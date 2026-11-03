"""The guided first setup ("Let's set up your QuoteRoom"): what a new business's admin sees on their first sign-in,
instead of the setup guide. One question a page, each with "Skip for now", and "I'll explore on my own" to leave:

  1. business  the company name and phone (filled in from the trial request), the logo if they have it
  2. units     how they measure: feet & inches, mm, cm or inches, and rates per sqft or per sq m
  3. rates     "Do you have an old quotation or rate Excel ready?" yes: Bring your old quotation (app/ai_import.py,
               when it's on), which then comes back here; no: what they mostly do → a short list of typical items
               and rates (TYPICAL, priced by item). Either way: "These are your rates", to check and change.
  4. quote     their first quotation: the new quotation form (or, set up from an old quotation, that quotation
               rebuilt here), with a strip on top saying what to do
  5. send      the saved quotation: its PDF and Send on WhatsApp
  then done    "When you have time": payment details, terms & conditions, invoices, team (the setup guide's steps)

Steps 1–3 are their own pages (templates/welcome/); 4 and 5 are the app's own pages with the tour's strip on top
(templates/partials/_welcome_bar.html), so they learn the real screens. What's done here also completes the setup
guide's steps. Progress is one app_settings row (JSON): no database update. The console shows where a trial stopped.
"""
import json
from datetime import datetime

KEY = 'welcome_tour'
SESSION_KEY = 'welcome_tour'     # set while under way, so other pages don't read the setting to know
STEPS = [('business', 'Your business'), ('units', 'How you measure'), ('rates', 'Your rates'),
         ('quote', 'Your first quotation'), ('send', 'See it and send it')]
ORDER = [k for k, _ in STEPS]
TITLES = dict(STEPS)

KINDS = {'interiors': 'Full interiors', 'kitchens': 'Modular kitchens & wardrobes', 'turnkey': 'Turnkey & civil work',
         'other': 'Something else'}

# Typical items and rates (per sqft, rft, nos or point) for a business with no file: a starting point they change.
# Not any customer's numbers. ('#', group) starts a group.
_WOOD = [
    ('#', 'Bedrooms'),
    ('Wardrobe', 'sqft', 1600, 'Carcass in BWR plywood, laminate outside, liner inside, soft-close hinges'),
    ('Loft', 'sqft', 1100, 'Above the wardrobe, same finish'),
    ('Dressing Table', 'sqft', 1500, 'With mirror and drawers'),
    ('Study Table', 'sqft', 1400, 'With drawer and open shelves'),
    ('Bed with Storage', 'nos', 45000, 'Queen size, hydraulic storage, headboard'),
    ('#', 'Living & Dining'),
    ('TV Unit', 'sqft', 1400, 'Wall unit with back panel and storage'),
    ('Crockery Unit', 'sqft', 1600, 'Glass shutters, profile light'),
    ('Shoe Rack', 'sqft', 1300, 'With seating top'),
    ('Pooja Unit', 'sqft', 1800, 'With back panel and drawers'),
]
_KITCHEN = [
    ('#', 'Kitchen'),
    ('Base Cabinet', 'sqft', 1700, 'BWP plywood carcass, laminate shutters, soft-close hinges'),
    ('Overhead Cabinet', 'sqft', 1500, 'Same finish as the base cabinets'),
    ('Tall Unit', 'sqft', 1800, 'Pantry or appliance unit'),
    ('Kitchen Loft', 'sqft', 1100, 'Above the overhead cabinets'),
    ('Tandem Drawer', 'nos', 6500, 'Soft-close, full extension'),
    ('Magic Corner', 'nos', 18000, 'For the corner base cabinet'),
]
_SERVICES = [
    ('#', 'Services'),
    ('False Ceiling', 'sqft', 120, 'Gypsum, with framework, as per design'),
    ('Painting', 'sqft', 28, 'Putty, primer and two coats of emulsion'),
    ('Electrical Point', 'point', 850, 'Wiring with conduit; switches and plates extra'),
]
TYPICAL = {
    'interiors': _WOOD + _KITCHEN[:5] + _SERVICES[:2],
    'kitchens': _KITCHEN + [
        ('Pull-out Basket', 'nos', 4500, 'Stainless steel, soft-close'),
        ('Countertop (Granite)', 'rft', 450, 'Black granite, 2 ft deep, with edge polish'),
        ('#', 'Wardrobes'),
        ('Wardrobe (Hinged)', 'sqft', 1600, 'Laminate outside, liner inside, soft-close hinges'),
        ('Wardrobe (Sliding)', 'sqft', 1800, 'Sliding shutters with soft-close channel'),
        ('Loft', 'sqft', 1100, 'Above the wardrobe, same finish'),
    ],
    'turnkey': [('#', 'Civil'),
                ('Demolition & Debris', 'sqft', 40, 'Breaking, removal and disposal'),
                ('Flooring (Vitrified Tiles)', 'sqft', 120, 'Laying with tile adhesive, tiles extra'),
                ('Wall Tiling', 'sqft', 140, 'Bathroom and kitchen walls, laying only'),
                ('Plumbing Point', 'point', 1500, 'CPVC lines, fittings extra')]
               + _SERVICES + _WOOD[:3] + _WOOD[6:8] + _KITCHEN[:3],
    'other': [],
}


def _state():
    from .models import AppSetting
    try:
        data = json.loads(AppSetting.get(KEY, '') or '{}')
    except ValueError:
        data = {}
    return data if isinstance(data, dict) else {}


def _store(data):
    from .models import AppSetting
    AppSetting.set(KEY, json.dumps(data, sort_keys=True))


def state():
    return _state()


def active():
    """The tour is under way (started and not finished or left)."""
    s = _state()
    return bool(s.get('step')) and not s.get('finished')


def step():
    return _state().get('step') if active() else None


def number(key):
    return ORDER.index(key) + 1 if key in ORDER else None


def start():
    """Begin (or begin again) at the first step. The setup guide then doesn't open by itself."""
    from . import setup_guide
    s = _state()
    s.update(step=ORDER[0], finished=None, skipped=[], started=s.get('started') or datetime.utcnow().isoformat(timespec='seconds'))
    _store(s)
    setup_guide.note_seen()
    _flag(True)


def _flag(on):
    from flask import has_request_context, session
    if has_request_context():
        if on:
            session[SESSION_KEY] = True
        else:
            session.pop(SESSION_KEY, None)


def note_sign_in():
    """At sign-in: the strip shows on this browser too if the tour is under way."""
    _flag(active())


def start_on_first_login():
    """A new business's admin on their first sign-in (as the setup guide decides: no quotations yet, the guide never
    seen, not the demo): start the tour. True when started."""
    from . import setup_guide
    if _state().get('step') or not setup_guide.open_on_first_login():
        return False
    start()
    return True


def go_to(key):
    s = _state()
    if key in ORDER and not s.get('finished'):
        s['step'] = key
        _store(s)


def advance(from_key, skipped=False):
    """From this step to the next one (skipped: "Skip for now", remembered for the last page). Returns the new step,
    or None when that was the last (the tour is then done)."""
    s = _state()
    if from_key not in ORDER:
        return s.get('step')
    if skipped:
        s['skipped'] = sorted(set(s.get('skipped') or []) | {from_key})
    i = ORDER.index(from_key)
    if i + 1 < len(ORDER):
        s['step'] = ORDER[i + 1]
    else:
        s['step'], s['finished'] = 'done', 'done'
        _flag(False)
    _store(s)
    return None if s.get('finished') else s['step']


def finish(how='done'):
    """'done' (the last step) or 'exit' ("I'll explore on my own")."""
    s = _state()
    s['finished'] = how
    if how == 'done':
        s['step'] = 'done'
    _store(s)
    _flag(False)


def remember_project(project_id):
    """The quotation rebuilt from their old one (Bring your old quotation): step 4 opens it."""
    s = _state()
    s['project'] = project_id
    _store(s)


def add_typical(kind):
    """Price by item, with the typical items for this kind of business when they have no items of their own yet
    (in their own units). Returns how many were added."""
    from sqlalchemy import func
    from . import boq, db
    from .models import BoqItem
    added = 0
    if BoqItem.query.filter(BoqItem.unit != boq.LUMP_SUM).first() is None:
        from . import units
        metric = units.area_unit() == 'sqm'
        have = {n for (n,) in db.session.query(func.lower(BoqItem.name)).all()}
        group = 'Other'
        for row in TYPICAL.get(kind, []):
            if row[0] == '#':
                group = row[1]
                continue
            name, unit, rate, description = row
            if metric and unit == 'sqft':
                unit, rate = 'sq m', boq._metric_rate(rate, boq.AREA_UNITS['sq m'])
            elif metric and unit == 'rft':
                unit, rate = 'rmt', boq._metric_rate(rate, boq.LENGTH_UNITS['rmt'])
            if name.lower() in have:
                continue
            db.session.add(BoqItem(name=name, unit=unit, rate=rate, description=description, category=group))
            have.add(name.lower())
            added += 1
        db.session.flush()
    boq.set_pricing(boq.ITEM, starter=False)
    return added


def bar(endpoint, view_args):
    """The strip on the app's own pages while the tour is under way: {'key', 'number', 'total', 'title', 'hint',
    'next' (button label, or None), 'skip'}. None on the tour's own pages and when it isn't under way."""
    from flask import session
    if not endpoint or endpoint.startswith('welcome.') or not session.get(SESSION_KEY):
        return None
    if not active():
        _flag(False)
        return None
    key = _state().get('step')
    hint, nxt, skip, back = None, 'Next', True, None
    if key in ('quote', 'send') and endpoint == 'projects.view_project':
        key, nxt, skip = 'send', 'Finish', False
        hint = ('This is your quotation. Tap <strong>Quotation PDF</strong> to see what your customer gets, or '
                '<strong>Send on WhatsApp</strong> (further down).')
    elif key == 'quote' and endpoint == 'projects.create_project':
        hint = 'Add a room, add an item, type its size, then tap <strong>Save quotation</strong>.'
        nxt, back = None, 'welcome.check'
    elif key == 'rates' and endpoint == 'admin.ai_import':
        from flask import request
        hint = ('Check the lines we read, then set up your app with them.' if request.method == 'POST' else
                'Upload your file. You check every line before anything is saved.')
        nxt, back = None, 'welcome.rates'
    elif key == 'rates' and endpoint == 'admin.rates':
        hint = 'These are your rates. Change anything that\'s different, tap <strong>Save</strong>, then Next.'
        back = 'welcome.rates'
    else:
        return {'key': key, 'number': number(key), 'total': len(ORDER), 'title': TITLES.get(key, ''),
                'hint': None, 'next': None, 'skip': False, 'away': True, 'back': None}
    return {'key': key, 'number': number(key), 'total': len(ORDER), 'title': TITLES[key], 'hint': hint, 'next': nxt,
            'skip': skip, 'away': False, 'back': back}


def console_text(raw):
    """Where a trial is in the tour, for the console: from the app_settings value."""
    try:
        s = json.loads(raw or '{}')
    except ValueError:
        return ''
    if not isinstance(s, dict) or not s.get('step'):
        return ''
    skipped = [TITLES.get(k, k).lower() for k in s.get('skipped') or []]
    tail = f' (skipped {", ".join(skipped)})' if skipped else ''
    if s.get('finished') == 'done':
        return 'finished' + tail
    where = TITLES.get(s['step'], s['step']).lower()
    if s.get('finished') == 'exit':
        return f'left at step {number(s["step"]) or "?"}, {where}' + tail
    return f'at step {number(s["step"]) or "?"}, {where}' + tail
