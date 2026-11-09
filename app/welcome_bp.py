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


BACK = {'units': 'welcome.business', 'work': 'welcome.units', 'pricing': 'welcome.work', 'rates': 'welcome.work'}


def _page(template, key, back=None, back_args=None, **kw):
    """A tour page; back: the page before it (its GET puts the tour back on that step)."""
    return render_template(template, hide_nav=True, key=key, number=W.number(key), total=len(W.ORDER),
                           back_url=url_for(back, **(back_args or {})) if back else None, title="Let's set up your QuoteRoom", **kw)


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
    return redirect(url_for('welcome.work' if key == 'pricing' else f'welcome.{key}'))


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
        if not confirmed and ('name' not in locked or 'logo' not in locked):     # the box is on the page: always tick it
            flash('Tick "These details are correct" to continue.', 'danger')
            return redirect(url_for('welcome.business'))
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
            clean = _phone(phone)
            if clean is None:
                errors.append('Type your phone number with digits only, e.g. 98765 43210.')
            else:
                AppSetting.set(phone_key, clean)
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
        from .ops import PREFILLED_NAME_KEY
        AppSetting.set(PREFILLED_NAME_KEY, '')      # confirmed: their own now (even if unchanged from their request)
        setup_guide.mark('company')
        if branding.get_brand().get('logo_url'):
            setup_guide.mark('logo')
        return _next('business')
    db.session.commit()
    s = AppSetting.get_many([name_key, phone_key])
    phone = s[phone_key] or ''
    return _page('welcome/business.html', 'business', name=s[name_key] or '', phone=_phone(phone) or phone,
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
    return _page('welcome/units.html', 'units', back=BACK['units'], size=U.size_unit(), area=U.area_unit())


# ── 3. Your work: what you mostly do, and (interiors) how you price ─────────────

def _kinds_page(chosen):
    """The kinds to choose from: those the console offers, and the one already chosen."""
    from . import business
    offered = business.kinds_offered()
    return {k: v for k, v in W.KINDS.items() if k in offered or k == chosen}   # the console's Kinds of business


@welcome_bp.route('/work', methods=['GET', 'POST'])
def work():
    """What they mostly do. Interiors, turnkey and furniture firms are then asked how they price; every other kind
    prices by item, without being asked."""
    from . import boq
    W.go_to('pricing')
    if request.method == 'POST':
        k = request.form.get('kind')
        if k not in W.KINDS:
            flash('Choose what you mostly do.', 'danger')
            return redirect(url_for('welcome.work'))
        W.set_kind(k)
        if k in W.PRICING_KINDS:
            db.session.commit()
            return redirect(url_for('welcome.pricing'))
        boq.set_pricing(boq.ITEM, starter=False)
        W.set_pricing(boq.ITEM)
        return _next('pricing')
    db.session.commit()
    chosen = W.state().get('kind') or _trial_kind()
    return _page('welcome/kind.html', 'pricing', back=BACK['work'], kinds=_kinds_page(chosen), icons=W.ICONS,
                 chosen=chosen, action=url_for('welcome.work'), has_items=False)


@welcome_bp.route('/pricing', methods=['GET', 'POST'])
def pricing():
    """By material or by item (interiors, turnkey and furniture), each with the quotation PDF it makes."""
    from . import boq, business
    W.go_to('pricing')
    if (W.state().get('kind') or 'interiors') not in W.PRICING_KINDS:
        db.session.commit()
        return redirect(url_for('welcome.work'))
    if request.method == 'POST':
        mode = request.form.get('mode')
        if mode not in (boq.MATERIAL, boq.ITEM):
            flash('Choose how you price your work.', 'danger')
            return redirect(url_for('welcome.pricing'))
        boq.set_pricing(mode, starter=False)
        W.set_pricing(mode)
        return _next('pricing')
    db.session.commit()
    p = business.profile()
    return _page('welcome/pricing.html', 'pricing', back=BACK['pricing'], examples=W.pricing_examples(p['kind']),
                 chosen=W.state().get('pricing'), recommend=None, label=p['label'])


# ── 4. Your rates ────────────────────────────────────────────────────────────

def _trial_kind():
    """What they picked on the trial form (set up with the trial), to start with it chosen."""
    from . import business
    from .models import AppSetting
    found = AppSetting.get(business.KEY) or ''
    return W.OLD_KINDS.get(found, found) if found else None


def _has_items():
    """Their rates are already in, from outside this tour: their own items (an old quotation read, a price list loaded
    from the console), or rates set up by material."""
    from . import boq, setup_guide
    if boq.enabled() and W.own_items():
        return True
    return 'import' in (setup_guide._state().get('done') or [])


@welcome_bp.route('/rates', methods=['GET', 'POST'])
def rates():
    """Their rates, by what they do (step 3): interiors and turnkey firms are first asked for an old quotation or rate
    Excel (when Bring your old quotation is on); then their materials (by material) or their items (by item). When
    step 3 was skipped, it asks what they mostly do here."""
    from . import ai_import
    W.go_to('rates')
    db.session.commit()
    k = request.form.get('kind') if request.method == 'POST' else W.state().get('kind')
    if request.method == 'POST' and k not in W.KINDS:
        flash('Choose what you mostly do.', 'danger')
        return redirect(url_for('welcome.rates'))
    if k in W.KINDS:
        if k in W.FILE_KINDS and ai_import.available() and not _has_items():
            return redirect(url_for('welcome.file', kind=k))
        return _your_rates(k)
    chosen = _trial_kind()
    return _page('welcome/kind.html', 'rates', back=BACK['rates'], kinds=_kinds_page(chosen), icons=W.ICONS,
                 chosen=chosen, action=url_for('welcome.rates'), has_items=_has_items())


def _back_from_rates(k):
    """Back from step 4's pages: how you price (interiors), else what you do."""
    return 'welcome.pricing' if (k or W.state().get('kind')) in W.PRICING_KINDS else 'welcome.work'


@welcome_bp.route('/rates/file', methods=['GET', 'POST'])
def file():
    """"Do you have an old quotation or rate Excel ready?" (interiors and turnkey)."""
    from . import ai_import
    W.go_to('rates')
    db.session.commit()
    k = request.args.get('kind') if request.args.get('kind') in W.KINDS else 'interiors'
    if request.method == 'POST':
        if request.form.get('file') == 'yes' and ai_import.available():
            return redirect(url_for('admin.ai_import'))
        return _your_rates(k)
    if not ai_import.available():
        return _your_rates(k)
    return _page('welcome/rates.html', 'rates', back=_back_from_rates(k), has_items=_has_items())


def _your_rates(k):
    """Their rates to check: by material, the materials page; by item, their lines and the typical ones for `k`."""
    if W.by_material():
        return redirect(url_for('welcome.materials', kind=k))
    return redirect(url_for('welcome.check', kind=k))


@welcome_bp.route('/rates/kind')
def kind():
    return redirect(url_for('welcome.rates'))       # (the first page of step 3 before it asked what you do first)


@welcome_bp.route('/rates/check', methods=['GET', 'POST'])
def check():
    """"These are your rates": their items in sections, and (with ?kind=…, when their rates aren't already in from
    elsewhere) the typical items for that business, shown but not saved. Sections can be renamed and added, each
    with an empty row to add more. Save my rates writes it all, priced by item."""
    import re
    from . import boq
    from .models import BoqItem
    W.go_to('rates')
    k = request.args.get('kind') if request.args.get('kind') in W.KINDS else None
    if W.by_material():                           # priced by material: their materials and rates
        db.session.commit()
        return redirect(url_for('welcome.materials', kind=k))
    if request.method == 'POST':
        if not boq.ready():
            flash('Your app needs its latest update first. Please contact support.', 'danger')
            return redirect(url_for('welcome.check', kind=k))
        sections = {}
        for key, value in request.form.items():
            m = re.match(r'^grp_(\d+)$', key)
            if m:
                sections[m.group(1)] = ' '.join(value.split())[:60]
        for sk, name in sections.items():          # a section renamed: its items move with it
            old = request.form.get(f'grpold_{sk}')
            if old is not None and name and name != old:
                q = BoqItem.query.filter((BoqItem.category == old) | (BoqItem.category.is_(None))) if old in ('', 'Other') \
                    else BoqItem.query.filter(BoqItem.category == old)
                for it in q.all():
                    it.category = name
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
        added = []
        for key in request.form:                   # new rows (n…) and the typical items shown (s…, unless untick)
            m = re.match(r'^(?:n(\d+)x\d*|s(\d+)y\d+)_name$', key)
            if not m:
                continue
            p = key[:-len('name')]
            name = ' '.join(request.form.get(key, '').split())[:100]
            if not name or name.lower() in have or request.form.get(p + 'skip'):
                continue
            b = BoqItem(name=name, unit=boq.clean_unit(request.form.get(p + 'unit')),
                        rate=_money(request.form.get(p + 'rate'), 0),
                        description=(request.form.get(p + 'desc') or '').strip()[:500] or None,
                        category=sections.get(m.group(1) or m.group(2)) or 'Other')
            db.session.add(b)
            db.session.flush()
            added.append(b.id)
            have.add(name.lower())
        W.note_added(added)
        if k:
            W.set_kind(k)
        boq.set_pricing(boq.ITEM, starter=False)
        from . import setup_guide
        setup_guide.mark('rates')
        db.session.commit()
        flash('Your rates are saved.', 'success')
        return _next('rates')
    db.session.commit()
    items = BoqItem.query.order_by(BoqItem.id).all() if boq.enabled() else []
    groups = {}
    for it in items:                              # in their sections, in the order they were added
        groups.setdefault(it.category or 'Other', ([], []))[0].append(it)
    if k and not _has_items():
        have = {it.name.lower() for it in items}
        for group, name, unit, rate, description in W.typical_rows(k):
            if name.lower() not in have:
                groups.setdefault(group, ([], []))[1].append(
                    {'name': name, 'unit': unit, 'rate': rate, 'description': description})
    return _page('welcome/check.html', 'rates', back=_back_from_rates(k), groups=[(g, a, b) for g, (a, b) in groups.items()],
                 units_list=boq.units_for_business())


@welcome_bp.route('/rates/materials', methods=['GET', 'POST'])
def materials():
    """"These are your rates", priced by material: each material's rate per sqft (or sq m) for Box Work and Frame
    Work, or one rate; a bin hides one (old quotations keep it); new materials in the empty rows. Fittings and plywood
    stay in Admin → Rates."""
    import re
    from . import boq, materials as M, units
    from .catalog import WORK_TYPES
    from .models import ItemRate, Material
    W.go_to('rates')
    k = request.args.get('kind') if request.args.get('kind') in W.KINDS else None
    if not M.table_ready():
        db.session.commit()
        return redirect(url_for('admin.rates'))
    mats = Material.query.filter_by(active=True).order_by(Material.sort_order, Material.id).all()
    rates = {(r.wood_type, r.work_type): r for r in ItemRate.query.all()}

    def current(name, work):                       # the rate in the business's area unit
        r = rates.get((name, work))
        return units.rate_value(r.rate_per_sqft or 0) if r else 0

    def set_rate(name, work, value):
        row = rates.get((name, work))
        if row is None:
            row = rates[(name, work)] = ItemRate(wood_type=name, work_type=work, rate_per_sqft=0)
            db.session.add(row)
        row.rate_per_sqft = units.rate_to_sqft(value)

    if request.method == 'POST':
        errors = []
        for m in mats:
            if request.form.get(f'm{m.id}_hide'):
                m.active = False
                continue
            for work in (WORK_TYPES if m.uses_work_types else ['']):
                raw = request.form.get(f'm{m.id}_{work or "rate"}')
                if raw is not None:
                    set_rate(m.name, work, _money(raw, current(m.name, work)))
        top = max([m.sort_order for m in mats] or [0])
        names = {n.lower() for (n,) in db.session.query(Material.name)}
        for key in request.form:                     # new materials: nm_, nm2_… (one per row)
            if not re.fullmatch(r'nm\d*_name', key):
                continue
            p = key[:-len('name')]
            try:
                name = M.clean_name(request.form.get(key)) if (request.form.get(key) or '').strip() else ''
            except ValueError as exc:
                errors.append(str(exc))
                continue
            if not name or name.lower() in names:
                continue
            uses_work = request.form.get(p + 'type') == 'work'
            top += 1
            db.session.add(Material(name=name, uses_work_types=uses_work, active=True, sort_order=top))
            for work in (WORK_TYPES if uses_work else ['']):
                set_rate(name, work, _money(request.form.get(p + 'rate'), 0))
            names.add(name.lower())
        if errors:
            db.session.rollback()
            for e in errors:
                flash(e, 'danger')
            return redirect(url_for('welcome.materials', kind=k))
        if k:
            W.set_kind(k)
        boq.set_pricing(boq.MATERIAL, starter=False)
        from . import setup_guide
        setup_guide.mark('rates')
        db.session.commit()
        flash('Your rates are saved.', 'success')
        return _next('rates')
    db.session.commit()
    rows = [{'m': m, 'rates': {w: current(m.name, w) for w in (WORK_TYPES if m.uses_work_types else [''])}}
            for m in mats]
    return _page('welcome/materials.html', 'rates', back=_back_from_rates(k),
                 rows=rows, work_types=WORK_TYPES, rate_label=units.rate_label())


def _phone(raw):
    """A phone number as shown on quotations ('+91 98765 43210' for an Indian mobile), or None when it isn't one
    (letters, or too few or too many digits)."""
    import re
    from .marketing import normalise_phone
    from .ops import phone_display
    if not re.fullmatch(r'[0-9+()\- ]+', raw):
        return None
    mobile = normalise_phone(raw)
    if mobile:
        return phone_display(mobile)
    digits = re.sub(r'\D', '', raw)
    return ' '.join(raw.split()) if 10 <= len(digits) <= 13 else None


def _money(value, default):
    try:
        v = float(str(value).replace(',', '').replace('₹', '').strip())
    except (TypeError, ValueError):
        return default
    return max(v, 0)


# ── 4. Your first quotation, then done ───────────────────────────────────────

@welcome_bp.route('/sample')
def sample():
    """First sign-in: a sample 2 BHK quotation in their company's name, as their customer would get it, before any
    setup (app/sample_quote.py). Then "Make it yours" starts the guided setup."""
    from . import sample_quote
    if not sample_quote.available():
        return redirect(url_for('welcome.resume'))
    p = sample_quote.make(current_user)
    from .branding import get_brand
    return render_template('welcome/sample.html', hide_nav=True, title='Your first quotation', project=p,
                           company=get_brand().get('name') or 'your company')


@welcome_bp.route('/sample.pdf')
def sample_pdf():
    """The sample as the customer PDF: its title page, then the quotation (no About us or Next steps page)."""
    from flask import send_file
    from . import sample_quote
    from .models import AppSetting
    from .pdf_utils import generate_customer_pdf
    p = sample_quote.project()
    if p is None:
        abort(404)
    pay = AppSetting.get_many(['upi_id', 'bank_name', 'account_name', 'account_number', 'ifsc_code'])
    from .branding import get_brand
    name = ''.join(ch if ch.isalnum() else '_' for ch in (get_brand().get('name') or 'QuoteRoom')).strip('_')
    return send_file(generate_customer_pdf(p, payment_settings=pay, cover=True, closing=False), mimetype='application/pdf',
                     as_attachment=request.args.get('download') == '1', download_name=f'Sample_quotation_{name}.pdf')


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


# ── A free set-up call with us, or a WhatsApp chat (app/callbook.py) ─────────────

@welcome_bp.route('/call', methods=['GET', 'POST'])
def call():
    """Book a free 10-minute set-up call: our free times for the next week; the booking goes on our Schedule."""
    from . import branding, callbook
    if not callbook.available():
        abort(404)
    if request.method == 'POST':
        try:
            callbook.book(request.form.get('slot'), request.form.get('phone', ''), request.form.get('note', ''),
                          current_user.display_name)
        except ValueError as exc:
            flash(str(exc), 'danger')
            return redirect(url_for('welcome.call'))
        return redirect(url_for('welcome.call'))
    return render_template('welcome/call.html', title='Book a free set-up call', booked=callbook.booked(),
                           slots=callbook.slots(), whatsapp=callbook.whatsapp_url(),
                           phone=branding.get_brand().get('phone') or '')
