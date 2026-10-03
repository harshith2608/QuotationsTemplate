from flask import Blueprint, render_template, redirect, url_for, flash, request, abort
from flask_login import login_required, current_user
from werkzeug.security import generate_password_hash
from sqlalchemy import func
from . import db
from .models import User, Project, Item, Room, WoodRate, WorkTypeRate, ItemRate, MasterRoom, MasterItem, AppSetting, Notification
from .forms import CreateUserForm, ChangePasswordForm
from .decorators import admin_required
from .pdf_utils import DEFAULT_TERMS
from .catalog import WOOD_TYPES, WORK_TYPES
from .branding import EDITABLE_FIELDS, env_default

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')


@admin_bp.before_request
@login_required
def require_admin():
    if not current_user.is_admin:
        abort(403)


@admin_bp.route('/dashboard')
def dashboard():
    # Employee performance stats
    employee_stats = (
        db.session.query(
            User.id,
            User.username,
            func.count(Project.id).label('project_count'),
            func.coalesce(func.sum(Project.final_total_sql()), 0).label('total_value')
        )
        .outerjoin(Project, Project.created_by == User.id)
        .filter(User.role == 'employee')
        .group_by(User.id, User.username)
        .all()
    )

    # Wood type distribution (total area per wood type)
    wood_dist = (
        db.session.query(Item.wood_type, func.sum(Item.area).label('total_area'))
        .group_by(Item.wood_type)
        .all()
    )
    wood_labels = [w.wood_type for w in wood_dist]
    wood_data = [round(w.total_area, 2) for w in wood_dist]

    # Room type distribution (top 8)
    room_dist = (
        db.session.query(Room.name, func.count(Room.id).label('count'))
        .group_by(Room.name)
        .order_by(func.count(Room.id).desc())
        .limit(8)
        .all()
    )
    room_labels = [r.name for r in room_dist]
    room_data = [r.count for r in room_dist]

    # Overall stats
    total_projects = Project.query.count()
    total_value = db.session.query(func.coalesce(func.sum(Project.final_total_sql()), 0)).scalar()
    total_customers = db.session.query(func.count(func.distinct(Project.mobile))).scalar()
    total_employees = User.query.filter_by(role='employee').count()

    return render_template(
        'admin/dashboard.html',
        title='Admin Dashboard',
        employee_stats=employee_stats,
        wood_labels=wood_labels,
        wood_data=wood_data,
        room_labels=room_labels,
        room_data=room_data,
        total_projects=total_projects,
        total_value=total_value,
        total_customers=total_customers,
        total_employees=total_employees
    )


@admin_bp.route('/users')
def users():
    all_users = User.query.order_by(User.created_at.desc()).all()
    form = CreateUserForm()
    return render_template('admin/users.html', title='User Management',
                           users=all_users, form=form)


@admin_bp.route('/users/new', methods=['POST'])
def create_user():
    form = CreateUserForm()
    if form.validate_on_submit():
        existing = User.query.filter_by(username=form.username.data.strip()).first()
        if existing:
            flash('Username already exists.', 'danger')
        else:
            user = User(
                username=form.username.data.strip(),
                password_hash=generate_password_hash(form.password.data, method='pbkdf2:sha256'),
                role=form.role.data
            )
            db.session.add(user)
            db.session.commit()
            flash(f'User "{user.username}" created successfully.', 'success')
    else:
        for field, errors in form.errors.items():
            for error in errors:
                flash(f'{error}', 'danger')
    return redirect(url_for('admin.users'))


@admin_bp.route('/users/<int:user_id>/delete', methods=['POST'])
def delete_user(user_id):
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash('You cannot delete your own account.', 'danger')
        return redirect(url_for('admin.users'))
    if user.role == 'admin' and User.query.filter_by(role='admin').count() <= 1:
        flash('Cannot delete the last admin account.', 'danger')
        return redirect(url_for('admin.users'))
    # Re-assign projects to current admin before deleting
    Project.query.filter_by(created_by=user.id).update({'created_by': current_user.id})
    db.session.delete(user)
    db.session.commit()
    flash(f'User "{user.username}" deleted. Their projects were reassigned to you.', 'success')
    return redirect(url_for('admin.users'))


@admin_bp.route('/users/<int:user_id>/rename', methods=['POST'])
def rename_user(user_id):
    user = User.query.get_or_404(user_id)
    new_username = request.form.get('new_username', '').strip()
    full_name     = request.form.get('full_name', '').strip()
    if not new_username:
        flash('Username cannot be empty.', 'danger')
    elif User.query.filter(User.username == new_username, User.id != user_id).first():
        flash(f'Username "{new_username}" is already taken.', 'danger')
    else:
        old_name = user.username
        user.username  = new_username
        user.full_name = full_name or None
        db.session.commit()
        flash(f'User "{old_name}" updated successfully.', 'success')
    return redirect(url_for('admin.users'))


@admin_bp.route('/users/<int:user_id>/change-password', methods=['POST'])
def change_user_password(user_id):
    user = User.query.get_or_404(user_id)
    form = ChangePasswordForm()
    if form.validate_on_submit():
        user.password_hash = generate_password_hash(form.new_password.data, method='pbkdf2:sha256')
        db.session.commit()
        flash(f'Password for "{user.username}" updated.', 'success')
    else:
        for field, errors in form.errors.items():
            for error in errors:
                flash(error, 'danger')
    return redirect(url_for('admin.users'))


@admin_bp.route('/rates', methods=['GET', 'POST'])
def rates():
    item_rates_map = {(r.wood_type, r.work_type): r for r in ItemRate.query.all()}

    if request.method == 'POST' and 'item_rates_submit' in request.form:
        for wood in WOOD_TYPES:
            for work in WORK_TYPES:
                field_key = f"rate_{wood.lower()}_{work.lower().replace(' ', '_')}"
                try:
                    rate = float(request.form.get(field_key, 0))
                except (ValueError, TypeError):
                    rate = 0
                rate = max(0, rate)
                existing = item_rates_map.get((wood, work))
                if existing:
                    existing.rate_per_sqft = rate
                else:
                    db.session.add(ItemRate(wood_type=wood, work_type=work, rate_per_sqft=rate))
        db.session.commit()
        flash('Item rates updated successfully.', 'success')
        return redirect(url_for('admin.rates'))

    # Build a nested dict for the template: { wood_type: { work_type: rate } }
    item_rates = {}
    for wood in WOOD_TYPES:
        item_rates[wood] = {}
        for work in WORK_TYPES:
            r = item_rates_map.get((wood, work))
            item_rates[wood][work] = r.rate_per_sqft if r else 0.0

    return render_template('admin/rates.html', title='Manage Rates',
                           item_rates=item_rates,
                           wood_types=WOOD_TYPES, work_types=WORK_TYPES)


COMPANY_KEYS = [app_key for app_key, _, _ in EDITABLE_FIELDS.values()]


@admin_bp.route('/payment-settings', methods=['GET', 'POST'])
def payment_settings():
    KEYS = ['razorpay_key_id', 'razorpay_key_secret', 'webhook_secret',
            'upi_id', 'bank_name', 'account_name', 'account_number', 'ifsc_code',
            'admin_email', 'smtp_host', 'smtp_port', 'smtp_user', 'smtp_pass']
    if request.method == 'POST':
        for key in KEYS:
            val = request.form.get(key, '').strip()
            # Don't blank out secrets if field left empty
            if key in ('razorpay_key_secret', 'webhook_secret', 'smtp_pass') and not val:
                continue
            AppSetting.set(key, val)
        # Multi-line fields — preserve newlines, allow blanking
        AppSetting.set('material_specs',    request.form.get('material_specs',    '').strip())
        AppSetting.set('terms_conditions',  request.form.get('terms_conditions',  '').strip())
        # Company details — blank means "use the deployment's env default"
        for key in COMPANY_KEYS:
            AppSetting.set(key, request.form.get(key, '').strip())
        db.session.commit()
        flash('Settings updated successfully.', 'success')
        return redirect(url_for('admin.payment_settings'))
    settings = {k: AppSetting.get(k, '') for k in KEYS}
    settings['material_specs']    = AppSetting.get('material_specs',   '')
    settings['terms_conditions']  = AppSetting.get('terms_conditions', '') or DEFAULT_TERMS
    for key in COMPANY_KEYS:
        settings[key] = AppSetting.get(key, '')
    env_defaults = {key: env_default(key) for key in COMPANY_KEYS}
    return render_template('admin/payment_settings.html',
                           title='Payment Settings', settings=settings,
                           env_defaults=env_defaults)


@admin_bp.route('/notifications')
def notifications():
    all_notifs = Notification.query.order_by(Notification.created_at.desc()).all()
    # Mark all as read when page is opened
    Notification.query.filter_by(is_read=False).update({'is_read': True})
    db.session.commit()
    return render_template('admin/notifications.html',
                           title='Notifications', notifications=all_notifs)


@admin_bp.route('/notifications/clear', methods=['POST'])
def clear_notifications():
    Notification.query.delete()
    db.session.commit()
    flash('All notifications cleared.', 'success')
    return redirect(url_for('admin.notifications'))


@admin_bp.route('/projects')
def all_projects():
    return redirect(url_for('projects.list_projects'))
