from datetime import datetime
from flask_login import UserMixin
from sqlalchemy import case, func
from . import db, login_manager


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


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

    def __repr__(self):
        return f'<User {self.username}>'


class Project(db.Model):
    __tablename__ = 'projects'
    id = db.Column(db.Integer, primary_key=True)
    customer_name = db.Column(db.String(100), nullable=False)
    mobile = db.Column(db.String(20), nullable=False)
    email = db.Column(db.String(100), nullable=True)
    address = db.Column(db.Text, nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    grand_total    = db.Column(db.Float, default=0.0)
    discount_type  = db.Column(db.String(20), default='none')   # 'none', 'percentage', 'fixed'
    discount_value = db.Column(db.Float, default=0.0)
    status = db.Column(db.String(20), default='complete', nullable=False)
    plywood_thickness = db.Column(db.Text, nullable=True, default='')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    rooms     = db.relationship('Room',           backref='project', lazy='dynamic', cascade='all, delete-orphan')
    payments  = db.relationship('Payment',        backref='project', lazy='dynamic', cascade='all, delete-orphan')
    edit_logs = db.relationship('ProjectEditLog', backref='project', lazy='dynamic', cascade='all, delete-orphan')

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
                key = key_fn(item)
                totals[key] = totals.get(key, 0.0) + item.area
        return totals

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
        if self.discount_type == 'percentage':
            return round(self.grand_total * (self.discount_value or 0) / 100, 2)
        elif self.discount_type == 'fixed':
            return round(min(self.discount_value or 0, self.grand_total), 2)
        return 0.0

    @property
    def final_total(self):
        return round(max(self.grand_total - self.discount_amount, 0), 2)

    @classmethod
    def final_total_sql(cls):
        """SQL expression equivalent of final_total, for aggregate queries."""
        gt = func.coalesce(cls.grand_total, 0.0)
        dv = func.coalesce(cls.discount_value, 0.0)
        discount = case(
            (cls.discount_type == 'percentage', gt * dv / 100.0),
            (cls.discount_type == 'fixed', case((dv < gt, dv), else_=gt)),
            else_=0.0,
        )
        return case((gt - discount > 0, gt - discount), else_=0.0)

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
    __tablename__ = 'items'
    id = db.Column(db.Integer, primary_key=True)
    room_id = db.Column(db.Integer, db.ForeignKey('rooms.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    length = db.Column(db.Float, nullable=False)
    width = db.Column(db.Float, nullable=False)
    area = db.Column(db.Float, nullable=False)
    wood_type = db.Column(db.String(50), nullable=False)
    work_type = db.Column(db.String(50), nullable=False, default='Box Work')

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
    rate_per_sqft = db.Column(db.Float, nullable=False)

    def __repr__(self):
        return f'<WoodRate {self.wood_type}: {self.rate_per_sqft}>'


class WorkTypeRate(db.Model):
    __tablename__ = 'work_type_rates'
    id = db.Column(db.Integer, primary_key=True)
    work_type = db.Column(db.String(50), unique=True, nullable=False)
    rate_per_sqft = db.Column(db.Float, nullable=False)

    def __repr__(self):
        return f'<WorkTypeRate {self.work_type}: {self.rate_per_sqft}>'


class ItemRate(db.Model):
    __tablename__ = 'item_rates'
    id            = db.Column(db.Integer, primary_key=True)
    wood_type     = db.Column(db.String(50), nullable=False)
    work_type     = db.Column(db.String(50), nullable=False)
    rate_per_sqft = db.Column(db.Float, nullable=False, default=0.0)
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

    @classmethod
    def get(cls, key, default=None):
        row = cls.query.get(key)
        return row.value if row else default

    @classmethod
    def get_many(cls, keys, default=''):
        """Fetch several settings in one query: {key: value or default}."""
        rows = {r.key: r.value for r in cls.query.filter(cls.key.in_(keys)).all()}
        return {k: rows.get(k) or default for k in keys}

    @classmethod
    def set(cls, key, value):
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
    amount              = db.Column(db.Float, nullable=False)
    note                = db.Column(db.String(200), nullable=True)
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
    amount           = db.Column(db.Float, nullable=False)
    created_at       = db.Column(db.DateTime, default=datetime.utcnow)

    project = db.relationship('Project')

    def __repr__(self):
        return f'<PaymentLink {self.razorpay_link_id} project={self.project_id}>'


class Notification(db.Model):
    """In-app notification for admin (e.g. auto payment received)."""
    __tablename__ = 'notifications'
    id         = db.Column(db.Integer, primary_key=True)
    title      = db.Column(db.String(200), nullable=False)
    message    = db.Column(db.Text, nullable=False)
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
