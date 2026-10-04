from flask import Blueprint, render_template, redirect, url_for, flash, request, abort
from flask_login import login_required, current_user
from werkzeug.security import generate_password_hash
from sqlalchemy import func
from . import db
from .models import User, Project, Item, Room, WoodRate, WorkTypeRate, ItemRate, MasterRoom, MasterItem, AppSetting, Notification
from .forms import CreateUserForm, ChangePasswordForm
from .decorators import admin_required
from .pdf_utils import DEFAULT_TERMS
from .catalog import WOOD_TYPES, WORK_TYPES, STAGES
from . import branding

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

    # Pipeline: count and value per workflow stage (excluding unfinished drafts)
    stage_rows = (
        db.session.query(Project.stage, func.count(Project.id),
                         func.coalesce(func.sum(Project.final_total_sql()), 0))
        .filter(Project.status != 'draft')
        .group_by(Project.stage).all()
    )
    by_stage = {key: (count, value) for key, count, value in stage_rows}
    pipeline = [{'key': key, 'label': st[0], 'icon': st[1], 'color': st[2], 'bg': st[3],
                 'count': by_stage.get(key, (0, 0))[0], 'value': by_stage.get(key, (0, 0))[1]}
                for key, st in STAGES.items()]
    pipeline_max = max([p['count'] for p in pipeline] + [1])

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
        total_employees=total_employees,
        pipeline=pipeline,
        pipeline_max=pipeline_max
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


PAYMENT_KEYS = ['razorpay_key_id', 'razorpay_key_secret', 'webhook_secret',
                'upi_id', 'bank_name', 'account_name', 'account_number', 'ifsc_code']
EMAIL_KEYS = ['admin_email', 'smtp_host', 'smtp_port', 'smtp_user', 'smtp_pass']
SECRET_KEYS = {'razorpay_key_secret', 'webhook_secret', 'smtp_pass'}
SETTINGS_TABS = ('company', 'appearance', 'documents', 'email')


def _save_plain_settings(keys):
    for key in keys:
        val = request.form.get(key, '').strip()
        # Don't blank out secrets if the field was left empty
        if key in SECRET_KEYS and not val:
            continue
        AppSetting.set(key, val)


@admin_bp.route('/payment-settings', methods=['GET', 'POST'])
def payment_settings():
    if request.method == 'POST':
        _save_plain_settings(PAYMENT_KEYS)
        db.session.commit()
        flash('Payment settings updated.', 'success')
        return redirect(url_for('admin.payment_settings'))
    settings = AppSetting.get_many(PAYMENT_KEYS)
    webhook_url = url_for('projects.razorpay_webhook', _external=True)
    status = {
        'has_keys': bool(settings['razorpay_key_id'] and settings['razorpay_key_secret']),
        'has_secret': bool(settings['webhook_secret']),
        'mode': razorpay_mode(settings['razorpay_key_id']),
    }
    return render_template('admin/payment_settings.html', title='Payment Settings',
                           settings=settings, webhook_url=webhook_url, status=status)


def razorpay_mode(key_id):
    """'test', 'live' or None, from the Razorpay key prefix."""
    key_id = (key_id or '').strip()
    if key_id.startswith('rzp_test_'):
        return 'test'
    if key_id.startswith('rzp_live_'):
        return 'live'
    return None


@admin_bp.route('/payment-settings/test', methods=['POST'])
def test_razorpay():
    """Check the saved Razorpay keys by making a harmless read-only API call."""
    import base64
    import urllib.error
    import urllib.request
    key_id = AppSetting.get('razorpay_key_id', '').strip()
    secret = AppSetting.get('razorpay_key_secret', '').strip()
    if not key_id or not secret:
        flash('Save your Razorpay Key ID and Key Secret first, then test the connection.', 'warning')
        return redirect(url_for('admin.payment_settings'))
    token = base64.b64encode(f'{key_id}:{secret}'.encode()).decode()
    req = urllib.request.Request('https://api.razorpay.com/v1/payment_links?count=1',
                                 headers={'Authorization': f'Basic {token}'})
    try:
        with urllib.request.urlopen(req, timeout=10):
            pass
        mode = razorpay_mode(key_id)
        flash(f'Connected to Razorpay{" in " + mode.upper() + " mode" if mode else ""}. Your keys work.', 'success')
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            flash('Razorpay rejected these keys. Check the Key ID and Key Secret, and that they belong to the same mode (test or live).', 'danger')
        else:
            flash(f'Razorpay answered with error {exc.code}. Make sure Payment Links are enabled on your Razorpay account.', 'danger')
    except Exception:
        flash('Could not reach Razorpay. Please try again in a minute.', 'danger')
    return redirect(url_for('admin.payment_settings'))


@admin_bp.route('/settings/test-email', methods=['POST'])
def test_email():
    """Send a test message to the admin email using the saved SMTP settings."""
    import smtplib
    import socket
    from .projects import _send_email, EmailNotConfigured
    to = AppSetting.get('admin_email', '').strip() or AppSetting.get('smtp_user', '').strip()
    try:
        _send_email(to, f'Test email from {branding.get_brand()["name"]}',
                    'Your email settings work. Payment notifications will be sent from this account.',
                    raise_errors=True)
        flash(f'Test email sent to {to}. Check the inbox (and spam folder).', 'success')
    except EmailNotConfigured as exc:
        flash(str(exc), 'warning')
    except smtplib.SMTPAuthenticationError:
        flash('The email server rejected the username or password. For Gmail, use an App Password, not your normal password.', 'danger')
    except (socket.gaierror, ConnectionRefusedError):
        flash('Could not find or connect to that SMTP host. Check the host name and port.', 'danger')
    except (socket.timeout, TimeoutError):
        flash('The connection timed out. Check the SMTP host and port (587 or 465).', 'danger')
    except Exception as exc:
        flash(f'Email could not be sent: {exc}', 'danger')
    return redirect(url_for('admin.settings', tab='email'))


def _save_brand_fields(brand_keys):
    """Save validated brand fields. Blank = fall back to env/default. Returns list of error messages."""
    errors = []
    for key in brand_keys:
        app_key = branding.FIELDS[key][0]
        raw = request.form.get(app_key, '').strip()
        value = branding.clean_value(key, raw)
        if value is None:
            errors.append(f'Invalid value for {key.replace("_", " ")}: "{raw}".')
            continue
        if key == 'background' and value and branding.luminance(value) < branding.MIN_BACKGROUND_LUMINANCE:
            errors.append('Page background is too dark for text to stay readable — pick a lighter shade.')
            continue
        # Store blank when it equals the deployment default, so env changes still apply
        AppSetting.set(app_key, '' if value == branding.env_default(key) and key in branding.THEME_KEYS else value)
    return errors


def _save_company_fields():
    """
    Save the Company tab. Company name and GSTIN lock once saved (see branding.locked_fields);
    saving a new value for them requires ticking the confirmation box. Returns error messages.
    """
    errors = []
    locked = branding.locked_fields()
    confirmed = bool(request.form.get('confirm_identity'))
    needs_confirm = []
    for key in branding.COMPANY_KEYS:
        app_key = branding.FIELDS[key][0]
        raw = request.form.get(app_key, '').strip()
        if key in ('name', 'gstin'):
            if key in locked:
                continue                       # read-only: ignore whatever was submitted
            if key == 'gstin' and raw:
                raw = raw.upper().replace(' ', '')
                if not branding.GSTIN_RE.match(raw):
                    errors.append(f'"{raw}" doesn\'t look like a valid GSTIN (15 characters, e.g. 29ABCDE1234F1Z5).')
                    continue
            current = (AppSetting.get(app_key, '') or '').strip()
            if branding.lock_enabled() and raw and raw != current and not confirmed:
                needs_confirm.append('company name' if key == 'name' else 'GSTIN')
                continue
            AppSetting.set(app_key, raw)
            if raw:
                branding.relock(key)
        else:
            AppSetting.set(app_key, raw)
    if needs_confirm:
        errors.append(f'Tick "These details are correct" to save your {" and ".join(needs_confirm)}. '
                      'They can\'t be changed later without contacting support.')
    return errors


@admin_bp.route('/settings', methods=['GET', 'POST'])
def settings():
    tab = request.args.get('tab') or request.form.get('section') or 'company'
    tab = tab if tab in SETTINGS_TABS else 'company'

    if request.method == 'POST':
        errors = []
        if tab == 'company':
            errors = _save_company_fields()
        elif tab == 'appearance':
            if request.form.get('reset_theme'):
                for key in branding.THEME_KEYS:
                    AppSetting.set(branding.FIELDS[key][0], '')
            else:
                errors = _save_brand_fields(branding.THEME_KEYS)
            uploading = request.files.get('logo') and request.files['logo'].filename
            logo_locked = 'logo' in branding.locked_fields()
            if (uploading or request.form.get('remove_logo')) and logo_locked:
                errors.append('Your logo is locked. Contact support to change it.')
            elif request.form.get('remove_logo'):
                branding.remove_logo()
            elif uploading:
                if branding.lock_enabled() and not request.form.get('confirm_logo'):
                    errors.append('Tick "This is my company\'s logo" to upload it. It can\'t be changed later without contacting support.')
                else:
                    try:
                        png, version = branding.process_logo_upload(request.files['logo'].read())
                        branding.save_logo_png(png, version)
                        branding.relock('logo')
                    except branding.LogoError as exc:
                        errors.append(str(exc))
        elif tab == 'documents':
            # Multi-line fields — preserve newlines, allow blanking
            AppSetting.set('material_specs', request.form.get('material_specs', '').strip())
            AppSetting.set('terms_conditions', request.form.get('terms_conditions', '').strip())
        elif tab == 'email':
            _save_plain_settings(EMAIL_KEYS)

        db.session.commit()
        for err in errors:
            flash(err, 'danger')
        if not errors:
            flash('Theme reset to defaults.' if request.form.get('reset_theme') else 'Settings saved.', 'success')
        return redirect(url_for('admin.settings', tab=tab))

    saved_keys = ([branding.FIELDS[k][0] for k in branding.COMPANY_KEYS + branding.THEME_KEYS]
                  + EMAIL_KEYS + ['material_specs', 'terms_conditions'])
    saved = AppSetting.get_many(saved_keys)
    saved['terms_conditions'] = saved['terms_conditions'] or DEFAULT_TERMS
    defaults = {branding.FIELDS[k][0]: branding.env_default(k)
                for k in branding.COMPANY_KEYS + branding.THEME_KEYS}
    support_display, support_url = branding.support_contact()
    support_links = {key: branding.support_message_url(what, current_user, request.host_url)
                     for key, what in (('name', 'company name'), ('gstin', 'GSTIN'), ('logo', 'logo'))}
    return render_template('admin/settings.html', title='Settings', tab=tab, support_links=support_links,
                           saved=saved, defaults=defaults, options=branding.ui_options(),
                           locked=branding.locked_fields(), lock_enabled=branding.lock_enabled(),
                           support_display=support_display, support_url=support_url)


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
