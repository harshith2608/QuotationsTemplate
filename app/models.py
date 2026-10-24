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
    __mapper_args__ = {'eager_defaults': False}   # never read the plywood column back after saving
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
    # The quotation's plywood (Admin → Rates → Plywood); None = the business's default. Older quotations keep
    # plywood_thickness (a free list, information only). Deferred: safe before the database update adds it.
    # FetchedValue: left out of INSERTs unless set, so new quotations save fine before the column exists
    plywood = db.deferred(db.Column(db.String(60), nullable=True, server_default=db.FetchedValue()))
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
        from . import layout
        rq = self.rooms.order_by(Room.id)
        if layout.description_ready():
            from sqlalchemy.orm import undefer
            rq = rq.options(undefer(Room.description))       # with the rooms, not one query per room
        rooms = rq.all()
        items_by_room = {r.id: [] for r in rooms}
        if rooms:
            from . import plywood
            q = Item.query.filter(Item.room_id.in_(items_by_room)).order_by(Item.id)
            if plywood.table_ready():
                from sqlalchemy.orm import undefer
                q = q.options(undefer(Item.plywood))          # one query, not one per item
            from . import boq
            if boq.ready():
                from sqlalchemy.orm import undefer
                q = q.options(undefer(Item.description), undefer(Item.unit))
            for item in q:
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
                         for i in room.item_list if i.is_fitting), 2)

    def boq_items_total(self, rooms=None):
        """Sum of all BOQ lines (quantity × rate)."""
        return round(sum((i.quantity or 0) * (i.unit_price or 0)
                         for room in (rooms if rooms is not None else self.rooms_with_items())
                         for i in room.item_list if i.is_boq), 2)

    def get_wood_totals(self, rooms=None):
        """Returns dict of {wood_type: total_area}. Pass preloaded rooms to avoid re-querying."""
        return self._area_totals(lambda i: i.wood_type, rooms)

    def get_item_totals(self, rooms=None):
        """{price key: total area}: 'Material|Work', or 'Material|Work|Plywood' when an item is on a plywood other
        than the default (it has its own rate, see plywood.rate_map). Pass preloaded rooms to avoid re-querying."""
        from . import plywood
        ply = plywood.project_plywood(self)
        return self._area_totals(lambda i: plywood.item_key(i, ply), rooms)

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
    __mapper_args__ = {'eager_defaults': False}   # never read the description column back after saving
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('projects.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    # What the room is made of, for the Initial Quotation ("Carcass: BWP ply · Shutters: 1mm laminate"); None = worked
    # out from its materials. Deferred + FetchedValue: rooms save fine before the database update adds it.
    description = db.deferred(db.Column(db.Text, nullable=True, server_default=db.FetchedValue()))
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
    A line in a room. Three kinds:
      * 'measured' — length × width = area, priced by the material/work rate per sqft
      * 'fixed'    — fittings & accessories (e.g. Magic Corner): quantity × unit price,
                     no dimensions (length/width/area are 0, wood/work types empty)
      * 'boq'      — a BOQ line (turnkey work, when the business has BOQ lines on, see app/boq.py): its own
                     description, quantity, unit (sqft, rft, nos, lump sum…) and rate; priced like a fitting
    Fittings and BOQ lines are both "priced" (quantity × unit price, is_fixed); is_fitting / is_boq tell them apart.
    """
    __tablename__ = 'items'
    __mapper_args__ = {'eager_defaults': False}   # never read the plywood column back after saving
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
    plywood = db.deferred(db.Column(db.String(60), nullable=True,    # this item's own plywood; None = the quotation's
                                    server_default=db.FetchedValue()))  # (left out of INSERTs unless set: safe before the update)
    # BOQ lines (and any item): a description and a unit; deferred like plywood, so items save before the update
    description = db.deferred(db.Column(db.Text, nullable=True, server_default=db.FetchedValue()))
    unit = db.deferred(db.Column(db.String(20), nullable=True, server_default=db.FetchedValue()))

    @property
    def is_fixed(self):
        """Priced as quantity × unit price, no area: a fitting or a BOQ line."""
        return self.item_type in ('fixed', 'boq')

    @property
    def is_fitting(self):
        return self.item_type == 'fixed'

    @property
    def is_boq(self):
        return self.item_type == 'boq'

    @property
    def price_to_follow(self):
        """A BOQ line whose price isn't fixed yet (no rate): printed as "Price to follow", not added to the total."""
        return self.is_boq and self.unit_price is None

    @property
    def boq_count(self):
        """No's of a BOQ line measured by size (its quantity / one piece's area or length), else 1."""
        from . import boq
        if not (self.is_boq and self.length):
            return 1
        unit = self.unit if boq.ready() else ''
        one = boq.quantity_from_size(unit, self.length, self.width or 0, 1)
        return max(int(round((self.quantity or 0) / one)), 1) if one else 1

    @property
    def finish(self):
        """A BOQ line's finish when not the base one ('Acrylic'), else '' (app/finishes.py; kept in wood_type)."""
        return (self.wood_type or '') if self.is_boq else ''

    @property
    def display_name(self):
        """The name as printed: 'Wardrobe (Acrylic finish)' for a BOQ line in another finish."""
        from .finishes import label
        return label(self.name, self.finish)

    @property
    def note(self):
        """The item's description, or '' (never reads the column before the database update)."""
        from . import boq
        return (self.description or '') if boq.ready() else ''

    @property
    def unit_text(self):
        """A BOQ line's unit as printed ('Sq.ft', 'Nos.', 'LS'…)."""
        from . import boq
        return boq.unit_text((self.unit if boq.ready() else '') or 'nos')

    @property
    def count(self):
        """How many of this measured item ("No's"); its area already includes it. Fittings use quantity."""
        return 1 if self.is_fixed else max(int(round(self.quantity or 1)), 1)

    def cost(self, item_rates, project_plywood=None):
        """Amount for this line. item_rates: plywood.rate_map(); project_plywood: the quotation's plywood."""
        if self.is_fixed:
            return (self.quantity or 0) * (self.unit_price or 0)
        from . import plywood
        return self.area * item_rates.get(plywood.item_key(self, project_plywood), 0)

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
    """Grants an employee access to a project they didn't create: view, or view and edit (can_edit)."""
    __tablename__ = 'project_access'
    __mapper_args__ = {'eager_defaults': False}   # never read can_edit back after saving
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False)
    user_id    = db.Column(db.Integer, db.ForeignKey('users.id',    ondelete='CASCADE'), nullable=False)
    granted_by = db.Column(db.Integer, db.ForeignKey('users.id'),   nullable=False)
    granted_at = db.Column(db.DateTime, default=datetime.utcnow)
    # True: may edit the quotation too (never delete: that stays admin-only). Deferred + FetchedValue: safe before
    # the database update adds it (access.edit_ready() guards every read).
    can_edit   = db.deferred(db.Column(db.Boolean, nullable=False, server_default=db.FetchedValue()))

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

    # Settings read during a request are kept for the rest of it (raw values, None = no row), one dict per database
    # schema: the operator console reads several businesses in one request. Cleared on rollback.
    @classmethod
    def _cache(cls):
        from flask import g, has_app_context
        if not has_app_context():
            return None
        from . import tenancy
        return g.setdefault('_app_settings', {}).setdefault(tenancy.current_schema() or '', {})

    @classmethod
    def prefetch(cls, keys):
        """Raw values for `keys` ({key: value or None}), reading only the ones not already read in this request."""
        cache = cls._cache()
        if cache is None:
            found = {r.key: r.value for r in cls.query.filter(cls.key.in_(keys)).all()}
            return {k: found.get(k) for k in keys}
        missing = [k for k in dict.fromkeys(keys) if k not in cache]
        if missing:
            found = {r.key: r.value for r in cls.query.filter(cls.key.in_(missing)).all()}
            for k in missing:
                cache[k] = found.get(k)
        return cache

    @classmethod
    def get(cls, key, default=None):
        raw = cls.prefetch([key]).get(key)
        return cls._out(key, raw) if raw is not None else default

    @classmethod
    def get_many(cls, keys, default=''):
        """Fetch several settings in one query (or none, if already read): {key: value or default}."""
        raw = cls.prefetch(keys)
        return {k: (cls._out(k, raw[k]) if raw.get(k) is not None else None) or default for k in keys}

    @classmethod
    def set(cls, key, value):
        if key in cls.ENCRYPTED_KEYS and value:
            value = encrypt(value)
        row = cls.query.get(key)
        if row:
            row.value = value
        else:
            db.session.add(cls(key=key, value=value or ''))
        cache = cls._cache()
        if cache is not None:
            cache[key] = value if row else (value or '')

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


class BoqItem(db.Model):
    """A saved BOQ line (businesses with BOQ lines on): remembered the first time it's used on a quotation, then
    offered by name with its description, unit and rate as defaults. A quotation can change them for itself; the
    default only changes from Admin → Rates or with "Save as my default" (app/boq.py)."""
    __tablename__ = 'boq_items'
    id          = db.Column(db.Integer, primary_key=True)
    name        = db.Column(db.String(100), unique=True, nullable=False)
    description = db.Column(db.Text, nullable=True)
    unit        = db.Column(db.String(20), nullable=True)
    category    = db.Column(db.String(60), nullable=True)    # groups the "Add from my lines" checklist
    rate        = db.Column(EncryptedFloat, nullable=False, default=0.0)

    def __repr__(self):
        return f'<BoqItem {self.name}: {self.rate}>'


class Lead(db.Model):
    """A free-trial request from the marketing site's form. Survives the nightly demo reset."""
    __tablename__ = 'leads'
    id            = db.Column(db.Integer, primary_key=True)
    created_at    = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    name          = db.Column(EncryptedText, nullable=False)
    phone         = db.Column(EncryptedText, nullable=False)       # normalised: 91XXXXXXXXXX
    business_type = db.Column(db.String(20), nullable=False)       # interiors / furniture / other
    business_other = db.Column(EncryptedText, nullable=True)       # free text when "other"
    # Deferred: not part of normal SELECTs, so the form keeps working right after a deploy, before the update adds it
    company_name  = db.deferred(db.Column(EncryptedText, nullable=True))
    city          = db.deferred(db.Column(EncryptedText, nullable=True))   # added later: read only once present
    email         = db.deferred(db.Column(EncryptedText, nullable=True))   # optional on the form
    source        = db.Column(db.String(200), nullable=True)       # utm_source / utm_campaign, page
    ip_hash       = db.Column(db.String(64), nullable=True, index=True)  # for rate limiting only

    def __repr__(self):
        return f'<Lead {self.id}>'


# ── Quote to cash: revisions, online approval, invoices, reminders, costs ─────
# All in their own tables (nothing added to existing ones), so a deploy works before the database update;
# see app/billing.py ready().

class QuoteRevision(db.Model):
    """A saved version of a quotation (R1, R2…): a snapshot of what the customer was quoted at the time."""
    __tablename__ = 'quote_revisions'
    id         = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False, index=True)
    number     = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    total      = db.Column(EncryptedFloat, nullable=False, default=0.0)
    snapshot   = db.Column(EncryptedText, nullable=False)          # JSON, see billing.quotation_snapshot

    user = db.relationship('User')
    __table_args__ = (db.UniqueConstraint('project_id', 'number', name='uq_quote_revision'),)

    def __repr__(self):
        return f'<QuoteRevision project={self.project_id} R{self.number}>'


class QuoteShare(db.Model):
    """A private link the customer opens to view and accept a quotation online."""
    __tablename__ = 'quote_shares'
    id         = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False, index=True)
    token      = db.Column(db.String(64), unique=True, nullable=False, index=True)
    active     = db.Column(db.Boolean, nullable=False, default=True)
    detail     = db.Column(db.String(10), nullable=False, default='summary')   # 'summary' (by material) | 'full'
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    first_viewed_at = db.Column(db.DateTime, nullable=True)
    last_viewed_at  = db.Column(db.DateTime, nullable=True)
    view_count      = db.Column(db.Integer, nullable=False, default=0)

    def __repr__(self):
        return f'<QuoteShare project={self.project_id}>'


class QuoteResponse(db.Model):
    """The customer's answer on the online quotation: accepted, or asked for changes."""
    __tablename__ = 'quote_responses'
    id          = db.Column(db.Integer, primary_key=True)
    share_id    = db.Column(db.Integer, db.ForeignKey('quote_shares.id', ondelete='CASCADE'), nullable=False)
    project_id  = db.Column(db.Integer, db.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False, index=True)
    kind        = db.Column(db.String(12), nullable=False)           # 'accepted' | 'changes'
    name        = db.Column(EncryptedText, nullable=True)            # typed by the customer
    note        = db.Column(EncryptedText, nullable=True)
    total       = db.Column(EncryptedFloat, nullable=True)           # quotation total they saw
    revision    = db.Column(db.Integer, nullable=True)               # revision number they saw
    created_at  = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f'<QuoteResponse project={self.project_id} {self.kind}>'


class Invoice(db.Model):
    """A tax invoice issued from a quotation. Everything printed is frozen in `data` when it is issued."""
    __tablename__ = 'invoices'
    id           = db.Column(db.Integer, primary_key=True)
    project_id   = db.Column(db.Integer, db.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False, index=True)
    number       = db.Column(db.String(20), unique=True, nullable=False)    # e.g. INV/2026-27/001
    fy           = db.Column(db.String(7), nullable=False)                   # financial year, e.g. 2026-27
    seq          = db.Column(db.Integer, nullable=False)
    issued_on    = db.Column(db.Date, nullable=False)
    status       = db.Column(db.String(12), nullable=False, default='issued')   # 'issued' | 'cancelled'
    total        = db.Column(EncryptedFloat, nullable=False, default=0.0)
    data         = db.Column(EncryptedText, nullable=False)                  # JSON, see billing.build_invoice
    created_at   = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    created_by   = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    cancelled_at = db.Column(db.DateTime, nullable=True)

    project = db.relationship('Project')
    __table_args__ = (db.UniqueConstraint('fy', 'seq', name='uq_invoice_seq'),)

    @property
    def with_gst(self):
        from .billing import invoice_data
        return bool(invoice_data(self)['gst'])

    def __repr__(self):
        return f'<Invoice {self.number}>'


class PaymentReminder(db.Model):
    """A payment reminder sent on WhatsApp (for "last reminded" on Balances due)."""
    __tablename__ = 'payment_reminders'
    id         = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False, index=True)
    sent_at    = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    sent_by    = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    amount     = db.Column(EncryptedFloat, nullable=True)

    def __repr__(self):
        return f'<PaymentReminder project={self.project_id}>'


class CostRate(db.Model):
    """What a material (per sqft) or a fitting (per unit) costs the business. Admin-only, never printed."""
    __tablename__ = 'cost_rates'
    id   = db.Column(db.Integer, primary_key=True)
    kind = db.Column(db.String(10), nullable=False)       # 'material' (name = 'Material|Work') | 'fitting'
    name = db.Column(db.String(120), nullable=False)
    cost = db.Column(EncryptedFloat, nullable=False, default=0.0)
    __table_args__ = (db.UniqueConstraint('kind', 'name', name='uq_cost_rate'),)

    def __repr__(self):
        return f'<CostRate {self.kind} {self.name}>'


class DemoStat(db.Model):
    """Anonymous daily counts for the public demo (no personal data). Survives the nightly demo reset."""
    __tablename__ = 'demo_stats'
    day        = db.Column(db.Date, primary_key=True)            # UTC date
    starts     = db.Column(db.Integer, nullable=False, default=0)   # visitors who opened the demo
    quotations = db.Column(db.Integer, nullable=False, default=0)   # quotations they created
    pdfs       = db.Column(db.Integer, nullable=False, default=0)   # PDFs they opened
    # browsers opening the marketing site for the first time; added by a later database update, so no Python default:
    # inserts leave it out and the database fills in 0 (and nothing breaks before the update)
    site_visitors = db.Column(db.Integer, nullable=False, server_default='0')

    def __repr__(self):
        return f'<DemoStat {self.day}>'


class Tutorial(db.Model):
    """A how-to video on the marketing site's Tutorials page (hosted on YouTube), managed from the ops console.
    Public content, so not encrypted. Survives the nightly demo reset."""
    __tablename__ = 'tutorials'
    id         = db.Column(db.Integer, primary_key=True)
    position   = db.Column(db.Integer, nullable=False, default=0)       # order on the page, lowest first
    title      = db.Column(db.String(120), nullable=False)
    about      = db.Column(db.String(300), nullable=False, default='')
    length     = db.Column(db.String(20), nullable=False, default='')   # e.g. '4 min'
    youtube_id = db.Column(db.String(11))                               # none yet → not shown
    hidden     = db.Column(db.Boolean, nullable=False, default=False)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    # Landscape (16:9) video, shown wide on the page; phone tutorials are 9:16. Deferred, with a server default, so
    # nothing reads or writes it before the database update that adds it (marketing.tutorials_wide_ready).
    wide       = db.deferred(db.Column(db.Boolean, nullable=False, server_default=db.false()))
    __mapper_args__ = {'eager_defaults': False}

    def __repr__(self):
        return f'<Tutorial {self.title}>'


class Material(db.Model):
    """A material a business quotes per sqft (Acrylic, Laminates, Glass, PU, Wallpaper…), managed in Admin → Rates.
    With work types, it is priced per (material, Box/Frame Work); without, one rate per sqft (work_type '').
    Items store the material by name; renaming updates them. Hidden materials stay valid on old quotations."""
    __tablename__ = 'materials'
    __mapper_args__ = {'eager_defaults': False}   # never read the plywood column back after saving
    id              = db.Column(db.Integer, primary_key=True)
    name            = db.Column(db.String(60), unique=True, nullable=False)
    uses_work_types = db.Column(db.Boolean, nullable=False, default=True)
    active          = db.Column(db.Boolean, nullable=False, default=True)
    sort_order      = db.Column(db.Integer, nullable=False, default=0)
    # Priced on plywood: its rate changes with the quotation's plywood (Admin → Rates → Plywood). Deferred: safe
    # before the database update adds it (plywood.table_ready() guards every read).
    uses_plywood    = db.deferred(db.Column(db.Boolean, nullable=False, server_default=db.FetchedValue()))

    def __repr__(self):
        return f'<Material {self.name}>'


class PlywoodOption(db.Model):
    """A plywood a business offers (18mm BWP, 12mm MR…), managed in Admin → Rates. Material rates are for the
    default one; another adds its adjustment (₹ per sqft, can be negative) to plywood materials' rates."""
    __tablename__ = 'plywood_options'
    __mapper_args__ = {'eager_defaults': False}   # never read the details column back after saving
    id              = db.Column(db.Integer, primary_key=True)
    name            = db.Column(db.String(60), unique=True, nullable=False)
    adjustment      = db.Column(EncryptedFloat, nullable=False, default=0.0)   # selling, ₹/sqft vs the default
    cost_adjustment = db.Column(EncryptedFloat, nullable=True)                 # what it costs you extra; None = same
    is_default      = db.Column(db.Boolean, nullable=False, default=False)
    active          = db.Column(db.Boolean, nullable=False, default=True)
    sort_order      = db.Column(db.Integer, nullable=False, default=0)
    # Brand, grade, thickness, warranty… for {plywood_details} in the quotation sections. Deferred + FetchedValue:
    # safe before the database update adds it (plywood.details_ready() guards every read).
    details         = db.deferred(db.Column(db.Text, nullable=True, server_default=db.FetchedValue()))

    def __repr__(self):
        return f'<PlywoodOption {self.name}>'


from sqlalchemy import event as _event                     # noqa: E402
from sqlalchemy.orm import Session as _Session             # noqa: E402


@_event.listens_for(_Session, 'after_soft_rollback')
def _forget_settings(session, previous_transaction):
    """A rolled-back AppSetting.set must not stay in the request's settings cache."""
    from flask import g, has_app_context
    if has_app_context():
        g.pop('_app_settings', None)
