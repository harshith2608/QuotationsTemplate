import json
from datetime import datetime, timedelta
from urllib.parse import quote
from flask import (Blueprint, render_template, redirect, url_for, flash,
                   request, abort, send_file, current_app)
from flask_login import login_required, current_user
from . import db
from .models import (Project, Room, Item, MasterRoom, MasterItem, WoodRate, WorkTypeRate, ItemRate,
                     ProjectEditLog, ProjectAccess, User, AppSetting, Payment,
                     PaymentLink, Notification, PriceListItem)
from .decorators import admin_required
from .catalog import WOOD_TYPES, WORK_TYPES, DEFAULT_WOOD, DEFAULT_WORK, STAGES, FIXED_ITEMS_LABEL
from .branding import get_brand

projects_bp = Blueprint('projects', __name__)

def _get_work_type_rates():
    return {r.work_type: r.rate_per_sqft for r in WorkTypeRate.query.all()}

def _get_price_list():
    """Fittings & accessories price list for the quotation form: [{name, price, unit}]."""
    return [{'name': p.name, 'price': p.price, 'unit': p.unit or ''}
            for p in PriceListItem.query.order_by(PriceListItem.name).all()]


def _get_item_rates():
    """Returns flat dict { 'wood_type|work_type': rate } for the JS form."""
    return {f'{r.wood_type}|{r.work_type}': r.rate_per_sqft for r in ItemRate.query.all()}


class EmailNotConfigured(Exception):
    pass


def _send_email(to_address, subject, body, raise_errors=False):
    """
    Send a plain-text email via the SMTP settings in Admin → Settings → Email.
    Returns True on success. With raise_errors=True (used by "Send test email"),
    failures raise instead of returning False so the admin sees the reason.
    Port 465 uses SSL; any other port (normally 587) uses STARTTLS.
    """
    import smtplib
    from email.mime.text import MIMEText
    from email.utils import formataddr
    smtp_host = AppSetting.get('smtp_host', '').strip()
    smtp_port = int(AppSetting.get('smtp_port', '587') or 587)
    smtp_user = AppSetting.get('smtp_user', '').strip()
    smtp_pass = AppSetting.get('smtp_pass', '').strip()
    from_addr = AppSetting.get('admin_email', '').strip() or smtp_user
    if not all([smtp_host, smtp_user, smtp_pass, to_address]):
        if raise_errors:
            raise EmailNotConfigured('Fill in SMTP host, username, password and admin email first.')
        return False
    try:
        msg = MIMEText(body, 'plain', 'utf-8')
        msg['Subject'] = subject
        msg['From']    = formataddr((get_brand()['name'], from_addr))
        msg['To']      = to_address
        if smtp_port == 465:
            with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=10) as s:
                s.login(smtp_user, smtp_pass)
                s.send_message(msg)
        else:
            with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as s:
                s.ehlo()
                s.starttls()
                s.login(smtp_user, smtp_pass)
                s.send_message(msg)
        return True
    except Exception as exc:
        if raise_errors:
            raise
        current_app.logger.warning(f'Email send failed: {exc}')
        return False


def _ensure_creator_access(project, creator_user):
    """Auto-grant ProjectAccess to the creator if they are an employee and don't already have it."""
    if creator_user.is_admin:
        return  # admins see everything, no entry needed
    existing = ProjectAccess.query.filter_by(
        project_id=project.id, user_id=creator_user.id
    ).first()
    if not existing:
        db.session.add(ProjectAccess(
            project_id=project.id,
            user_id=creator_user.id,
            granted_by=creator_user.id   # self-granted (creator)
        ))


def _get_wood_rates():
    return {r.wood_type: r.rate_per_sqft for r in WoodRate.query.all()}


def _save_project_data(project, rooms_data):
    """Delete existing rooms/items and save new ones. Returns grand_total."""
    # Remove existing rooms (cascade deletes items)
    for room in project.rooms.all():
        db.session.delete(room)
    db.session.flush()

    item_rates_flat = _get_item_rates()
    grand_total = 0.0

    for rd in rooms_data:
        room_name = rd.get('name', '').strip()
        if not room_name:
            continue
        room = Room(project_id=project.id, name=room_name)
        db.session.add(room)
        db.session.flush()

        # Auto-learn room name (case-insensitive dedup)
        if not MasterRoom.query.filter(MasterRoom.name.ilike(room_name)).first():
            db.session.add(MasterRoom(name=room_name))

        for id_ in rd.get('items', []):
            item_name = id_.get('name', '').strip()
            if not item_name:
                continue
            if id_.get('type') == 'fixed':
                # Fittings & accessories: quantity × unit price, no dimensions
                try:
                    quantity = float(id_.get('quantity', 1))
                    unit_price = float(id_.get('unit_price', 0))
                except (ValueError, TypeError):
                    continue
                if quantity <= 0 or unit_price < 0:
                    continue
                db.session.add(Item(room_id=room.id, name=item_name[:100], item_type='fixed',
                                    quantity=quantity, unit_price=unit_price,
                                    length=0, width=0, area=0, wood_type='', work_type=''))
                grand_total += quantity * unit_price
                continue
            try:
                length = float(id_.get('length', 0))
                width = float(id_.get('width', 0))
            except (ValueError, TypeError):
                continue
            if length <= 0 or width <= 0:
                continue
            area = round(length * width, 4)
            wood_type = id_.get('wood_type', DEFAULT_WOOD)
            if wood_type not in WOOD_TYPES:
                wood_type = DEFAULT_WOOD
            work_type = id_.get('work_type', DEFAULT_WORK)
            if work_type not in WORK_TYPES:
                work_type = DEFAULT_WORK

            item = Item(
                room_id=room.id,
                name=item_name,
                length=length,
                width=width,
                area=area,
                wood_type=wood_type,
                work_type=work_type
            )
            db.session.add(item)
            grand_total += area * item_rates_flat.get(f'{wood_type}|{work_type}', 0)

            # Auto-learn item name (case-insensitive dedup)
            if not MasterItem.query.filter(MasterItem.name.ilike(item_name)).first():
                db.session.add(MasterItem(name=item_name))

    return round(grand_total, 2)


@projects_bp.route('/projects')
@login_required
def list_projects():
    # Purge drafts older than 48 hours
    cutoff = datetime.utcnow() - timedelta(hours=48)
    old_drafts = Project.query.filter(
        Project.status == 'draft',
        Project.updated_at < cutoff
    ).all()
    for d in old_drafts:
        db.session.delete(d)
    if old_drafts:
        db.session.commit()

    page = request.args.get('page', 1, type=int)
    search = request.args.get('q', '').strip()
    stage = request.args.get('stage', '').strip()
    stage = stage if stage in STAGES else ''
    if current_user.is_admin:
        query = Project.query
    else:
        # Access is controlled entirely via ProjectAccess for employees
        # (creator is auto-added to ProjectAccess on save; admin can revoke it)
        accessible_ids = db.session.query(ProjectAccess.project_id).filter_by(user_id=current_user.id)
        query = Project.query.filter(Project.id.in_(accessible_ids))
    if search:
        query = query.filter(
            db.or_(
                Project.customer_name.ilike(f'%{search}%'),
                Project.mobile.ilike(f'%{search}%')
            )
        )
    # Stage counts for the filter pills (drafts are unfinished forms, so they have no real stage)
    stage_counts = dict(
        query.filter(Project.status != 'draft')
             .with_entities(Project.stage, db.func.count(Project.id))
             .group_by(Project.stage).all()
    )
    all_count = query.count()
    if stage:
        query = query.filter(Project.stage == stage, Project.status != 'draft')
    projects = query.order_by(Project.created_at.desc()).paginate(
        page=page, per_page=15, error_out=False
    )

    # Admin extras: employee list + per-project access map for the modal
    employees = []
    access_map = {}
    creator_map = {}   # project_id → creator user_id (so modal can lock the creator)
    if current_user.is_admin:
        employees = User.query.filter_by(role='employee').order_by(User.username).all()
        page_ids = [p.id for p in projects.items]
        rows = ProjectAccess.query.filter(ProjectAccess.project_id.in_(page_ids)).all()
        for row in rows:
            access_map.setdefault(row.project_id, []).append(row.user_id)
        # Build creator map so the modal knows who made each quotation
        for p in projects.items:
            creator_map[p.id] = p.created_by

    employees_json = [{'id': e.id, 'username': e.username} for e in employees]
    return render_template('projects/list.html', projects=projects, search=search,
                           stage=stage, stage_counts=stage_counts, all_count=all_count,
                           title='Quotations', employees=employees,
                           employees_json=employees_json,
                           access_map=access_map,
                           creator_map=creator_map)


@projects_bp.route('/projects/new', methods=['GET', 'POST'])
@login_required
def create_project():
    master_rooms = [r.name for r in MasterRoom.query.order_by(MasterRoom.name).all()]
    master_items = [i.name for i in MasterItem.query.order_by(MasterItem.name).all()]
    rates = _get_wood_rates()
    work_type_rates = _get_work_type_rates()
    item_rates = _get_item_rates()

    if request.method == 'POST':
        customer_name  = request.form.get('customer_name', '').strip()
        mobile         = request.form.get('mobile', '').strip()
        email          = request.form.get('email', '').strip()
        address        = request.form.get('address', '').strip()
        discount_type  = request.form.get('discount_type', 'none').strip()
        try:
            discount_value = float(request.form.get('discount_value', 0) or 0)
        except ValueError:
            discount_value = 0.0
        rooms_json        = request.form.get('rooms_data', '[]')
        plywood_thickness = ','.join(request.form.getlist('plywood_thickness'))

        errors = []
        if not customer_name:
            errors.append('Customer name is required.')
        if not mobile:
            errors.append('Mobile number is required.')
        if not mobile.lstrip('+').replace('-', '').replace(' ', '').isdigit() and mobile:
            errors.append('Mobile number must contain only digits.')

        try:
            rooms_data = json.loads(rooms_json)
        except (json.JSONDecodeError, ValueError):
            rooms_data = []
            errors.append('Form data is invalid. Please try again.')

        valid_rooms = [
            r for r in rooms_data
            if r.get('name', '').strip() and
            any(i.get('name', '').strip() for i in r.get('items', []))
        ]
        if not valid_rooms:
            errors.append('At least one room with one item is required.')

        if errors:
            for err in errors:
                flash(err, 'danger')
            return render_template('projects/form.html',
                                   title='New Quotation',
                                   master_rooms=master_rooms,
                                   master_items=master_items,
                                   rates=rates,
                                   work_type_rates=work_type_rates,
                                   item_rates=item_rates,
                                   price_list=_get_price_list(),
                                   form_data={'customer_name': customer_name,
                                              'mobile': mobile,
                                              'email': email,
                                              'address': address,
                                              'plywood_thickness': plywood_thickness},
                                   rooms_json=rooms_json,
                                   project=None)

        # If JS auto-saved a draft, promote it to complete instead of creating new
        draft_id = request.form.get('draft_id', '').strip()
        project = None
        if draft_id:
            project = Project.query.get(int(draft_id))
            if not project or project.created_by != current_user.id or project.status != 'draft':
                project = None

        if project:
            project.customer_name     = customer_name
            project.mobile            = mobile
            project.email             = email or None
            project.address           = address or None
            project.discount_type     = discount_type if discount_type in ('percentage', 'fixed') else 'none'
            project.discount_value    = discount_value
            project.plywood_thickness = plywood_thickness
        else:
            project = Project(
                customer_name=customer_name,
                mobile=mobile,
                email=email or None,
                address=address or None,
                created_by=current_user.id,
                grand_total=0.0,
                discount_type=discount_type if discount_type in ('percentage', 'fixed') else 'none',
                discount_value=discount_value,
                plywood_thickness=plywood_thickness,
            )
            db.session.add(project)
            db.session.flush()

        grand_total = _save_project_data(project, rooms_data)
        project.grand_total = grand_total
        project.status = 'complete'
        _ensure_creator_access(project, current_user)
        db.session.commit()

        flash('Quotation created successfully!', 'success')
        return redirect(url_for('projects.view_project', project_id=project.id))

    return render_template('projects/form.html',
                           title='New Quotation',
                           master_rooms=master_rooms,
                           master_items=master_items,
                           rates=rates,
                           work_type_rates=work_type_rates,
                           item_rates=item_rates,
                           price_list=_get_price_list(),
                           form_data={},
                           rooms_json='[]',
                           project=None)


@projects_bp.route('/projects/<int:project_id>')
@login_required
def view_project(project_id):
    project = Project.query.get_or_404(project_id)
    if not current_user.is_admin:
        if not ProjectAccess.query.filter_by(project_id=project_id, user_id=current_user.id).first():
            abort(403)
    # Drafts have no content to view — send to edit form to complete them
    if project.status == 'draft':
        flash('This quotation is still in progress. Complete and save it.', 'warning')
        return redirect(url_for('projects.edit_project', project_id=project.id))
    item_rates_flat = _get_item_rates()
    rooms = project.rooms_with_items()
    item_totals = project.get_item_totals(rooms)  # { 'wood|work': area } — measured items only
    fixed_total = project.fixed_items_total(rooms)
    item_summary = []
    for key in [f'{w}|{wk}' for w in WOOD_TYPES for wk in WORK_TYPES]:
        area = item_totals.get(key, 0.0)
        if area > 0:
            rate = item_rates_flat.get(key, 0.0)
            parts = key.split('|')
            item_summary.append({
                'label': f'{parts[0]} – {parts[1]}',
                'wood_type': parts[0], 'work_type': parts[1],
                'area': area, 'rate': rate, 'subtotal': round(area * rate, 2)
            })
    edit_logs = (ProjectEditLog.query
                 .filter_by(project_id=project.id)
                 .order_by(ProjectEditLog.edited_at.desc())
                 .all())
    payments = (Payment.query
                .filter_by(project_id=project.id)
                .order_by(Payment.recorded_at.desc())
                .all())
    total_paid = sum(p.amount for p in payments)
    balance    = max(project.final_total - total_paid, 0)
    settings   = AppSetting.get_many(['upi_id', 'bank_name', 'account_name',
                                      'account_number', 'ifsc_code', 'razorpay_key_id'])
    return render_template('projects/view.html',
                           project=project,
                           rooms=rooms,
                           item_summary=item_summary,
                           item_rates=item_rates_flat,
                           edit_logs=edit_logs,
                           payments=payments,
                           total_paid=total_paid,
                           balance=balance,
                           settings=settings,
                           stage_history=project.stage_changes.all(),
                           fixed_total=fixed_total,
                           can_change_stage=_can_change_stage(project),
                           title=f'Quotation – {project.customer_name}')


def _can_change_stage(project):
    """Admins, and employees who can see the quotation, may move it through the workflow."""
    if project.status == 'draft':
        return False
    if current_user.is_admin:
        return True
    return ProjectAccess.query.filter_by(project_id=project.id, user_id=current_user.id).first() is not None


def _safe_next(default):
    """Only allow redirects back to a path on this site."""
    nxt = request.form.get('next', '')
    return nxt if nxt.startswith('/') and not nxt.startswith('//') else default


@projects_bp.route('/projects/<int:project_id>/stage', methods=['POST'])
@login_required
def update_stage(project_id):
    project = Project.query.get_or_404(project_id)
    if not _can_change_stage(project):
        abort(403)
    new_stage = request.form.get('stage', '')
    if new_stage not in STAGES:
        flash('Unknown stage.', 'danger')
    elif project.set_stage(new_stage, current_user, request.form.get('note')):
        db.session.commit()
        flash(f'Quotation #{project.id} moved to "{STAGES[new_stage][0]}".', 'success')
    return redirect(_safe_next(url_for('projects.view_project', project_id=project.id)))


@projects_bp.route('/projects/<int:project_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_project(project_id):
    project = Project.query.get_or_404(project_id)
    if not current_user.is_admin and project.created_by != current_user.id:
        abort(403)

    master_rooms = [r.name for r in MasterRoom.query.order_by(MasterRoom.name).all()]
    master_items = [i.name for i in MasterItem.query.order_by(MasterItem.name).all()]
    rates = _get_wood_rates()
    work_type_rates = _get_work_type_rates()
    item_rates = _get_item_rates()

    if request.method == 'POST':
        customer_name  = request.form.get('customer_name', '').strip()
        mobile         = request.form.get('mobile', '').strip()
        email          = request.form.get('email', '').strip()
        address        = request.form.get('address', '').strip()
        discount_type  = request.form.get('discount_type', 'none').strip()
        try:
            discount_value = float(request.form.get('discount_value', 0) or 0)
        except ValueError:
            discount_value = 0.0
        rooms_json        = request.form.get('rooms_data', '[]')
        plywood_thickness = ','.join(request.form.getlist('plywood_thickness'))

        errors = []
        if not customer_name:
            errors.append('Customer name is required.')
        if not mobile:
            errors.append('Mobile number is required.')

        try:
            rooms_data = json.loads(rooms_json)
        except (json.JSONDecodeError, ValueError):
            rooms_data = []
            errors.append('Form data is invalid.')

        valid_rooms = [
            r for r in rooms_data
            if r.get('name', '').strip() and
            any(i.get('name', '').strip() for i in r.get('items', []))
        ]
        if not valid_rooms:
            errors.append('At least one room with one item is required.')

        if errors:
            for err in errors:
                flash(err, 'danger')
            # Build existing rooms JSON for re-render
            existing_json = _build_rooms_json(project)
            return render_template('projects/form.html',
                                   title='Edit Quotation',
                                   master_rooms=master_rooms,
                                   master_items=master_items,
                                   rates=rates,
                                   work_type_rates=work_type_rates,
                                   item_rates=item_rates,
                                   price_list=_get_price_list(),
                                   form_data={'customer_name': customer_name,
                                              'mobile': mobile, 'email': email,
                                              'plywood_thickness': plywood_thickness},
                                   rooms_json=rooms_json,
                                   project=project)

        was_draft = project.status == 'draft'
        project.customer_name     = customer_name
        project.mobile            = mobile
        project.email             = email or None
        project.address           = address or None
        project.discount_type     = discount_type if discount_type in ('percentage', 'fixed') else 'none'
        project.discount_value    = discount_value
        project.plywood_thickness = plywood_thickness
        grand_total = _save_project_data(project, rooms_data)
        project.grand_total = grand_total
        project.status = 'complete'
        if not was_draft:
            db.session.add(ProjectEditLog(project_id=project.id, edited_by=current_user.id))
        # Ensure the creator (if employee) has a ProjectAccess entry
        _ensure_creator_access(project, current_user)
        db.session.commit()

        flash('Quotation saved successfully!' if was_draft else 'Quotation updated successfully!', 'success')
        return redirect(url_for('projects.view_project', project_id=project.id))

    existing_json = _build_rooms_json(project)
    return render_template('projects/form.html',
                           title='Edit Quotation',
                           master_rooms=master_rooms,
                           master_items=master_items,
                           rates=rates,
                           work_type_rates=work_type_rates,
                           item_rates=item_rates,
                           price_list=_get_price_list(),
                           form_data={
                               'customer_name': project.customer_name,
                               'mobile': project.mobile,
                               'email': project.email or '',
                               'address': project.address or '',
                               'plywood_thickness': project.plywood_thickness or ''
                           },
                           rooms_json=existing_json,
                           project=project)


def _build_rooms_json(project):
    rooms_data = []
    for room in project.rooms_with_items():
        room_dict = {
            'name': room.name,
            'items': [
                {
                    'name': item.name,
                    'type': item.item_type,
                    'length': item.length,
                    'width': item.width,
                    'wood_type': item.wood_type,
                    'work_type': item.work_type,
                    'area': item.area,
                    'quantity': item.quantity,
                    'unit_price': item.unit_price,
                }
                for item in room.item_list
            ]
        }
        rooms_data.append(room_dict)
    return json.dumps(rooms_data)


@projects_bp.route('/projects/<int:project_id>/access', methods=['POST'])
@login_required
@admin_required
def set_project_access(project_id):
    project = Project.query.get_or_404(project_id)
    selected_ids = set(int(uid) for uid in request.form.getlist('user_ids'))

    # Replace all existing access entries for this project
    ProjectAccess.query.filter_by(project_id=project_id).delete()
    for uid in selected_ids:
        user = User.query.get(uid)
        if user and user.role == 'employee':
            db.session.add(ProjectAccess(
                project_id=project_id,
                user_id=uid,
                granted_by=current_user.id
            ))
    db.session.commit()
    count = len(selected_ids)
    flash(f'Access updated — {count} employee{"s" if count != 1 else ""} can now view this quotation.', 'success')
    return redirect(url_for('projects.list_projects'))


@projects_bp.route('/projects/<int:project_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_project(project_id):
    project = Project.query.get_or_404(project_id)
    db.session.delete(project)
    db.session.commit()
    flash(f'Quotation for {project.customer_name} deleted.', 'success')
    return redirect(url_for('projects.list_projects'))


@projects_bp.route('/projects/<int:project_id>/payments/add', methods=['POST'])
@login_required
@admin_required
def add_payment(project_id):
    project = Project.query.get_or_404(project_id)
    try:
        amount = float(request.form.get('amount', 0))
    except ValueError:
        amount = 0
    if amount <= 0:
        flash('Please enter a valid payment amount.', 'danger')
        return redirect(url_for('projects.view_project', project_id=project_id))
    note = request.form.get('note', '').strip()
    db.session.add(Payment(
        project_id=project_id,
        amount=amount,
        note=note or None,
        recorded_by=current_user.id
    ))
    db.session.commit()
    flash(f'Payment of ₹{amount:,.2f} recorded successfully.', 'success')
    return redirect(url_for('projects.view_project', project_id=project_id))


@projects_bp.route('/projects/<int:project_id>/payments/<int:payment_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_payment(project_id, payment_id):
    payment = Payment.query.get_or_404(payment_id)
    if payment.project_id != project_id:
        abort(404)
    db.session.delete(payment)
    db.session.commit()
    flash('Payment record removed.', 'success')
    return redirect(url_for('projects.view_project', project_id=project_id))


@projects_bp.route('/projects/<int:project_id>/payment-link', methods=['POST'])
@login_required
def generate_payment_link(project_id):
    from flask import jsonify
    import urllib.request, urllib.error
    import json as _json, base64

    project = Project.query.get_or_404(project_id)
    if not current_user.is_admin and project.created_by != current_user.id:
        if not ProjectAccess.query.filter_by(project_id=project_id, user_id=current_user.id).first():
            return jsonify({'error': 'Access denied.'}), 403

    api_key    = AppSetting.get('razorpay_key_id', '')
    api_secret = AppSetting.get('razorpay_key_secret', '')
    if not api_key or not api_secret:
        return jsonify({'error': 'Razorpay is not configured. Ask admin to add API keys in Payment Settings.'}), 400

    payments   = Payment.query.filter_by(project_id=project_id).all()
    total_paid = sum(p.amount for p in payments)
    remaining  = max(project.final_total - total_paid, 0)
    if remaining <= 0:
        return jsonify({'error': 'This quotation is fully paid — no outstanding balance.'}), 400

    mobile_clean = project.mobile.lstrip('+').replace(' ', '').replace('-', '')
    if not mobile_clean.startswith('91') and len(mobile_clean) == 10:
        mobile_clean = '91' + mobile_clean

    payload = _json.dumps({
        'amount': int(remaining * 100),
        'currency': 'INR',
        'accept_partial': True,
        'description': f"{get_brand()['name']} – Quotation #{project.id} for {project.customer_name}",
        'customer': {'name': project.customer_name, 'contact': '+' + mobile_clean,
                     'email': project.email or ''},
        'notify': {'sms': True, 'email': bool(project.email)},
        'reminder_enable': True,
        'notes': {'project_id': str(project.id)}
    }).encode()

    credentials = base64.b64encode(f'{api_key}:{api_secret}'.encode()).decode()
    req = urllib.request.Request(
        'https://api.razorpay.com/v1/payment_links',
        data=payload,
        headers={'Content-Type': 'application/json', 'Authorization': f'Basic {credentials}'},
        method='POST'
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = _json.loads(resp.read())
            link_id  = data.get('id')
            short_url = data.get('short_url')
            # Store link so webhook can resolve the project
            if link_id:
                existing = PaymentLink.query.filter_by(razorpay_link_id=link_id).first()
                if not existing:
                    db.session.add(PaymentLink(
                        project_id=project.id,
                        razorpay_link_id=link_id,
                        amount=remaining
                    ))
                    db.session.commit()
            return jsonify({'payment_link': short_url})
    except urllib.error.HTTPError as e:
        err_body = _json.loads(e.read())
        return jsonify({'error': err_body.get('error', {}).get('description', 'Razorpay error.')}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@projects_bp.route('/projects/<int:project_id>/pdf')
@login_required
def download_pdf(project_id):
    project = Project.query.get_or_404(project_id)
    if not current_user.is_admin and project.created_by != current_user.id:
        if not ProjectAccess.query.filter_by(project_id=project_id, user_id=current_user.id).first():
            abort(403)
    from .pdf_utils import generate_pdf
    pay_settings = AppSetting.get_many(['upi_id', 'bank_name', 'account_name', 'account_number', 'ifsc_code'])
    payments_list = Payment.query.filter_by(project_id=project_id).all()
    total_paid = sum(p.amount for p in payments_list)
    pdf_buffer = generate_pdf(project, payment_settings=pay_settings, total_paid=total_paid)
    filename = f"Quotation_{project.customer_name.replace(' ', '_')}_{project.id}.pdf"
    # ?download=1  → Content-Disposition: attachment  (force save to device)
    # default      → Content-Disposition: inline      (open in viewer / share sheet)
    as_attachment = request.args.get('download') == '1'
    return send_file(pdf_buffer, as_attachment=as_attachment,
                     download_name=filename, mimetype='application/pdf')


@projects_bp.route('/projects/<int:project_id>/pdf/customer')
@login_required
def download_customer_pdf(project_id):
    project = Project.query.get_or_404(project_id)
    if not current_user.is_admin and project.created_by != current_user.id:
        if not ProjectAccess.query.filter_by(project_id=project_id, user_id=current_user.id).first():
            abort(403)
    from .pdf_utils import generate_customer_pdf
    pay_settings = AppSetting.get_many(['upi_id', 'bank_name', 'account_name', 'account_number', 'ifsc_code'])
    payments_list = Payment.query.filter_by(project_id=project_id).all()
    total_paid = sum(p.amount for p in payments_list)
    pdf_buffer = generate_customer_pdf(project, payment_settings=pay_settings, total_paid=total_paid)
    filename = f"CustomerQuotation_{project.customer_name.replace(' ', '_')}_{project.id}.pdf"
    as_attachment = request.args.get('download') == '1'
    return send_file(pdf_buffer, as_attachment=as_attachment,
                     download_name=filename, mimetype='application/pdf')


@projects_bp.route('/projects/<int:project_id>/whatsapp')
@login_required
def whatsapp_share(project_id):
    from flask import redirect as flask_redirect
    project = Project.query.get_or_404(project_id)
    if not current_user.is_admin and project.created_by != current_user.id:
        if not ProjectAccess.query.filter_by(project_id=project_id, user_id=current_user.id).first():
            abort(403)

    item_rates = _get_item_rates()
    rooms = project.rooms_with_items()
    combo_totals = project.get_item_totals(rooms)    # measured items, by material & work
    fixed_total = project.fixed_items_total(rooms)

    # Payment info for WhatsApp
    pay_settings = AppSetting.get_many(['upi_id', 'bank_name', 'account_name', 'account_number', 'ifsc_code'])
    payments_list = Payment.query.filter_by(project_id=project_id).all()
    total_paid = sum(p.amount for p in payments_list)
    balance = max(project.final_total - total_paid, 0)

    lines = [
        f"Hello {project.customer_name}! 👋",
        f"",
        f"Thank you for considering *{get_brand()['name']}* for your home.",
        f"Here is your interior design quotation summary:",
        f"",
        f"📋 *Quotation #{project.id}*",
        f"📅 Date: {project.created_at.strftime('%d %b %Y')}",
    ]
    if project.address:
        lines.append(f"📍 Address: {project.address}")
    lines += ["", "*Room-wise Breakdown:*"]
    def _ft_in(d):
        feet = int(d); inch = round((d - feet) * 12)
        if inch == 12: feet += 1; inch = 0
        return f"{feet}ft" if inch == 0 else f"{feet}ft {inch}in"

    for room in rooms:
        lines.append(f"\n🏠 *{room.name}*")
        for item in room.item_list:
            if item.is_fixed:
                lines.append(f"  • {item.name}: {item.quantity:g} × Rs.{item.unit_price:,.0f}")
            else:
                lines.append(f"  • {item.name}: {_ft_in(item.length)} × {_ft_in(item.width)} = {item.area:.2f} sqft ({item.wood_type})")

    lines += ["", "*Material Summary:*"]
    for key, area in combo_totals.items():
        if area > 0:
            rate = item_rates.get(key, 0.0)
            wood, work = key.split('|')
            lines.append(f"  • {wood} – {work}: {area:.2f} sqft × Rs.{rate:,.0f} = Rs.{area * rate:,.0f}")
    if fixed_total > 0:
        lines.append(f"  • {FIXED_ITEMS_LABEL}: Rs.{fixed_total:,.0f}")

    lines.append("")
    if project.discount_amount > 0:
        lines.append(f"Subtotal: Rs.{project.grand_total:,.2f}")
        lines.append(f"Discount: - Rs.{project.discount_amount:,.2f}")
    lines.append(f"💰 *Grand Total: Rs.{project.final_total:,.2f}*")

    if total_paid > 0:
        lines.append(f"✅ Amount Paid: Rs.{total_paid:,.2f}")
        lines.append(f"⏳ Balance Due: Rs.{balance:,.2f}")

    # Payment instructions
    pay_lines = []
    if pay_settings.get('upi_id'):
        pay_lines.append(f"📱 UPI: *{pay_settings['upi_id']}*")
    if pay_settings.get('account_number'):
        pay_lines.append(
            f"🏦 Bank: {pay_settings.get('bank_name', '')} | "
            f"{pay_settings.get('account_name', '')} | "
            f"A/C: {pay_settings['account_number']} | "
            f"IFSC: {pay_settings.get('ifsc_code', '')}"
        )
    if pay_lines:
        lines += ["", "*Payment Details:*"] + pay_lines

    lines += [
        "",
        "_Please find the detailed PDF quotation attached._",
        "",
        f"Thank you for choosing {get_brand()['name']}! 🏡",
        "We look forward to transforming your space."
    ]

    from .demo import demo_enabled
    if demo_enabled():
        lines = ['*DEMO — NOT A VALID QUOTATION*', ''] + lines
    message = '\n'.join(lines)
    mobile = project.mobile.lstrip('+').replace(' ', '').replace('-', '')
    if not mobile.startswith('91') and len(mobile) == 10:
        mobile = '91' + mobile
    wa_url = f"https://wa.me/{mobile}?text={quote(message)}"
    return flask_redirect(wa_url)


@projects_bp.route('/webhook/razorpay', methods=['POST'])
def razorpay_webhook():
    """
    Razorpay sends a POST here whenever a payment link is paid.
    We verify the signature, auto-record the payment, create an in-app
    notification, and email both the customer and the admin.
    This endpoint is CSRF-exempt (Razorpay is the caller, not a browser).
    """
    import hmac as _hmac
    import hashlib as _hashlib
    import json as _json
    from flask import jsonify

    # ── 1. Read raw body for signature verification
    raw_body = request.get_data()
    signature = request.headers.get('X-Razorpay-Signature', '')
    webhook_secret = AppSetting.get('webhook_secret', '').strip()

    # Without a secret we can't tell Razorpay from a forger, so refuse rather than record fake payments
    if not webhook_secret:
        current_app.logger.warning('Razorpay webhook rejected: no webhook secret configured in Payment Settings')
        return jsonify({'error': 'Webhook secret not configured'}), 400
    expected = _hmac.new(webhook_secret.encode('utf-8'), raw_body, _hashlib.sha256).hexdigest()
    if not _hmac.compare_digest(expected, signature):
        current_app.logger.warning('Razorpay webhook: invalid signature')
        return jsonify({'error': 'Invalid signature'}), 400

    try:
        payload = _json.loads(raw_body)
    except Exception:
        return jsonify({'error': 'Bad JSON'}), 400

    event = payload.get('event', '')
    if event != 'payment_link.paid':
        # We only care about paid events; acknowledge others silently
        return jsonify({'status': 'ignored'}), 200

    # ── 2. Extract data from webhook payload
    pl_entity  = payload.get('payload', {}).get('payment_link', {}).get('entity', {})
    pay_entity = payload.get('payload', {}).get('payment', {}).get('entity', {})

    link_id        = pl_entity.get('id', '')
    notes          = pl_entity.get('notes') or {}
    razorpay_pay_id = pay_entity.get('id', '')
    amount_paise   = pay_entity.get('amount', 0)
    amount_rupees  = amount_paise / 100.0

    # ── 3. Find project — first via notes, fallback to PaymentLink table
    project = None
    proj_id_str = notes.get('project_id') if isinstance(notes, dict) else None
    if proj_id_str:
        try:
            project = Project.query.get(int(proj_id_str))
        except (ValueError, TypeError):
            pass
    if project is None and link_id:
        pl_record = PaymentLink.query.filter_by(razorpay_link_id=link_id).first()
        if pl_record:
            project = pl_record.project

    if project is None:
        current_app.logger.warning(f'Razorpay webhook: project not found for link {link_id}')
        return jsonify({'error': 'Project not found'}), 404

    # ── 4. Deduplicate — skip if this Razorpay payment ID was already recorded
    if razorpay_pay_id and Payment.query.filter_by(razorpay_payment_id=razorpay_pay_id).first():
        return jsonify({'status': 'duplicate'}), 200

    # ── 5. Auto-record payment (use first admin as recorded_by)
    admin_user = User.query.filter_by(role='admin').order_by(User.id).first()
    payment = Payment(
        project_id=project.id,
        amount=amount_rupees,
        note=f'Auto-recorded via Razorpay (Payment ID: {razorpay_pay_id})',
        recorded_by=admin_user.id if admin_user else None,
        source='razorpay',
        razorpay_payment_id=razorpay_pay_id or None
    )
    db.session.add(payment)

    # ── 6. Compute updated balance
    all_payments = Payment.query.filter_by(project_id=project.id).all()
    total_paid   = sum(p.amount for p in all_payments) + amount_rupees
    balance      = max(project.final_total - total_paid, 0)

    # ── 7. In-app notification for admin
    notif_msg = (
        f"₹{amount_rupees:,.2f} received from {project.customer_name} "
        f"(Quotation #{project.id}) via Razorpay.\n"
        f"Total Paid: ₹{total_paid:,.2f}  |  Balance: ₹{balance:,.2f}"
    )
    db.session.add(Notification(
        title=f'Payment received – {project.customer_name}',
        message=notif_msg,
        project_id=project.id
    ))
    db.session.commit()

    # ── 8. Email — customer
    if project.email:
        customer_body = (
            f"Dear {project.customer_name},\n\n"
            f"We have received your payment of ₹{amount_rupees:,.2f} for "
            f"Quotation #{project.id}.\n\n"
            f"Total Paid : ₹{total_paid:,.2f}\n"
            f"Balance Due: ₹{balance:,.2f}\n\n"
            f"{'Thank you — your account is fully settled!' if balance == 0 else 'Please clear the remaining balance at your earliest convenience.'}\n\n"
            f"Thank you for choosing {get_brand()['name']}!\n"
            f"We look forward to transforming your space."
        )
        _send_email(
            project.email,
            f"Payment Received – Quotation #{project.id} | {get_brand()['name']}",
            customer_body
        )

    # ── 9. Email — admin
    admin_email = AppSetting.get('admin_email', '').strip()
    if admin_email:
        admin_body = (
            f"New payment received via Razorpay:\n\n"
            f"Customer   : {project.customer_name}\n"
            f"Mobile     : {project.mobile}\n"
            f"Quotation  : #{project.id}\n"
            f"Amount Paid: ₹{amount_rupees:,.2f}\n"
            f"Total Paid : ₹{total_paid:,.2f}\n"
            f"Balance Due: ₹{balance:,.2f}\n"
            f"Razorpay ID: {razorpay_pay_id}\n\n"
            f"{'✅ Fully Paid' if balance == 0 else '⏳ Partial Payment'}"
        )
        _send_email(
            admin_email,
            f"[{get_brand()['name']}] Payment ₹{amount_rupees:,.2f} – {project.customer_name}",
            admin_body
        )

    current_app.logger.info(
        f'Razorpay webhook: recorded ₹{amount_rupees} for project {project.id}'
    )
    return jsonify({'status': 'ok'}), 200
