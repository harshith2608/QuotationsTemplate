"""Item options for a business that prices by item: the same item costs more in another finish, board, brand…
(a wardrobe at ₹1,800/sqft in laminate, +25% in acrylic; +₹400/sqft on Century Bond in place of Century Sainik).

The business lists its options once (Admin → Rates → Item options), in sections it names itself (Finish, Board,
Hardware…). In each section the first option is the base (the saved lines' rates are for it); every other one adds
a % of the base rate or a ₹ amount per unit (either can be negative: a cheaper board). Each saved line is ticked for
the sections it comes in. On a quotation such a line gets one choice per section; the rate is
    base rate × (1 + the chosen %s / 100) + the chosen ₹ amounts
and the line prints as "Wardrobe (Acrylic finish, 16mm Century Bond 710)". Base options print nothing.

Stored in AppSetting 'boq_finishes' as {"sections": [{"name", "options": [{"name", "extra"} or {"name", "amount"}],
"lines": [BoqItem ids]}]}. The older {"options": [...], "lines": [...]} (one list of finishes, % only) reads as one
section named "Finish", so businesses already set up need nothing.

A BOQ line on a quotation keeps its non-base choices as one text, "Acrylic|16mm Century Bond 710" (option names
are unique across sections, so each name finds its section), in items.wood_type (unused by BOQ lines otherwise),
running on into items.work_type (marked with a leading '+') past 50 characters, so no database update is needed.
"""
import json

KEY = 'boq_finishes'
NAME_MAX = 40
MAX_OPTIONS = 12
MAX_SECTIONS = 4
SEP = '|'
STORE_MAX = 99                    # wood_type (50) + work_type (50, less its '+')
LEGACY_SECTION = 'Finish'


def _load():
    from .models import AppSetting
    try:
        data = json.loads(AppSetting.get(KEY, '') or '{}')
    except ValueError:
        data = {}
    return data if isinstance(data, dict) else {}


def _ids(raw):
    return {int(i) for i in raw or [] if str(i).isdigit()}


def _num(v):
    try:
        return round(float(v or 0), 2)
    except (TypeError, ValueError):
        return 0.0


def all_sections():
    """Every saved section as it is (for Admin → Rates), even one with a single option:
    [{'name', 'options': [{'name', 'extra', 'amount'}], 'lines': {ids}}]. The base option's extra and amount are 0."""
    data = _load()
    raw = data.get('sections')
    if not isinstance(raw, list):              # the older single list of finishes
        raw = [{'name': LEGACY_SECTION, 'options': data.get('options') or [], 'lines': data.get('lines') or []}] \
            if data.get('options') else []
    out = []
    for s in raw:
        if not isinstance(s, dict):
            continue
        opts = [o for o in s.get('options') or [] if isinstance(o, dict) and o.get('name')]
        out.append({'name': str(s.get('name') or LEGACY_SECTION)[:NAME_MAX],
                    'options': [{'name': str(o['name'])[:NAME_MAX],
                                 'extra': 0.0 if n == 0 or o.get('amount') not in (None, '') else _num(o.get('extra')),
                                 'amount': 0.0 if n == 0 else _num(o.get('amount'))}
                                for n, o in enumerate(opts)],
                    'lines': _ids(s.get('lines'))})
    return out


def sections():
    """The sections with something to choose (two options or more)."""
    return [s for s in all_sections() if len(s['options']) >= 2]


def options():
    """The first section's options (the base first), or [] (nothing to choose)."""
    secs = sections()
    return secs[0]['options'] if secs else []


def line_ids():
    """Ids of the saved lines that come in any section."""
    return set().union(*[s['lines'] for s in sections()]) if sections() else set()


def _find(name):
    """(section, option, is_base) for an option name, or (None, None, False)."""
    key = (name or '').strip().lower()
    for s in sections():
        for n, o in enumerate(s['options']):
            if o['name'].lower() == key:
                return s, o, n == 0
    return None, None, False


def parts(finish):
    """'Acrylic|Century Bond' → ['Acrylic', 'Century Bond']."""
    return [p for p in (' '.join(x.split()) for x in str(finish or '').split(SEP)) if p]


def save_sections(secs):
    """secs: [{'name', 'options': [(name, value, 'pct' | 'amt')] (the base first), 'lines': ids}]. Sections with no
    name and no options are dropped. Returns error messages (nothing saved then)."""
    from .models import AppSetting
    clean, errors, sec_seen, opt_seen = [], [], set(), set()
    for s in secs:
        sname = ' '.join(str(s.get('name') or '').replace(SEP, ' ').split())[:NAME_MAX]
        opts = []
        for name, value, kind in s.get('options') or []:
            name = ' '.join(str(name or '').replace(SEP, ' ').split())[:NAME_MAX]
            if not name:
                continue
            if name.lower() in opt_seen:
                errors.append(f'"{name}" is in your item options twice (each option needs its own name).')
                continue
            opt_seen.add(name.lower())
            if not opts:
                opts.append({'name': name})                  # the base
                continue
            try:
                value = float(value or 0)
            except (TypeError, ValueError):
                errors.append(f'"{name}": the extra should be a number.')
                continue
            if kind == 'amt':
                if not -1000000 <= value <= 1000000:
                    errors.append(f'"{name}": the ₹ extra is too large.')
                    continue
                opts.append({'name': name, 'amount': round(value, 2)})
            else:
                if value < -90 or value > 500:
                    errors.append(f'"{name}": the % extra should be between -90 and 500.')
                    continue
                opts.append({'name': name, 'extra': round(value, 2)})
        if not opts and not sname:
            continue
        sname = sname or (LEGACY_SECTION if not clean else f'Option {len(clean) + 1}')
        if sname.lower() in sec_seen:
            errors.append(f'Two sections are named "{sname}".')
            continue
        sec_seen.add(sname.lower())
        if len(opts) > MAX_OPTIONS:
            errors.append(f'{sname}: up to {MAX_OPTIONS} options.')
        clean.append({'name': sname, 'options': opts, 'lines': sorted(_ids(s.get('lines')))})
    if len(clean) > MAX_SECTIONS:
        errors.append(f'Up to {MAX_SECTIONS} sections.')
    if errors:
        return errors
    AppSetting.set(KEY, json.dumps({'sections': clean}))
    return []


def save(opts, ids):
    """The older single list (one section, % extras): kept for callers that set just the finishes."""
    secs = all_sections()
    first = {'name': secs[0]['name'] if secs else LEGACY_SECTION,
             'options': [(n, e, 'pct') for n, e in opts], 'lines': ids}
    return save_sections([first] + [_as_input(s) for s in secs[1:]])


def _as_input(s, lines=None):
    return {'name': s['name'], 'lines': s['lines'] if lines is None else lines,
            'options': [(o['name'], o['amount'] if o['amount'] else o['extra'], 'amt' if o['amount'] else 'pct')
                        for o in s['options']]}


def set_lines(ticks):
    """ticks: {section name: ids} from the items table; sections not in it keep their lines."""
    return save_sections([_as_input(s, ticks.get(s['name'], s['lines'])) for s in all_sections()])


def base():
    opts = options()
    return opts[0]['name'] if opts else ''


def _extras(finish):
    pct = amt = 0.0
    for p in parts(finish):
        _, o, is_base = _find(p)
        if o and not is_base:
            pct += o['extra']
            amt += o['amount']
    return pct, amt


def extra(name):
    """The % extra for an option name (0 for a base or an unknown one)."""
    return _extras(name)[0]


def rate_for(base_rate_, finish):
    """The rate in these choices, from the base options' rate."""
    pct, amt = _extras(finish)
    return round(max(base_rate_ * (1 + pct / 100) + amt, 0.0), 2)


def clean(finish):
    """The choices to keep on a quotation line: base options dropped; others kept as chosen (even if renamed or
    removed since, so an old quotation still says what was quoted), at most one per section."""
    out, used = [], set()
    for p in parts(finish):
        p = p[:NAME_MAX]
        s, o, is_base = _find(p)
        if is_base:
            continue
        sec = s['name'].lower() if s else '?' + p.lower()
        if sec in used:
            continue
        used.add(sec)
        out.append(o['name'] if o else p)
    text = SEP.join(out)
    while len(text) > STORE_MAX and out:            # very long names: keep the ones that fit
        out.pop()
        text = SEP.join(out)
    return text


def store(item, finish):
    """Keep the choices on a quotation line (wood_type, running on into work_type)."""
    finish = finish or ''
    item.wood_type = finish[:50]
    item.work_type = ('+' + finish[50:STORE_MAX]) if len(finish) > 50 else ''


def stored(item):
    """The choices kept on a quotation line."""
    more = item.work_type or ''
    return (item.wood_type or '') + (more[1:] if more.startswith('+') else '')


def base_rate(rate, finish):
    """The base options' rate for a line priced in these choices (for "Save as my default")."""
    pct, amt = _extras(finish)
    return round((rate - amt) / (1 + pct / 100), 2) if pct > -100 else rate


def work_hidden(name):
    """A line named 'Kitchen Base Unit – Box Work' prints as 'Kitchen Base Unit': like a material's work type, Box Work /
    Frame Work is a word for the firm (two saved lines, two rates), not the customer — unless the business shows work
    types (Settings → Quotation PDFs). The quotation form keeps the full name."""
    from .catalog import WORK_TYPES
    main, dash, work = (name or '').rpartition(' – ')
    if not dash:
        main, dash, work = (name or '').rpartition(' - ')
    if not dash or work.strip() not in WORK_TYPES or not main.strip():
        return name
    from .materials import SHOW_WORK_KEY
    from .models import AppSetting
    return name if AppSetting.get(SHOW_WORK_KEY) == '1' else main.strip()


def _shown(part, alone):
    """An option as printed: a finish says so ('Acrylic finish'); a board, brand… prints as it is."""
    s, _, _ = _find(part)
    if s is not None:
        finishy = 'finish' in s['name'].lower()
    else:                                  # renamed or removed since: an old one-finish line still reads as before
        secs = sections()
        finishy = alone and (not secs or 'finish' in secs[0]['name'].lower())
    return part if not finishy or part.lower().endswith('finish') else f'{part} finish'


def label(name, finish):
    """'Wardrobe (Acrylic finish, 16mm Century Bond 710)', or the name alone when there are no choices (without a
    Box / Frame Work ending)."""
    name = work_hidden(name)
    ps = parts(finish)
    if not ps:
        return name
    return f"{name} ({', '.join(_shown(p, len(ps) == 1) for p in ps)})"


def for_form():
    """For the quotation form: {'sections': [{'name', 'options', 'base'}]} or None when there's nothing to choose."""
    secs = sections()
    return {'sections': [{'name': s['name'], 'options': s['options'], 'base': s['options'][0]['name']} for s in secs]} \
        if secs else None


def line_sections():
    """{saved line id: [section names it comes in]}."""
    out = {}
    for s in sections():
        for i in s['lines']:
            out.setdefault(i, []).append(s['name'])
    return out


def set_from_price_list(secs):
    """From a price list file: [{'name', 'options': [{'name', 'extra' | 'amount'}], 'line_names': [...]}]. A section
    already there (by name) is replaced, keeping the lines already ticked (a file with only a few new lines doesn't
    untick the others); other sections stay."""
    from sqlalchemy import func
    from . import db
    from .models import BoqItem
    current = {s['name'].lower(): s for s in all_sections()}
    out = []
    for s in secs:
        keys = [n.lower() for n in s.get('line_names') or []]
        ids = {b.id for b in db.session.query(BoqItem).filter(func.lower(BoqItem.name).in_(keys)).all()} if keys else set()
        had = current.get(s['name'].lower())
        out.append({'name': s['name'], 'lines': ids | (had['lines'] if had else set()),
                    'options': [(o['name'], o.get('amount') if o.get('amount') else o.get('extra', 0),
                                 'amt' if o.get('amount') else 'pct') for o in s['options']]})
    by_name = {o['name'].lower(): o for o in out}
    return save_sections([by_name.get(s['name'].lower()) or _as_input(s) for s in all_sections()]
                         + [o for o in out if o['name'].lower() not in current])
