"""Pages of the guided first setup (logic in welcome.py): one question a page, for the admin."""
from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from . import db, welcome as W

welcome_bp = Blueprint('welcome', __name__, url_prefix='/welcome')


@welcome_bp.before_request
@login_required
def admins_only():
    from .demo import demo_enabled
    if not current_user.is_admin or demo_enabled():
        abort(404)


def _page(template, key, **kw):
    return render_template(template, hide_nav=True, key=key, number=W.number(key), total=len(W.ORDER),
                           title="Let's set up your QuoteRoom", **kw)


def _next(key, skipped=False):
    """On to the step after `key`: its page here, or the app's own page for steps 4 and 5."""
    nxt = W.advance(key, skipped=skipped)
    db.session.commit()
    return redirect(url_for('welcome.resume') if nxt else url_for('welcome.done'))


@welcome_bp.route('/')
def resume():
    """Wherever the tour is (started again if it was left or never begun)."""
    if not W.active():
        if W.state().get('finished') == 'done':
            return redirect(url_for('welcome.done'))
        W.start()
        db.session.commit()
    key = W.step()
    if key == 'quote':
        return redirect(url_for('welcome.quote'))
    if key == 'send':
        pid = W.state().get('project')
        from .models import Project
        last = Project.query.get(pid) if pid else Project.query.order_by(Project.id.desc()).first()
        return redirect(url_for('projects.view_project', project_id=last.id) if last else url_for('welcome.done'))
    return redirect(url_for(f'welcome.{key}'))


@welcome_bp.route('/skip/<key>', methods=['POST'])
def skip(key):
    if key not in W.ORDER:
        abort(404)
    return _next(key, skipped=request.form.get('done') != '1')


@welcome_bp.route('/exit', methods=['POST'])
def leave():
    W.finish('exit')
    db.session.commit()
    flash('You can finish setting up any time: Admin → Setup guide.', 'info')
    return redirect(url_for('projects.list_projects'))


@welcome_bp.route('/restart', methods=['POST'])
def restart():
    W.start()
    db.session.commit()
    return redirect(url_for('welcome.resume'))


# ── 1. Your business ─────────────────────────────────────────────────────────

@welcome_bp.route('/business', methods=['GET', 'POST'])
def business():
    from . import branding
    from .models import AppSetting
    W.go_to('business')
    locked = branding.locked_fields()
    name_key, phone_key = branding.FIELDS['name'][0], branding.FIELDS['phone'][0]
    if request.method == 'POST':
        errors = []
        confirmed = not branding.lock_enabled() or bool(request.form.get('confirm'))
        name = ' '.join(request.form.get('name', '').split())[:80]
        phone = ' '.join(request.form.get('phone', '').split())[:30]
        if 'name' not in locked:
            if not name:
                errors.append('Type your business name.')
            elif name != (AppSetting.get(name_key, '') or '').strip() and not confirmed:
                errors.append('Tick "These details are correct" to save your business name.')
            else:
                AppSetting.set(name_key, name)
                if branding.lock_enabled():
                    branding.relock('name')
        if phone:
            AppSetting.set(phone_key, phone)
        logo = request.files.get('logo')
        if logo and logo.filename and 'logo' not in locked and not errors:
            if not confirmed:
                errors.append('Tick "These details are correct" to upload your logo.')
            else:
                try:
                    png, version = branding.process_logo_upload(logo.read())
                    branding.save_logo_png(png, version)
                    branding.relock('logo')
                except branding.LogoError as exc:
                    errors.append(str(exc))
        if errors:
            db.session.rollback()
            for e in errors:
                flash(e, 'danger')
            return redirect(url_for('welcome.business'))
        from . import setup_guide
        setup_guide.mark('company')
        if branding.get_brand().get('logo_url'):
            setup_guide.mark('logo')
        return _next('business')
    db.session.commit()
    s = AppSetting.get_many([name_key, phone_key])
    return _page('welcome/business.html', 'business', name=s[name_key] or '', phone=s[phone_key] or '',
                 locked=locked, lock_enabled=branding.lock_enabled(), logo_url=branding.get_brand().get('logo_url'))


# ── 2. How you measure ───────────────────────────────────────────────────────

@welcome_bp.route('/units', methods=['GET', 'POST'])
def units():
    from . import units as U
    from .models import AppSetting
    W.go_to('units')
    if request.method == 'POST':
        size, area = request.form.get('size_unit'), request.form.get('area_unit') or 'sqft'
        if size not in U.SIZE_UNITS or area not in U.AREA_UNITS:
            flash('Choose how you measure.', 'danger')
            return redirect(url_for('welcome.units'))
        AppSetting.set('size_unit', size)
        AppSetting.set('area_unit', area)
        U.clear_cache()
        from . import setup_guide
        setup_guide.mark('units')
        return _next('units')
    db.session.commit()
    return _page('welcome/units.html', 'units', size=U.size_unit(), area=U.area_unit())


# ── 3. Your rates ────────────────────────────────────────────────────────────

def _has_items():
    """Their rates are already in: their own items, or rates set up before (a price list loaded from the console)."""
    from . import boq, setup_guide
    from .models import BoqItem
    if boq.enabled() and BoqItem.query.filter(BoqItem.unit != boq.LUMP_SUM).first() is not None:
        return True
    return 'rates' in (setup_guide._state().get('done') or [])


@welcome_bp.route('/rates', methods=['GET', 'POST'])
def rates():
    from . import ai_import
    W.go_to('rates')
    db.session.commit()
    if request.method == 'POST':
        if request.form.get('file') == 'yes' and ai_import.available():
            return redirect(url_for('admin.ai_import'))
        return redirect(url_for('welcome.kind'))
    if not ai_import.available():                 # no upload here: straight to the typical rates
        return redirect(url_for('welcome.check') if _has_items() else url_for('welcome.kind'))
    return _page('welcome/rates.html', 'rates', has_items=_has_items())


@welcome_bp.route('/rates/kind', methods=['GET', 'POST'])
def kind():
    W.go_to('rates')
    if request.method == 'POST':
        k = request.form.get('kind')
        if k not in W.KINDS:
            flash('Choose what you mostly do.', 'danger')
            return redirect(url_for('welcome.kind'))
        from . import boq
        if not boq.ready():
            flash('Your app needs its latest update first. Please contact support.', 'danger')
            return redirect(url_for('welcome.kind'))
        if not _has_items():                      # never over rates already set up (they're checked instead)
            W.add_typical(k)
        db.session.commit()
        return redirect(url_for('welcome.check'))
    db.session.commit()
    return _page('welcome/kind.html', 'rates', kinds=W.KINDS, has_items=_has_items())


@welcome_bp.route('/rates/check', methods=['GET', 'POST'])
def check():
    """"These are your rates": every item with its unit and rate, to change; empty rows to add more."""
    from . import boq
    from .models import BoqItem
    W.go_to('rates')
    if not boq.enabled():                         # priced by material (set up from their file): the Rates page
        db.session.commit()
        return redirect(url_for('admin.rates'))
    if request.method == 'POST':
        for item in BoqItem.query.all():
            if request.form.get(f'del_{item.id}'):
                db.session.delete(item)
                continue
            name = ' '.join(request.form.get(f'name_{item.id}', item.name).split())[:100]
            if name:
                item.name = name
            item.unit = boq.clean_unit(request.form.get(f'unit_{item.id}', item.unit))
            item.rate = _money(request.form.get(f'rate_{item.id}'), item.rate)
        have = {i.name.lower() for i in BoqItem.query.all()}
        for key in request.form:
            if not (key.startswith('new') and key.endswith('_name')):
                continue
            p = key[:-len('name')]
            name = ' '.join(request.form.get(key, '').split())[:100]
            if not name or name.lower() in have:
                continue
            db.session.add(BoqItem(name=name, unit=boq.clean_unit(request.form.get(p + 'unit')),
                                   rate=_money(request.form.get(p + 'rate'), 0), category='Other'))
            have.add(name.lower())
        from . import setup_guide
        setup_guide.mark('pricing')
        setup_guide.mark('rates')
        db.session.commit()
        flash('Your rates are saved.', 'success')
        return _next('rates')
    db.session.commit()
    items = BoqItem.query.order_by(BoqItem.id).all()
    first = {}
    for it in items:                              # in their groups, in the order they were added
        first.setdefault(it.category or '', it.id)
    items.sort(key=lambda it: (first[it.category or ''], it.id))
    return _page('welcome/check.html', 'rates', items=items, units_list=boq.units_for_business())


def _money(value, default):
    try:
        v = float(str(value).replace(',', '').replace('₹', '').strip())
    except (TypeError, ValueError):
        return default
    return max(v, 0)


# ── 4. Your first quotation, then done ───────────────────────────────────────

@welcome_bp.route('/quote')
def quote():
    """The quotation rebuilt from their old one, else the new quotation form (the strip on top says what to do)."""
    from .models import Project
    W.go_to('quote')
    db.session.commit()
    pid = W.state().get('project')
    if pid and Project.query.get(pid):
        return redirect(url_for('projects.view_project', project_id=pid))
    return redirect(url_for('projects.create_project'))


@welcome_bp.route('/done')
def done():
    from . import setup_guide
    if W.active():
        W.finish('done')
        db.session.commit()
    st = setup_guide.status()
    later = [(s, d) for s, d in st['steps'] if s.key in ('logo', 'payments', 'pdf', 'invoices', 'team') and not d]
    return render_template('welcome/done.html', hide_nav=True, title='You\'re set up', later=later)
