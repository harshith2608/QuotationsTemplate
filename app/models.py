from datetime import datetime
from flask_login import UserMixin
from . import db, login_manager
from .crypto import EncryptedFloat, EncryptedText, decrypt, encrypt
from .catalog import STAGES, DEFAULT_STAGE


@login_manager.user_loader
def load_user(user_id):
    # In the shared trials app ids are "<slug>:<id>", so a session from one trial is useless in another
    from .tenancy import current_slug
    slug, _, raw = str(user_id).rpartition(':')
    if (slug or None) != current_slug() or not raw.isdigit():
        return None
    return User.query.get(int(raw))


class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    full_name = db.Column(db.String(120), nullable=True)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='employee')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def display_name(self):
        """Returns full_name if set, otherwise falls back to username."""
        return self.full_name.strip() if self.full_name and self.full_name.strip() else self.username
    projects = db.relationship('Project', backref='creator', lazy='dynamic',
                               foreign_keys='Project.created_by')

    @property
    def is_admin(self):
        return self.role == 'admin'

    def get_id(self):
        from .tenancy import current_slug
        slug = current_slug()
        return f'{slug}:{self.id}' if slug else str(self.id)

    def __repr__(self):
        return f'<User {self.username}>'


class Project(db.Model):
    __tablename__ = 'projects'
    id = db.Column(db.Integer, primary_key=True)
    # Customer details and amounts are encrypted at rest (app/crypto.py): never filter,
    # sort or sum these in SQL; do it in Python after loading.
    customer_name = db.Column(EncryptedText, nullable=False)
    mobile = db.Column(EncryptedText, nullable=False)
    email = db.Column(EncryptedText, nullable=True)
    address = db.Column(EncryptedText, nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    grand_total    = db.Column(EncryptedFloat, default=0.0)
    discount_type  = db.Column(db.String(20), default='none')   # 'none', 'percentage', 'fixed'
    discount_value = db.Column(EncryptedFloat, default=0.0)
    status = db.Column(db.String(20), default='complete', nullable=False)   # 'complete' or 'draft' (form auto-save)
    # Workflow stage, see catalog.STAGES (pending → confirmed → ongoing → completed, plus on_hold / cancelled)
    stage = db.Column(db.String(20), nullable=False, default=DEFAULT_STAGE,
                      server_default=DEFAULT_STAGE, index=True)
    stage_changed_at = db.Column(db.DateTime, nullable=True)
    plywood_thickness = db.Column(db.Text, nullable=True, default='')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    rooms     = db.relationship('Room',           backref='project', lazy='dynamic', cascade='all, delete-orphan')
    payments  = db.relationship('Payment',        backref='project', lazy='dynamic', cascade='all, delete-orphan')
    edit_logs = db.relationship('ProjectEditLog', backref='project', lazy='dynamic', cascade='all, delete-orphan')
    stage_changes = db.relationship('ProjectStageChange', backref='project', lazy='dynamic',
                                    cascade='all, delete-orphan',
                                    order_by='ProjectStageChange.changed_at.desc()')

    @property
    def stage_info(self):
        """(label, icon, text colour, background colour) for the current stage."""
        return STAGES.get(self.stage, STAGES[DEFAULT_STAGE])

    def set_stage(self, new_stage, user, note=None):
        """Move to a new stage and record it in the history. Returns False if unchanged/invalid."""
        if new_stage not in STAGES or new_stage == self.stage:
            return False
        now = datetime.utcnow()
        db.session.add(ProjectStageChange(project_id=self.id, from_stage=self.stage, to_stage=new_stage,
                                          changed_by=user.id if user else None, changed_at=now,
                                          note=(note or '').strip()[:200] or None))
        self.stage = new_stage
        self.stage_changed_at = now
        return True

    def rooms_with_items(self):
        """
        Load this project's rooms and all their items in two queries (instead of
        one query per room). Each room gets an .item_list attribute, which
        Room.total_area also uses, so callers can loop without re-querying.
        """
        rooms = self.rooms.order_by(Room.id).all()
        items_by_room = {r.id: [] for r in rooms}
        if rooms:
            for item in Item.query.filter(Item.room_id.in_(items_by_room)).order_by(Item.id):
                items_by_room[item.room_id].append(item)
        for room in rooms:
            room.item_list = items_by_room[room.id]
        return rooms

    def _area_totals(self, key_fn, rooms=None):
        totals = {}
        for room in (rooms if rooms is not None else self.rooms_with_items()):
            for item in room.item_list:
                if item.is_fixed:
                    continue          # fittings have no area / material
                key = key_fn(item)
                totals[key] = totals.get(key, 0.0) + item.area
        return totals

    def fixed_items_total(self, rooms=None):
        """Sum of all fittings & accessories (quantity × unit price)."""
        return round(sum((i.quantity or 0) * (i.unit_price or 0)
                         for room in (rooms if rooms is not None else self.rooms_with_items())
                         for i in room.item_list if i.is_fixed), 2)

    def get_wood_totals(self, rooms=None):
        """Returns dict of {wood_type: total_area}. Pass preloaded rooms to avoid re-querying."""
        return self._area_totals(lambda i: i.wood_type, rooms)

    def get_item_totals(self, rooms=None):
        """Returns dict of {'wood_type|work_type': total_area}. Pass preloaded rooms to avoid re-querying."""
        return self._area_totals(lambda i: f'{i.wood_type}|{i.work_type}', rooms)

    def get_work_totals(self, rooms=None):
        """Returns dict of {work_type: total_area}. Pass preloaded rooms to avoid re-querying."""
        return self._area_totals(lambda i: i.work_type, rooms)

    @property
    def discount_amount(self):
        gt = self.grand_total or 0
        if self.discount_type == 'percentage':
            return round(gt * (self.discount_value or 0) / 100, 2)
        elif self.discount_type == 'fixed':
            return round(min(self.discount_value or 0, gt), 2)
        return 0.0

    @property
    def final_total(self):
        return round(max((self.grand_total or 0) - self.discount_amount, 0), 2)

    def __repr__(self):
        return f'<Project {self.id}: {self.customer_name}>'


class Room(db.Model):
    __tablename__ = 'rooms'
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('projects.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    items = db.relationship('Item', backref='room', lazy='dynamic',
                            cascade='all, delete-orphan')

    @property
    def total_area(self):
        # Use items preloaded by Project.rooms_with_items() when available
        items = getattr(self, 'item_list', None)
        return sum(item.area for item in (self.items if items is None else items))

    def __repr__(self):
        return f'<Room {self.name}>'


class Item(db.Model):
    """
    A line in a room. Two kinds:
      * 'measured' — length × width = area, priced by the material/work rate per sqft
      * 'fixed'    — fittings & accessories (e.g. Magic Corner): quantity × unit price,
                     no dimensions (length/width/area are 0, wood/work types empty)
    """
    __tablename__ = 'items'
    id = db.Column(db.Integer, primary_key=True)
    room_id = db.Column(db.Integer, db.ForeignKey('rooms.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    length = db.Column(db.Float, nullable=False)
    width = db.Column(db.Float, nullable=False)
    area = db.Column(db.Float, nullable=False)
    wood_type = db.Column(db.String(50), nullable=False)
    work_type = db.Column(db.String(50), nullable=False, default='Box Work')
    item_type = db.Column(db.String(10), nullable=False, default='measured', server_default='measured')
    quantity = db.Column(db.Float, nullable=True)
    unit_price = db.Column(EncryptedFloat, nullable=True)

    @property
    def is_fixed(self):
        return self.item_type == 'fixed'

    def cost(self, item_rates):
        """Amount for this line. item_rates: {'wood|work': rate per sqft}."""
        if self.is_fixed:
            return (self.quantity or 0) * (self.unit_price or 0)
        return self.area * item_rates.get(f'{self.wood_type}|{self.work_type}', 0)

    def __repr__(self):
        return f'<Item {self.name}>'


class MasterRoom(db.Model):
    __tablename__ = 'master_rooms'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)

    def __repr__(self):
        return f'<MasterRoom {self.name}>'


class MasterItem(db.Model):
    __tablename__ = 'master_items'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)

    def __repr__(self):
        return f'<MasterItem {self.name}>'


class WoodRate(db.Model):
    __tablename__ = 'wood_rates'
    id = db.Column(db.Integer, primary_key=True)
    wood_type = db.Column(db.String(50), unique=True, nullable=False)
    rate_per_sqft = db.Column(EncryptedFloat, nullable=False)

    def __repr__(self):
        return f'<WoodRate {self.wood_type}: {self.rate_per_sqft}>'


class WorkTypeRate(db.Model):
    __tablename__ = 'work_type_rates'
    id = db.Column(db.Integer, primary_key=True)
    work_type = db.Column(db.String(50), unique=True, nullable=False)
    rate_per_sqft = db.Column(EncryptedFloat, nullable=False)

    def __repr__(self):
        return f'<WorkTypeRate {self.work_type}: {self.rate_per_sqft}>'


class ItemRate(db.Model):
    __tablename__ = 'item_rates'
    id            = db.Column(db.Integer, primary_key=True)
    wood_type     = db.Column(db.String(50), nullable=False)
    work_type     = db.Column(db.String(50), nullable=False)
    rate_per_sqft = db.Column(EncryptedFloat, nullable=False, default=0.0)
    __table_args__ = (db.UniqueConstraint('wood_type', 'work_type', name='uq_item_rate'),)
    def __repr__(self):
        return f'<ItemRate {self.wood_type}|{self.work_type}: {self.rate_per_sqft}>'


class ProjectAccess(db.Model):
    """Grants an employee access to a project they didn't create."""
    __tablename__ = 'project_access'
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False)
    user_id    = db.Column(db.Integer, db.ForeignKey('users.id',    ondelete='CASCADE'), nullable=False)
    granted_by = db.Column(db.Integer, db.ForeignKey('users.id'),   nullable=False)
    granted_at = db.Column(db.DateTime, default=datetime.utcnow)

    grantee = db.relationship('User', foreign_keys=[user_id])

    __table_args__ = (db.UniqueConstraint('project_id', 'user_id', name='uq_project_access'),)

    def __repr__(self):
        return f'<ProjectAccess project={self.project_id} user={self.user_id}>'


class AppSetting(db.Model):
    """Key-value store for admin-configurable app settings (Razorpay, UPI, bank)."""
    __tablename__ = 'app_settings'
    key   = db.Column(db.String(100), primary_key=True)
    value = db.Column(db.Text, nullable=True)

    # Settings stored encrypted (secrets and bank details); everything else is plain text
    ENCRYPTED_KEYS = frozenset({'razorpay_key_secret', 'webhook_secret', 'smtp_pass', 'smtp_user',
                                'account_number', 'ifsc_code'})

    @classmethod
    def _out(cls, key, value):
        return decrypt(value) if key in cls.ENCRYPTED_KEYS else value

    @classmethod
    def get(cls, key, default=None):
        row = cls.query.get(key)
        return cls._out(key, row.value) if row else default

    @classmethod
    def get_many(cls, keys, default=''):
        """Fetch several settings in one query: {key: value or default}."""
        rows = {r.key: cls._out(r.key, r.value) for r in cls.query.filter(cls.key.in_(keys)).all()}
        return {k: rows.get(k) or default for k in keys}

    @classmethod
    def set(cls, key, value):
        if key in cls.ENCRYPTED_KEYS and value:
            value = encrypt(value)
        row = cls.query.get(key)
        if row:
            row.value = value
        else:
            db.session.add(cls(key=key, value=value or ''))

    def __repr__(self):
        return f'<AppSetting {self.key}>'


class Payment(db.Model):
    """Records a partial or full payment made by a customer for a project."""
    __tablename__ = 'payments'
    id                  = db.Column(db.Integer, primary_key=True)
    project_id          = db.Column(db.Integer, db.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False)
    amount              = db.Column(EncryptedFloat, nullable=False)
    note                = db.Column(EncryptedText, nullable=True)
    recorded_by         = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    recorded_at         = db.Column(db.DateTime, default=datetime.utcnow)
    source              = db.Column(db.String(20), default='manual')   # 'manual' or 'razorpay'
    razorpay_payment_id = db.Column(db.String(100), nullable=True, unique=True)

    recorder = db.relationship('User')

    def __repr__(self):
        return f'<Payment project={self.project_id} amount={self.amount}>'


class PaymentLink(db.Model):
    """Tracks generated Razorpay payment links so webhooks can find the right project."""
    __tablename__ = 'payment_links'
    id               = db.Column(db.Integer, primary_key=True)
    project_id       = db.Column(db.Integer, db.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False)
    razorpay_link_id = db.Column(db.String(100), unique=True, nullable=False)
    amount           = db.Column(EncryptedFloat, nullable=False)
    created_at       = db.Column(db.DateTime, default=datetime.utcnow)

    project = db.relationship('Project')

    def __repr__(self):
        return f'<PaymentLink {self.razorpay_link_id} project={self.project_id}>'


class Notification(db.Model):
    """In-app notification for admin (e.g. auto payment received)."""
    __tablename__ = 'notifications'
    id         = db.Column(db.Integer, primary_key=True)
    title      = db.Column(EncryptedText, nullable=False)
    message    = db.Column(EncryptedText, nullable=False)
    project_id = db.Column(db.Integer, db.ForeignKey('projects.id', ondelete='SET NULL'), nullable=True)
    is_read    = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    project = db.relationship('Project')

    def __repr__(self):
        return f'<Notification {self.id} read={self.is_read}>'


class ProjectEditLog(db.Model):
    __tablename__ = 'project_edit_logs'
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('projects.id'), nullable=False)
    edited_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    edited_at = db.Column(db.DateTime, default=datetime.utcnow)

    editor = db.relationship('User')

    def __repr__(self):
        return f'<EditLog project={self.project_id} by={self.edited_by}>'


class ProjectStageChange(db.Model):
    """History of a quotation's workflow stage changes."""
    __tablename__ = 'project_stage_changes'
    id         = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False, index=True)
    from_stage = db.Column(db.String(20), nullable=True)
    to_stage   = db.Column(db.String(20), nullable=False)
    changed_by = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    changed_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    note       = db.Column(EncryptedText, nullable=True)

    user = db.relationship('User')

    def __repr__(self):
        return f'<StageChange project={self.project_id} {self.from_stage}→{self.to_stage}>'


class PriceListItem(db.Model):
    """Admin-managed fittings & accessories price list (Admin → Rates)."""
    __tablename__ = 'price_list_items'
    id    = db.Column(db.Integer, primary_key=True)
    name  = db.Column(db.String(100), unique=True, nullable=False)
    price = db.Column(EncryptedFloat, nullable=False, default=0.0)
    unit  = db.Column(db.String(30), nullable=True)

    def __repr__(self):
        return f'<PriceListItem {self.name}: {self.price}>'


class Lead(db.Model):
    """A free-trial request from the marketing site's form. Survives the nightly demo reset."""
    __tablename__ = 'leads'
    id            = db.Column(db.Integer, primary_key=True)
    created_at    = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    name          = db.Column(EncryptedText, nullable=False)
    phone         = db.Column(EncryptedText, nullable=False)       # normalised: 91XXXXXXXXXX
    business_type = db.Column(db.String(20), nullable=False)       # interiors / furniture / other
    business_other = db.Column(EncryptedText, nullable=True)       # free text when "other"
    source        = db.Column(db.String(200), nullable=True)       # utm_source / utm_campaign, page
    ip_hash       = db.Column(db.String(64), nullable=True, index=True)  # for rate limiting only

    def __repr__(self):
        return f'<Lead {self.id}>'
