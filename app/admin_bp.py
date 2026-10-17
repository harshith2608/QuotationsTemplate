import re
from datetime import date
from flask import Blueprint, render_template, redirect, url_for, flash, request, abort
from flask_login import login_required, current_user
from werkzeug.security import generate_password_hash
from types import SimpleNamespace
from sqlalchemy import func
from sqlalchemy.orm import load_only
from . import db
from .models import User, Project, Item, Room, WoodRate, WorkTypeRate, ItemRate, MasterRoom, MasterItem, AppSetting, Notification, PriceListItem, Material
from .forms import CreateUserForm, ChangePasswordForm
from .decorators import admin_required
from .pdf_utils import DEFAULT_TERMS
from .catalog import WORK_TYPES, STAGES
from . import branding

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')


@admin_bp.before_request
@login_required
def require_admin():
    if not current_user.is_admin:
        abort(403)


@admin_bp.route('/dashboard')
def dashboard():
    # Amounts and mobiles are encrypted, so totals are added up here rather than in SQL
    projects = Project.query.options(load_only(
        Project.id, Project.created_by, Project.stage, Project.status, Project.mobile,
        Project.grand_total, Project.discount_type, Project.discount_value)).all()

    # Employee performance stats
    per_user = {}
    for p in projects:
        count, value = per_user.get(p.created_by, (0, 0.0))
        per_user[p.created_by] = (count + 1, value + p.final_total)
    employee_stats = [
        SimpleNamespace(id=u.id, username=u.username, project_count=per_user.get(u.id, (0, 0))[0],
                        total_value=round(per_user.get(u.id, (0, 0.0))[1], 2))
        for u in User.query.filter_by(role='employee').order_by(User.id).all()
    ]

    # Wood type distribution (total area per wood type)
    wood_dist = (
        db.session.query(Item.wood_type, func.sum(Item.area).label('total_area'))
        .filter(Item.item_type == 'measured')          # fittings have no material/area
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
    total_projects = len(projects)
    total_value = round(sum(p.final_total for p in projects), 2)
    total_customers = len({p.mobile for p in projects})
    total_employees = User.query.filter_by(role='employee').count()

    # Pipeline: count and value per workflow stage (excluding unfinished drafts)
    by_stage = {}
    for p in projects:
        if p.status != 'draft':
            count, value = by_stage.get(p.stage, (0, 0.0))
            by_stage[p.stage] = (count + 1, round(value + p.final_total, 2))
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


def _save_price_list():
    """Apply edits, additions and deletions from the price-list form. Returns error messages."""
    errors = []
    ids, names = request.form.getlist('pl_id'), request.form.getlist('pl_name')
    prices, units = request.form.getlist('pl_price'), request.form.getlist('pl_unit')
    delete_ids = {d for d in request.form.getlist('pl_delete') if d}
    existing = {str(p.id): p for p in PriceListItem.query.all()}
    seen = set()
    for item_id, name, price, unit in zip(ids, names, prices, units):
        name, unit = name.strip()[:100], unit.strip()[:30]
        if item_id in delete_ids:
            if item_id in existing:
                db.session.delete(existing[item_id])
            continue
        if not name:
            continue                       # blank "add" rows are simply ignored
        if name.lower() in seen:
            errors.append(f'"{name}" appears twice in the price list.')
            continue
        try:
            price_val = max(0.0, float(price or 0))
        except ValueError:
            errors.append(f'Price for "{name}" must be a number.')
            continue
        seen.add(name.lower())
        row = existing.get(item_id)
        if row:
            row.name, row.price, row.unit = name, price_val, unit or None
        else:
            clash = PriceListItem.query.filter(func.lower(PriceListItem.name) == name.lower()).first()
            if clash and str(clash.id) not in ids:
                errors.append(f'"{name}" is already in the price list.')
                continue
            db.session.add(PriceListItem(name=name, price=price_val, unit=unit or None))
    return errors


@admin_bp.route('/rates', methods=['GET', 'POST'])
def rates():
    from . import materials as M
    if not M.table_ready():
        # Right after an update is deployed, before "Update all" has run: price list only, for a few minutes
        if request.method == 'POST' and 'price_list_submit' not in request.form:
            flash('Materials can be edited again in a few minutes (a database update is pending).', 'warning')
            return redirect(url_for('admin.rates'))
        if request.method == 'GET':
            flash('A database update is pending: material rates can\'t be edited for a few minutes.', 'warning')
            return render_template('admin/rates.html', title='Manage Rates', materials=[],
                                   price_list=PriceListItem.query.order_by(PriceListItem.name).all(),
                                   work_types=WORK_TYPES)

    if request.method == 'POST' and 'price_list_submit' in request.form:
        errors = _save_price_list()
        db.session.commit()
        for err in errors:
            flash(err, 'danger')
        if not errors:
            flash('Price list updated.', 'success')
        return redirect(url_for('admin.rates') + '#price-list')

    from . import plywood
    if plywood.table_ready():
        plywood.ensure_options()
    if request.method == 'POST' and 'plywood_submit' in request.form:
        if not plywood.table_ready():
            flash('Plywood can be set up after the database update (Updates).', 'warning')
            return redirect(url_for('admin.rates'))
        errors = _save_plywood()
        if errors:
            db.session.rollback()
            for err in errors:
                flash(err, 'danger')
        else:
            db.session.commit()
            flash('Plywood updated. New and edited quotations use these prices.', 'success')
        return redirect(url_for('admin.rates') + '#plywood')

    if request.method == 'POST' and 'material_add' in request.form:
        try:
            name = M.clean_name(request.form.get('mat_name'))
        except ValueError as exc:
            flash(str(exc), 'danger')
            return redirect(url_for('admin.rates') + '#materials')
        if Material.query.filter(db.func.lower(Material.name) == name.lower()).first():
            flash(f'"{name}" already exists.', 'danger')
            return redirect(url_for('admin.rates') + '#materials')
        uses_work = bool(request.form.get('mat_uses_work'))
        rate = _rate(request.form.get('mat_rate'))
        top = db.session.query(db.func.max(Material.sort_order)).scalar() or 0
        mat = Material(name=name, uses_work_types=uses_work, active=True, sort_order=top + 1)
        if plywood.table_ready():
            mat.uses_plywood = bool(request.form.get('mat_uses_plywood'))
        db.session.add(mat)
        for work in (WORK_TYPES if uses_work else ['']):
            existing = ItemRate.query.filter_by(wood_type=name, work_type=work).first()
            if existing:
                existing.rate_per_sqft = rate
            else:
                db.session.add(ItemRate(wood_type=name, work_type=work, rate_per_sqft=rate))
        db.session.commit()
        flash(f'Added "{name}". It now appears in the material list on quotations.', 'success')
        return redirect(url_for('admin.rates') + '#materials')

    if request.method == 'POST' and 'item_rates_submit' in request.form:
        errors = _save_materials_and_rates()
        action = request.form.get('item_rates_submit', '')
        if not errors and ':' in action:
            errors += _material_action(*action.split(':', 1))
        if errors:
            db.session.rollback()
            for err in errors:
                flash(err, 'danger')
        else:
            db.session.commit()
            if ':' not in action:
                flash('Materials and rates updated.', 'success')
        return redirect(url_for('admin.rates') + '#materials')

    rate_map = {(r.wood_type, r.work_type): r.rate_per_sqft for r in ItemRate.query.all()}
    rows = []
    ply_ready = plywood.table_ready()
    q = Material.query.order_by(Material.sort_order, Material.id)
    if ply_ready:
        from sqlalchemy.orm import undefer
        q = q.options(undefer(Material.uses_plywood))
    for m in q.all():
        works = WORK_TYPES if m.uses_work_types else ['']
        rows.append({'m': m, 'in_use': M.in_use(m.name), 'on_plywood': ply_ready and m.uses_plywood,
                     'rates': [(i, w, rate_map.get((m.name, w), 0.0)) for i, w in enumerate(works)]})
    ply_rows = []
    if ply_ready:
        from .models import PlywoodOption
        for o in plywood.context()['options']:
            ply_rows.append(dict(o, in_use=plywood.in_use(o['name'])))
    return render_template('admin/rates.html', title='Manage Rates', materials=rows,
                           price_list=PriceListItem.query.order_by(PriceListItem.name).all(),
                           work_types=WORK_TYPES, ply_ready=ply_ready, plywood_rows=ply_rows)


def _plywood_ready():
    from . import plywood
    return plywood.table_ready()


def _adjustment(raw):
    """'+100', '-200', '' → float (₹/sqft, may be negative), or None if not a number."""
    raw = str(raw if raw is not None else '').strip().replace(',', '').replace('₹', '').replace(' ', '')
    if raw in ('', '+', '-'):
        return 0.0
    try:
        return round(float(raw), 2)
    except ValueError:
        return None


def _save_plywood():
    """Names, adjustments, default, show/hide, delete and a new one, from the Plywood card. Returns errors.
    The default is always ₹0: choosing another default re-bases every adjustment on it, so the same plywood keeps
    the same price difference to the others."""
    from . import plywood
    from .models import PlywoodOption
    errors = []
    rows = PlywoodOption.query.order_by(PlywoodOption.sort_order, PlywoodOption.id).all()
    by_id = {str(r.id): r for r in rows}
    deleting = set(request.form.getlist('ply_delete'))
    for r in rows:
        sid = str(r.id)
        name = ' '.join((request.form.get(f'ply_name_{sid}', r.name) or '').split())[:plywood.NAME_MAX]
        if len(name) < 2:
            errors.append('Give every plywood a name (at least 2 characters).')
            continue
        if '|' in name:
            errors.append('A plywood name can\'t contain "|".')
            continue
        adj = _adjustment(request.form.get(f'ply_adj_{sid}', r.adjustment))
        if adj is None:
            errors.append(f'{r.name}: enter the price difference as a number, e.g. 100 or -200.')
            continue
        if name != r.name:
            if any(o.name.lower() == name.lower() and o.id != r.id for o in rows):
                errors.append(f'"{name}" already exists.')
                continue
            # Quotations follow a renamed plywood
            Project.query.filter(Project.plywood == r.name).update({'plywood': name}, synchronize_session=False)
            Item.query.filter(Item.plywood == r.name).update({'plywood': name}, synchronize_session=False)
            r.name = name
        r.adjustment = adj
        r.active = bool(request.form.get(f'ply_active_{sid}'))
    if errors:
        return errors
    new_default = by_id.get(request.form.get('ply_default') or '') or next((r for r in rows if r.is_default), None)
    for sid in deleting:
        r = by_id.get(sid)
        if not r:
            continue
        if r is new_default:
            errors.append(f'"{r.name}" is the default. Choose another default first.')
        elif plywood.in_use(r.name):
            errors.append(f'"{r.name}" is used on quotations, so it can\'t be deleted. Untick "Show" to hide it instead.')
        else:
            db.session.delete(r)
            rows.remove(r)
    if errors:
        return errors
    new_name = ' '.join((request.form.get('ply_new_name') or '').split())[:plywood.NAME_MAX]
    if new_name:
        adj = _adjustment(request.form.get('ply_new_adj'))
        if len(new_name) < 2 or '|' in new_name:
            errors.append('Give the new plywood a name (at least 2 characters, no "|").')
        elif adj is None:
            errors.append('Enter the new plywood\'s price difference as a number, e.g. 100 or -200.')
        elif any(o.name.lower() == new_name.lower() for o in rows):
            errors.append(f'"{new_name}" already exists.')
        else:
            base = new_default.adjustment if new_default else 0.0
            row = PlywoodOption(name=new_name, adjustment=adj + (base or 0.0), active=True,
                                is_default=not rows, sort_order=max([r.sort_order for r in rows] or [0]) + 1)
            db.session.add(row)
            rows.append(row)
            new_default = new_default or row
    if errors or not new_default:
        return errors
    if not new_default.active:
        new_default.active = True
    base = new_default.adjustment or 0.0
    cbase = new_default.cost_adjustment if new_default.cost_adjustment is not None else base
    if base or cbase:
        _shift_plywood_rates(base, cbase)
        if base:
            flash(f'Material rates priced on plywood moved by {base:+g} ₹/sqft, so they\'re for {new_default.name} '
                  'and every quotation keeps the same price.', 'info')
    for r in rows:                                     # re-base: the default is ₹0, others keep their difference
        old_cost = r.cost_adjustment if r.cost_adjustment is not None else (r.adjustment or 0.0)
        r.is_default = r is new_default
        r.adjustment = round((r.adjustment or 0.0) - base, 2)
        new_cost = round(old_cost - cbase, 2)          # the same extra cost relative to the new default
        if r.cost_adjustment is not None or new_cost != r.adjustment:
            r.cost_adjustment = new_cost               # (unset costs keep following the price difference when it fits)
    plywood.clear_cache()
    return errors


def _shift_plywood_rates(delta, cost_delta):
    """A new default plywood: rates (and costs) of materials priced on plywood move by its difference, so every
    plywood keeps exactly the price (and cost) it had."""
    from sqlalchemy.orm import undefer
    from . import billing
    from .models import CostRate
    names = {m.name for m in Material.query.options(undefer(Material.uses_plywood)).all() if m.uses_plywood}
    for r in ItemRate.query.all():
        if r.wood_type in names:
            r.rate_per_sqft = round(max((r.rate_per_sqft or 0.0) + delta, 0.0), 2)
    if billing.ready() and cost_delta:
        for c in CostRate.query.filter_by(kind='material'):
            if c.name.split('|', 1)[0] in names:
                c.cost = round(max((c.cost or 0.0) + cost_delta, 0.0), 2)


def _rate(raw):
    try:
        return max(0.0, round(float(raw or 0), 2))
    except (TypeError, ValueError):
        return 0.0


def _save_materials_and_rates():
    """Renames and rates from the materials table. Returns error messages (caller commits / rolls back)."""
    from . import materials as M
    errors = []
    mats = Material.query.all()
    taken = {m.name.lower(): m.id for m in mats}
    for m in mats:
        new_name = request.form.get(f'name_{m.id}')
        if new_name is not None:
            try:
                new_name = M.clean_name(new_name)
            except ValueError as exc:
                errors.append(f'{m.name}: {exc}')
                continue
            if new_name != m.name:
                if taken.get(new_name.lower(), m.id) != m.id:
                    errors.append(f'"{new_name}" already exists.')
                    continue
                # Keep every quotation and rate pointing at the renamed material
                Item.query.filter(Item.wood_type == m.name).update({'wood_type': new_name}, synchronize_session=False)
                ItemRate.query.filter(ItemRate.wood_type == m.name).update({'wood_type': new_name},
                                                                          synchronize_session=False)
                _rename_material_costs(m.name, new_name)
                taken.pop(m.name.lower(), None)
                taken[new_name.lower()] = m.id
                m.name = new_name
        if f'ply_seen_{m.id}' in request.form and _plywood_ready():
            m.uses_plywood = bool(request.form.get(f'ply_{m.id}'))
        for i, work in enumerate(WORK_TYPES if m.uses_work_types else ['']):
            field = f'rate_{m.id}_{i}'
            if field not in request.form:
                continue
            rate = _rate(request.form.get(field))
            row = ItemRate.query.filter_by(wood_type=m.name, work_type=work).first()
            if row:
                row.rate_per_sqft = rate
            else:
                db.session.add(ItemRate(wood_type=m.name, work_type=work, rate_per_sqft=rate))
    return errors


def _material_action(action, mid):
    from . import materials as M
    m = db.session.get(Material, int(mid)) if mid.isdigit() else None
    if not m:
        return ['That material no longer exists.']
    if action == 'toggle':
        if m.active and Material.query.filter_by(active=True).count() <= 1:
            return ['Keep at least one material visible.']
        m.active = not m.active
        flash(f'"{m.name}" is now {"shown on new quotations" if m.active else "hidden from new quotations"}.', 'success')
        return []
    if action == 'delete':
        if M.in_use(m.name):
            return [f'"{m.name}" is used in existing quotations, so it can\'t be deleted. Hide it instead.']
        if m.active and Material.query.filter_by(active=True).count() <= 1:
            return ['Keep at least one material.']
        ItemRate.query.filter(ItemRate.wood_type == m.name).delete(synchronize_session=False)
        _rename_material_costs(m.name, None)
        db.session.delete(m)
        flash(f'Deleted "{m.name}".', 'success')
        return []
    return ['Unknown action.']


def _material_cost_rows(name):
    from . import billing
    from .models import CostRate
    if not billing.ready():
        return []
    return [c for c in CostRate.query.filter_by(kind='material') if c.name.split('|', 1)[0] == name]


def _rename_material_costs(old, new):
    """Costs follow a renamed material (new=None: the material was deleted)."""
    for c in _material_cost_rows(old):
        if new is None:
            db.session.delete(c)
        else:
            c.name = new + '|' + c.name.split('|', 1)[1]


# ── Costs & profit (owner only) ──────────────────────────────────────────────

def _parse_cost(raw):
    """'' → None (no cost set); otherwise a number ≥ 0, or False if invalid."""
    raw = (raw or '').strip().replace(',', '')
    if raw == '':
        return None
    try:
        value = float(raw)
    except ValueError:
        return False
    return value if value >= 0 else False


@admin_bp.route('/costs', methods=['GET', 'POST'])
def costs():
    """What each material and fitting costs you, so quotations show their estimated profit (admins only)."""
    from . import billing
    from . import materials as M
    from .models import CostRate
    if not billing.ready():
        flash('Costs & profit are available after the next database update.', 'warning')
        return redirect(url_for('admin.rates'))
    rates = {f'{r.wood_type}|{r.work_type}': r.rate_per_sqft for r in ItemRate.query.all()}
    existing = {(c.kind, c.name): c for c in CostRate.query.all()}
    combos = [(M.key(w, k), label) for w, k, label in M.combos(include_hidden=True)]
    fittings = PriceListItem.query.order_by(PriceListItem.name).all()
    if request.method == 'POST':
        errors = []

        def put(kind, name, raw, label):
            value = _parse_cost(raw)
            row = existing.get((kind, name))
            if value is False:
                errors.append(f'Enter a number for {label}.')
            elif value is None:
                if row:
                    db.session.delete(row)
            elif row:
                row.cost = value
            else:
                db.session.add(CostRate(kind=kind, name=name, cost=value))
        for i, (key, label) in enumerate(combos):
            put('material', key, request.form.get(f'm_{i}'), label)
        listed = {f.name.lower() for f in fittings}
        for f in fittings:
            put('fitting', f.name, request.form.get(f'f_{f.id}'), f.name)
        # Fittings typed on quotations that aren't on the price list
        for (kind, name), row in existing.items():
            if kind == 'fitting' and name.lower() not in listed:
                put('fitting', name, request.form.get(f'x_{row.id}'), name)
        # What each other plywood costs you extra per sqft ('' = same as its price difference)
        from . import plywood
        if plywood.table_ready():
            from .models import PlywoodOption
            for o in PlywoodOption.query.filter_by(is_default=False):
                if f'pc_{o.id}' not in request.form:
                    continue
                raw = (request.form.get(f'pc_{o.id}') or '').strip()
                if raw == '':
                    o.cost_adjustment = None
                else:
                    value = _adjustment(raw)
                    if value is None:
                        errors.append(f'Enter the extra cost of {o.name} as a number, e.g. 80 or -150.')
                    else:
                        o.cost_adjustment = value
        extra_name = ' '.join((request.form.get('new_fitting') or '').split())[:120]
        if extra_name:
            if any(k == 'fitting' and n.lower() == extra_name.lower() for k, n in existing):
                errors.append(f'"{extra_name}" already has a cost.')
            else:
                put('fitting', extra_name, request.form.get('new_fitting_cost'), extra_name)
        if errors:
            db.session.rollback()
            for e in errors:
                flash(e, 'danger')
        else:
            db.session.commit()
            flash('Costs saved. Each quotation now shows its estimated profit (only admins see it).', 'success')
        return redirect(url_for('admin.costs'))
    listed = {f.name.lower() for f in fittings}
    extra = sorted([row for (kind, name), row in existing.items() if kind == 'fitting' and name.lower() not in listed],
                   key=lambda r: r.name.lower())
    from . import plywood
    ply_rows = []
    if plywood.table_ready():
        ply_rows = [o for o in plywood.context()['options'] if not o['default']]
    return render_template('admin/costs.html', title='Costs & profit', combos=combos, rates=rates,
                           fittings=fittings, extra=extra, plywood_rows=ply_rows, plywood_default=plywood.default_name(),
                           costs={k: v.cost for k, v in existing.items()})


PAYMENT_KEYS = ['razorpay_key_id', 'razorpay_key_secret', 'webhook_secret',
                'upi_id', 'bank_name', 'account_name', 'account_number', 'ifsc_code']
EMAIL_KEYS = ['admin_email', 'smtp_host', 'smtp_port', 'smtp_user', 'smtp_pass']
SECRET_KEYS = {'razorpay_key_secret', 'webhook_secret', 'smtp_pass'}
SETTINGS_TABS = ('company', 'appearance', 'documents', 'invoices', 'email')


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


def _save_invoice_settings():
    from . import billing
    errors = []
    prefix = billing.clean_prefix(request.form.get('invoice_prefix', ''))
    AppSetting.set('invoice_prefix', prefix or billing.DEFAULT_PREFIX)
    try:
        rate = float(request.form.get('invoice_gst_rate', billing.DEFAULT_GST_RATE))
    except ValueError:
        rate = -1
    if rate in billing.GST_RATES:
        AppSetting.set('invoice_gst_rate', f'{rate:g}')
    else:
        errors.append('Choose a GST rate.')
    AppSetting.set('invoice_hsn', re.sub(r'[^0-9A-Za-z]', '', request.form.get('invoice_hsn', ''))[:10])
    prices = request.form.get('invoice_prices')
    AppSetting.set('invoice_prices', prices if prices in (billing.PRICES_EXCLUSIVE, billing.PRICES_INCLUSIVE)
                   else billing.PRICES_EXCLUSIVE)
    AppSetting.set('invoice_notes', request.form.get('invoice_notes', '').strip()[:1500])
    AppSetting.set('invoice_with_gst', 'no' if request.form.get('invoice_with_gst') == 'no' else 'yes')
    AppSetting.set('invoice_layout', 'summary' if request.form.get('invoice_layout') == 'summary' else 'rooms')
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
        elif tab == 'invoices':
            errors = _save_invoice_settings()
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
    from . import billing
    invoice_settings = billing.invoice_settings()
    support_display, support_url = branding.support_contact()
    support_links = {key: branding.support_message_url(what, current_user, request.host_url)
                     for key, what in (('name', 'company name'), ('gstin', 'GSTIN'), ('logo', 'logo'))}
    return render_template('admin/settings.html', title='Settings', tab=tab, support_links=support_links,
                           saved=saved, defaults=defaults, options=branding.ui_options(),
                           locked=branding.locked_fields(), lock_enabled=branding.lock_enabled(),
                           support_display=support_display, support_url=support_url,
                           invoice_settings=invoice_settings, gst_rates=billing.GST_RATES,
                           fy_example=billing.financial_year(date.today()),
                           business_state=billing.STATES.get(billing.business_state_code(), ''))


@admin_bp.route('/reports')
def reports():
    """Sales, collections, invoices and estimated profit by financial year, with a projection (admins only)."""
    from . import reports as R
    return render_template('admin/reports.html', title='Reports', r=R.build())


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
