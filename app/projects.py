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
from .catalog import STAGES, FIXED_ITEMS_LABEL
from .branding import get_brand
from . import billing

projects_bp = Blueprint('projects', __name__)

def _get_work_type_rates():
    return {r.work_type: r.rate_per_sqft for r in WorkTypeRate.query.all()}

def _get_price_list():
    """Fittings & accessories price list for the quotation form: [{name, price, unit}]."""
    return [{'name': p.name, 'price': p.price, 'unit': p.unit or ''}
            for p in PriceListItem.query.order_by(PriceListItem.name).all()]


def _get_item_rates():
    """{price key: rate per sqft}, including plywood variants (see plywood.rate_map)."""
    from . import plywood
    return plywood.rate_map()


class EmailNotConfigured(Exception):
    pass


def _send_email(to_address, subject, body, raise_errors=False, attachments=None):
    """
    Send a plain-text email via the SMTP settings in Admin → Settings → Email.
    Returns True on success. With raise_errors=True (used by "Send test email"),
    failures raise instead of returning False so the admin sees the reason.
    Port 465 uses SSL; any other port (normally 587) uses STARTTLS.
    attachments: [(filename, bytes, mime subtype e.g. 'pdf')]
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
        if attachments:
            from email.mime.application import MIMEApplication
            from email.mime.multipart import MIMEMultipart
            msg = MIMEMultipart()
            msg.attach(MIMEText(body, 'plain', 'utf-8'))
            for filename, data, subtype in attachments:
                part = MIMEApplication(data, _subtype=subtype)
                part.add_header('Content-Disposition', 'attachment', filename=filename)
                msg.attach(part)
        else:
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


def _form_catalog(project):
    """Material options for the quotation form; keeps materials already used on `project` even if hidden since."""
    from . import materials as M
    from . import plywood
    used = set()
    if project is not None:
        for room in project.rooms_with_items():
            used |= {(i.wood_type, i.work_type) for i in room.item_list if not i.is_fixed}
    cat = M.form_catalog(used)
    if plywood.table_ready():
        plywood.ensure_options()
    ply = plywood.form_data()
    if request.method == 'POST' and request.form.get('plywood'):
        ply['selected'] = plywood.clean_choice(request.form.get('plywood'))
    else:
        ply['selected'] = plywood.project_plywood(project) if project is not None else None
    ply['selected'] = ply['selected'] or ply['default']
    ply['enabled'] = plywood.table_ready() and bool(ply['options'])
    cat['plywood_form'] = ply
    from . import layout
    cat['room_descriptions'] = layout.description_options()
    return cat


def _set_project_plywood(project, form):
    """The quotation's plywood from the form (Admin → Rates → Plywood). The old free list is cleared once a
    quotation has a priced plywood, so the PDF shows one, not both."""
    from . import plywood
    if not plywood.table_ready() or not plywood.enabled() or 'plywood' not in form:
        return
    chosen = plywood.clean_choice(form.get('plywood')) or plywood.default_name()
    existing = project.status == 'complete' and project.id is not None
    if existing and project.plywood is None and chosen == plywood.default_name():
        return          # a quotation from before plywood pricing, left on the default: nothing changes
    project.plywood = chosen
    project.plywood_thickness = ''


def _save_project_data(project, rooms_data):
    """Delete existing rooms/items and save new ones. Returns grand_total."""
    # Remove existing rooms (cascade deletes items)
    for room in project.rooms.all():
        db.session.delete(room)
    db.session.flush()

    item_rates_flat = _get_item_rates()
    grand_total = 0.0
    from . import materials as M
    from . import plywood
    from . import layout
    ply_ready = plywood.table_ready()
    desc_ready = layout.description_ready()
    project_ply = plywood.project_plywood(project)
    valid_combos = {(w, k) for w, k, _ in M.combos(include_hidden=True)}
    fallback_combo = M.default_combo()

    for rd in rooms_data:
        room_name = rd.get('name', '').strip()
        if not room_name:
            continue
        room = Room(project_id=project.id, name=room_name)
        if desc_ready:                         # only once the database has the column
            # one or more of the admin's descriptions, one per line
            lines = [' '.join(l.split()) for l in str(rd.get('description') or '').splitlines()]
            room.description = '\n'.join(dict.fromkeys(l for l in lines if l))[:2000] or None
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
            try:
                count = min(max(int(float(id_.get('count') or 1)), 1), 999)   # "No's": identical pieces
            except (ValueError, TypeError):
                count = 1
            area = round(length * width * count, 4)
            wood_type = str(id_.get('wood_type') or '')
            work_type = str(id_.get('work_type') or '')       # '' = a material with one rate (e.g. Glass)
            if (wood_type, work_type) not in valid_combos:
                wood_type, work_type = fallback_combo

            item = Item(
                room_id=room.id,
                name=item_name,
                length=length,
                width=width,
                area=area,
                wood_type=wood_type,
                work_type=work_type,
                quantity=count if count > 1 else None
            )
            item_ply = None
            if ply_ready:                      # only once the database has the column
                item_ply = plywood.clean_choice(id_.get('plywood'))
                if wood_type not in plywood.context()['materials'] or item_ply == project_ply:
                    item_ply = None            # same as the quotation's: follow it
                item.plywood = item_ply
            db.session.add(item)
            grand_total += area * item_rates_flat.get(
                plywood.key_for(wood_type, work_type, item_ply or project_ply), 0)

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
        # Names and mobiles are encrypted, so match them in Python after decrypting
        needle = search.lower()
        rows = query.with_entities(Project.id, Project.customer_name, Project.mobile).all()
        ids = [r.id for r in rows if needle in (r.customer_name or '').lower() or needle in (r.mobile or '')]
        query = query.filter(Project.id.in_(ids))
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
        from . import access as _access
        q = ProjectAccess.query.filter(ProjectAccess.project_id.in_(page_ids))
        if _access.edit_ready():
            from sqlalchemy.orm import undefer
            q = q.options(undefer(ProjectAccess.can_edit))
        for row in q.all():                 # {project: {user: 'view' | 'edit'}}
            access_map.setdefault(row.project_id, {})[row.user_id] = \
                'edit' if _access.edit_ready() and row.can_edit else 'view'
        # Build creator map so the modal knows who made each quotation
        for p in projects.items:
            creator_map[p.id] = p.created_by

    employees_json = [{'id': e.id, 'username': e.username} for e in employees]
    from . import access as _access
    editable_ids = _access.edit_ids(current_user, [p.id for p in projects.items])
    return render_template('projects/list.html', projects=projects, search=search,
                           stage=stage, stage_counts=stage_counts, all_count=all_count,
                           title='Quotations', employees=employees,
                           employees_json=employees_json,
                           access_map=access_map,
                           creator_map=creator_map, editable_ids=editable_ids,
                           edit_access_ready=_access.edit_ready())


@projects_bp.route('/projects/new', methods=['GET', 'POST'])
@login_required
def create_project():
    master_rooms = [r.name for r in MasterRoom.query.order_by(MasterRoom.name).all()]
    master_items = [i.name for i in MasterItem.query.order_by(MasterItem.name).all()]
    rates = _get_wood_rates()
    work_type_rates = _get_work_type_rates()
    item_rates = _get_item_rates()
    form_cat = _form_catalog(None)

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
                                   work_type_rates=work_type_rates, **form_cat,
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

        _set_project_plywood(project, request.form)
        grand_total = _save_project_data(project, rooms_data)
        project.grand_total = grand_total
        project.status = 'complete'
        _ensure_creator_access(project, current_user)
        db.session.commit()
        billing.record_revision(project, current_user)       # R1
        db.session.commit()

        flash('Quotation created successfully!', 'success')
        return redirect(url_for('projects.view_project', project_id=project.id))

    return render_template('projects/form.html',
                           title='New Quotation',
                           master_rooms=master_rooms,
                           master_items=master_items,
                           rates=rates,
                           work_type_rates=work_type_rates, **form_cat,
                           item_rates=item_rates,
                           price_list=_get_price_list(),
                           form_data={},
                           rooms_json='[]',
                           project=None)


@projects_bp.route('/projects/<int:project_id>')
@login_required
def view_project(project_id):
    from . import plywood as _ply
    project = _ply.load_project(project_id)
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
    from . import materials as M
    from . import plywood
    project_ply = plywood.project_plywood(project)
    item_summary = []
    for key in M.ordered_keys(item_totals):
        area = item_totals.get(key, 0.0)
        if area > 0:
            rate = item_rates_flat.get(key, 0.0)
            wood, work, _ply = plywood.split_key(key)
            item_summary.append({
                'label': plywood.label(key, project),
                'wood_type': wood, 'work_type': work,
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
    all_invoices = billing.invoices(project)
    invoice    = next((i for i in all_invoices if i.status == 'issued'), None)
    amount_due = billing.amount_due_total(project, invoice) if invoice else project.final_total
    balance    = max(amount_due - total_paid, 0)
    settings   = AppSetting.get_many(['upi_id', 'bank_name', 'account_name',
                                      'account_number', 'ifsc_code', 'razorpay_key_id', 'smtp_host', 'smtp_user',
                                      'smtp_pass'] + list(billing.INVOICE_KEYS))
    from .share import share_status
    history = billing.revision_history(project)
    q2c = {
        'ready': billing.ready(),
        'invoice': invoice,
        'invoices': all_invoices,
        'invoice_settings': billing.invoice_settings(settings),
        'business_state': billing.business_state_code(),
        'states': billing.STATES,
        'gst_rates': billing.GST_RATES,
        'history': history,
        'share': share_status(project, history[0][0].number if history else None),
        'last_reminder': billing.last_reminder(project) if balance > 0 else None,
        'profit': billing.profit(project, rooms, invoice=invoice, settings=billing.invoice_settings(settings))
                  if current_user.is_admin else None,
        'wa_number': billing.whatsapp_number(project.mobile),
        'email_ready': billing.email_ready(settings),
    }
    from .share import invoice_url
    invoice_links = {i.id: invoice_url(i) for i in all_invoices if i.status == 'issued'}
    latest_rev = q2c['history'][0][0] if q2c['history'] else None
    q2c['changed_after_invoice'] = bool(invoice and latest_rev and latest_rev.created_at > invoice.created_at)
    return render_template('projects/view.html',
                           project=project,
                           rooms=rooms,
                           item_summary=item_summary,
                           item_rates=item_rates_flat,
                           project_ply=project_ply,
                           ply_materials=plywood.context()['materials'],
                           plywood_enabled=plywood.enabled(),
                           edit_logs=edit_logs,
                           payments=payments,
                           total_paid=total_paid,
                           balance=balance,
                           amount_due=amount_due,
                           q2c=q2c,
                           invoice_links=invoice_links,
                           settings=settings,
                           stage_history=project.stage_changes.all(),
                           fixed_total=fixed_total,
                           can_change_stage=_can_change_stage(project),
                           can_edit=__import__('app.access', fromlist=['can_edit']).can_edit(project, current_user),
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
    from . import plywood as _ply
    project = _ply.load_project(project_id)
    from . import access
    if not access.can_edit(project, current_user):     # admin, its creator, or staff given "Can edit"
        abort(403)

    master_rooms = [r.name for r in MasterRoom.query.order_by(MasterRoom.name).all()]
    master_items = [i.name for i in MasterItem.query.order_by(MasterItem.name).all()]
    rates = _get_wood_rates()
    work_type_rates = _get_work_type_rates()
    item_rates = _get_item_rates()
    form_cat = _form_catalog(project)

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
                                   work_type_rates=work_type_rates, **form_cat,
                                   item_rates=item_rates,
                                   price_list=_get_price_list(),
                                   form_data={'customer_name': customer_name,
                                              'mobile': mobile, 'email': email,
                                              'plywood_thickness': plywood_thickness},
                                   rooms_json=rooms_json,
                                   project=project)

        was_draft = project.status == 'draft'
        billing.ensure_first_revision(project, current_user)   # older quotations: keep how it was as R1
        project.customer_name     = customer_name
        project.mobile            = mobile
        project.email             = email or None
        project.address           = address or None
        project.discount_type     = discount_type if discount_type in ('percentage', 'fixed') else 'none'
        project.discount_value    = discount_value
        project.plywood_thickness = plywood_thickness
        _set_project_plywood(project, request.form)
        grand_total = _save_project_data(project, rooms_data)
        project.grand_total = grand_total
        project.status = 'complete'
        if not was_draft:
            db.session.add(ProjectEditLog(project_id=project.id, edited_by=current_user.id))
        # Ensure the creator (if employee) has a ProjectAccess entry
        _ensure_creator_access(project, current_user)
        db.session.commit()
        rev = billing.record_revision(project, current_user)
        db.session.commit()
        if rev and rev.number > 1 and not was_draft:
            flash(f'Saved as revision {rev.number}.', 'info')

        flash('Quotation saved successfully!' if was_draft else 'Quotation updated successfully!', 'success')
        return redirect(url_for('projects.view_project', project_id=project.id))

    existing_json = _build_rooms_json(project)
    return render_template('projects/form.html',
                           title='Edit Quotation',
                           master_rooms=master_rooms,
                           master_items=master_items,
                           rates=rates,
                           work_type_rates=work_type_rates, **form_cat,
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
    from . import plywood
    from . import layout
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
                    'plywood': plywood.item_plywood(item),
                    'count': item.count,
                }
                for item in room.item_list
            ],
            'description': layout.room_description(room),
        }
        rooms_data.append(room_dict)
    return json.dumps(rooms_data)


@projects_bp.route('/projects/<int:project_id>/access', methods=['POST'])
@login_required
@admin_required
def set_project_access(project_id):
    project = Project.query.get_or_404(project_id)
    from . import access
    # access_<user id> = '' (no access) | 'view' | 'edit'. Older pop-ups send user_ids (view).
    levels = {}
    for key, value in request.form.items():
        if key.startswith('access_') and key[7:].isdigit() and value in ('view', 'edit'):
            levels[int(key[7:])] = value
    for uid in request.form.getlist('user_ids'):
        if uid.isdigit():
            levels.setdefault(int(uid), 'view')
    if not access.edit_ready():
        levels = {u: 'view' for u in levels}           # edit access arrives with the database update

    # Replace all existing access entries for this project
    ProjectAccess.query.filter_by(project_id=project_id).delete()
    viewers = editors = 0
    for uid, level in levels.items():
        user = db.session.get(User, uid)
        if user and user.role == 'employee':
            grant = ProjectAccess(project_id=project_id, user_id=uid, granted_by=current_user.id)
            if access.edit_ready():
                grant.can_edit = level == 'edit'
            db.session.add(grant)
            editors += level == 'edit'
            viewers += level == 'view'
    db.session.commit()
    parts = [f'{n} can {what}' for n, what in ((editors, 'edit'), (viewers, 'view')) if n]
    flash('Access updated: ' + (', '.join(parts) if parts else 'only admins') + '. Deleting stays admin-only.', 'success')
    return redirect(url_for('projects.list_projects'))


@projects_bp.route('/projects/<int:project_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_project(project_id):
    project = Project.query.get_or_404(project_id)
    if billing.invoices(project):
        flash('This quotation has invoices, so it can\'t be deleted (invoices must be kept for your records).', 'danger')
        return redirect(url_for('projects.view_project', project_id=project.id))
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

    project = Project.query.get_or_404(project_id)
    if not current_user.is_admin and project.created_by != current_user.id:
        if not ProjectAccess.query.filter_by(project_id=project_id, user_id=current_user.id).first():
            return jsonify({'error': 'Access denied.'}), 403

    api_key    = AppSetting.get('razorpay_key_id', '')
    api_secret = AppSetting.get('razorpay_key_secret', '')
    if not api_key or not api_secret:
        return jsonify({'error': 'Razorpay is not configured. Ask admin to add API keys in Payment Settings.'}), 400

    remaining  = billing.balance(project)
    if remaining <= 0:
        return jsonify({'error': 'This quotation is fully paid — no outstanding balance.'}), 400
    # Amount to collect: the whole balance by default, or a part (advance, stage payment)
    requested = (request.get_json(silent=True) or {}).get('amount')
    if requested in (None, ''):
        amount = remaining
    else:
        try:
            amount = round(float(requested), 2)
        except (TypeError, ValueError):
            return jsonify({'error': 'Enter the amount to collect, e.g. 50000.'}), 400
        if amount < 1:
            return jsonify({'error': 'The amount must be at least ₹1.'}), 400
        if amount > remaining:
            return jsonify({'error': f'That is more than the balance due (₹{remaining:,.2f}).'}), 400

    try:
        short_url = create_razorpay_link(project, amount, remaining)
    except RazorpayLinkError as exc:
        return jsonify({'error': str(exc)}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    return jsonify({'payment_link': short_url, 'amount': amount})


class RazorpayLinkError(Exception):
    pass


def create_razorpay_link(project, amount, remaining):
    """Create a Razorpay payment link for `amount` and remember it for the webhook. Returns the short URL."""
    import urllib.request, urllib.error
    import json as _json, base64
    api_key    = AppSetting.get('razorpay_key_id', '')
    api_secret = AppSetting.get('razorpay_key_secret', '')
    if not api_key or not api_secret:
        raise RazorpayLinkError('Razorpay is not configured. Ask admin to add API keys in Payment Settings.')
    inv = billing.active_invoice(project)
    mobile_clean = project.mobile.lstrip('+').replace(' ', '').replace('-', '')
    if not mobile_clean.startswith('91') and len(mobile_clean) == 10:
        mobile_clean = '91' + mobile_clean

    payload = _json.dumps({
        'amount': int(round(amount * 100)),
        'currency': 'INR',
        'accept_partial': True,
        'description': f"{get_brand()['name']} – " + (f'Invoice {inv.number}' if inv else f'Quotation #{project.id}')
                       + f" for {project.customer_name}" + ('' if amount == remaining else ' (part payment)'),
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
    except urllib.error.HTTPError as e:
        try:
            message = _json.loads(e.read()).get('error', {}).get('description') or 'Razorpay error.'
        except ValueError:
            message = f'Razorpay error (HTTP {e.code}).'
        if 'maximum amount' in message.lower():
            message = (f'Razorpay won\'t accept ₹{amount:,.0f} in one payment: it is above your Razorpay account\'s '
                       'per-payment limit. Request a smaller amount (e.g. the advance), or ask Razorpay support '
                       'to raise your maximum transaction amount.')
        raise RazorpayLinkError(message)
    link_id = data.get('id')
    # Store link so webhook can resolve the project
    if link_id and not PaymentLink.query.filter_by(razorpay_link_id=link_id).first():
        db.session.add(PaymentLink(project_id=project.id, razorpay_link_id=link_id, amount=amount))
        db.session.commit()
    return data.get('short_url')


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
    from . import plywood as _ply
    project = _ply.load_project(project_id)
    if not current_user.is_admin and project.created_by != current_user.id:
        if not ProjectAccess.query.filter_by(project_id=project_id, user_id=current_user.id).first():
            abort(403)

    from . import plywood
    item_rates = _get_item_rates()
    rooms = project.rooms_with_items()
    combo_totals = project.get_item_totals(rooms)    # measured items, by material & work (& plywood)
    project_ply = plywood.project_plywood(project)
    fixed_total = project.fixed_items_total(rooms)

    # Payment info for WhatsApp
    pay_settings = AppSetting.get_many(['upi_id', 'bank_name', 'account_name', 'account_number', 'ifsc_code'])
    payments_list = Payment.query.filter_by(project_id=project_id).all()
    total_paid = sum(p.amount for p in payments_list)
    balance = billing.balance(project)
    from .share import active_share_url
    approval_url = active_share_url(project)

    lines = [
        f"Hello {project.customer_name}! 👋",
        f"",
        f"Thank you for considering *{get_brand()['name']}* for your home.",
        f"Here is your interior design quotation summary:",
        f"",
        f"📋 *Quotation #{project.id}*",
        f"📅 Date: {(project.created_at + timedelta(hours=5, minutes=30)).strftime('%d %b %Y')}",
    ]
    if project.address:
        lines.append(f"📍 Address: {project.address}")
    if project_ply and plywood.enabled():
        lines.append(f"🪵 Plywood: {project_ply}")
    lines += ["", "*Room-wise Breakdown:*"]
    from . import units
    _ft_in = units.length

    for room in rooms:
        lines.append(f"\n🏠 *{room.name}*")
        for item in room.item_list:
            if item.is_fixed:
                lines.append(f"  • {item.name}: {item.quantity:g} × Rs.{item.unit_price:,.0f}")
            else:
                own_ply = plywood.item_plywood(item)
                ply_note = f", {own_ply}" if own_ply and item.wood_type in plywood.context()['materials'] else ''
                count_note = f" × {item.count}" if item.count > 1 else ''
                lines.append(f"  • {item.name}: {_ft_in(item.length)} × {_ft_in(item.width)}{count_note} = {units.area(item.area)} ({item.wood_type}{ply_note})")

    lines += ["", "*Material Summary:*"]
    from . import materials as M
    for key in M.ordered_keys(combo_totals):
        area = combo_totals[key]
        if area > 0:
            rate = item_rates.get(key, 0.0)
            lines.append(f"  • {plywood.label(key, project)}: {units.area(area)} × Rs.{units.rate_value(rate):,.0f}{units.rate_label()} = Rs.{area * rate:,.0f}")
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

    if approval_url:
        lines += ["", "👉 *View and accept your quotation online:*", approval_url]
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

    # ── 5. Auto-record payment (use first admin as recorded_by). Totals are taken before it's added: once added, the
    # query below would already include it (autoflush) and count it twice.
    total_paid = sum(p.amount for p in Payment.query.filter_by(project_id=project.id).all()) + amount_rupees
    balance    = max(billing.amount_due_total(project) - total_paid, 0)
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

    # ── 6. In-app notification for admin
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

    # ── 7. Email — customer
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

    # ── 8. Email — admin
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
