"""The guided first setup ("Let's set up your QuoteRoom"): what a new business's admin sees on their first sign-in,
instead of the setup guide. One question a page, each with "Skip for now", and "I'll explore on my own" to leave:

  1. business  the company name and phone (filled in from the trial request), the logo if they have it
  2. units     how they measure: feet & inches, mm, cm or inches, and rates per sqft or per sq m
  3. rates     what they mostly do (KINDS); interiors and turnkey firms are then asked "Do you have an old
               quotation or rate Excel ready?" (Bring your old quotation, app/ai_import.py, when it's on: it then
               comes back here). Every other kind, and a "no", is shown a short list of typical items and rates
               (TYPICAL) on "These are your rates", in sections, to check and change. Choosing a business writes
               nothing: the items are saved (priced by item) only with Save my rates.
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
STEPS = [('business', 'Your business'), ('units', 'How you measure'), ('pricing', 'How you price'), ('rates', 'Your rates'),
         ('quote', 'Your first quotation'), ('send', 'See it and send it')]
ORDER = [k for k, _ in STEPS]
TITLES = dict(STEPS)

KINDS = {'interiors': 'Interiors, modular kitchens & wardrobes', 'turnkey': 'Turnkey interiors & civil',
         'furniture': 'Furniture & carpentry', 'upvc': 'uPVC windows & doors', 'glass': 'Glass & aluminium',
         'tiles': 'Tiles, flooring & granite', 'construction': 'Construction', 'painting': 'Painting & waterproofing',
         'ceiling': 'False ceiling & POP', 'fabrication': 'Steel fabrication & grills',
         'curtains': 'Curtains, blinds & wallpaper', 'other': 'Something else'}
ICONS = {'interiors': 'house-door', 'turnkey': 'buildings', 'furniture': 'lamp',
         'upvc': 'window', 'glass': 'window-split', 'tiles': 'grid', 'construction': 'bricks', 'painting': 'paint-bucket',
         'ceiling': 'lightbulb', 'fabrication': 'tools', 'curtains': 'border-style', 'other': 'three-dots'}
# Asked for an old quotation or rate Excel: the kinds that usually have one. The others start from typical items.
FILE_KINDS = ('interiors', 'turnkey')
OLD_KINDS = {'kitchens': 'interiors'}      # kinds offered before, as they're now named

# Typical items and rates (per sqft, rft, nos or point) for a business with no file: a starting point they change.
# Not any customer's numbers. ('#', group) starts a group.
_WOOD = [
    ('#', 'Bedrooms'),
    ('Wardrobe', 'sqft', 1600, 'Carcass in BWR plywood, laminate outside, liner inside, soft-close hinges'),
    ('Sliding Wardrobe', 'sqft', 1800, 'Sliding shutters with soft-close channel'),
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
    'interiors': _WOOD + _KITCHEN + [
        ('Pull-out Basket', 'nos', 4500, 'Stainless steel, soft-close'),
        ('Countertop (Granite)', 'rft', 450, 'Black granite, 2 ft deep, with edge polish'),
    ] + _SERVICES[:2],
    'turnkey': [('#', 'Civil'),
                ('Demolition & Debris', 'sqft', 40, 'Breaking, removal and disposal'),
                ('Flooring (Vitrified Tiles)', 'sqft', 120, 'Laying with tile adhesive, tiles extra'),
                ('Wall Tiling', 'sqft', 140, 'Bathroom and kitchen walls, laying only'),
                ('Plumbing Point', 'point', 1500, 'CPVC lines, fittings extra')]
               + _SERVICES + _WOOD[:2] + _WOOD[3:4] + _WOOD[7:9] + _KITCHEN[:3],
    'furniture': [('#', 'Furniture'),
                  ('Wardrobe', 'sqft', 1400, 'Plywood with laminate, soft-close hinges'),
                  ('Bed with Storage', 'nos', 38000, 'Queen size, hydraulic storage'),
                  ('TV Unit', 'sqft', 1200, 'With back panel and storage'),
                  ('Study Table', 'sqft', 1200, 'With drawer'),
                  ('Shoe Rack', 'sqft', 1100, 'With seating top'),
                  ('Dining Table (6 seater)', 'nos', 32000, 'Solid wood top'),
                  ('Sofa (3 seater)', 'nos', 42000, 'Fabric, with cushions'),
                  ('Wooden Door', 'nos', 14000, 'Flush door with frame and laminate'),
                  ('Polish (PU)', 'sqft', 180, 'PU polish on wood')],
    'upvc': [('#', 'Windows'),
             ('Sliding Window (2 track)', 'sqft', 550, 'uPVC profile, 5 mm clear glass'),
             ('Sliding Window (3 track with mesh)', 'sqft', 650, 'With sliding mosquito mesh'),
             ('Casement Window', 'sqft', 700, 'Openable, multi-point locking'),
             ('Fixed Window', 'sqft', 450, 'Fixed glass'),
             ('Ventilator', 'sqft', 600, 'Bathroom ventilator with louvres'),
             ('#', 'Doors'),
             ('Sliding Door', 'sqft', 650, 'uPVC profile, toughened glass'),
             ('Casement Door', 'sqft', 800, 'Openable, with handle and lock'),
             ('#', 'Extras'),
             ('Toughened Glass (upgrade)', 'sqft', 90, 'In place of clear glass'),
             ('Safety Grill', 'sqft', 150, 'MS grill, painted'),
             ('Old Frame Removal', 'nos', 500, 'Per window, with debris removal')],
    'glass': [('#', 'Aluminium'),
              ('Aluminium Sliding Window', 'sqft', 450, 'Section with 5 mm glass'),
              ('Aluminium Partition', 'sqft', 350, 'Office partition with glass'),
              ('ACP Cladding', 'sqft', 260, '4 mm ACP sheet with framework'),
              ('#', 'Glass'),
              ('Toughened Glass 12 mm', 'sqft', 280, 'With fittings'),
              ('Shower Partition', 'sqft', 650, '10 mm toughened glass with SS fittings'),
              ('Glass Railing', 'rft', 1800, '12 mm toughened glass with SS clamps'),
              ('Mirror', 'sqft', 180, '5 mm mirror with polished edges'),
              ('Spider Glazing', 'sqft', 900, 'Structural glazing with spider fittings')],
    'tiles': [('#', 'Flooring'),
              ('Floor Tiles (2 x 2, with laying)', 'sqft', 110, 'Vitrified tiles with adhesive and grout'),
              ('Large Tiles (4 x 2, with laying)', 'sqft', 160, 'Vitrified tiles with adhesive and grout'),
              ('Granite Flooring', 'sqft', 180, 'With laying and polish'),
              ('Marble Flooring', 'sqft', 350, 'With laying and polish'),
              ('Wooden Flooring', 'sqft', 160, 'Laminate flooring with underlay'),
              ('Skirting', 'rft', 60, 'Tile skirting, 4 inch'),
              ('#', 'Walls & others'),
              ('Wall Tiles (with laying)', 'sqft', 120, 'Bathroom and kitchen walls'),
              ('Granite Kitchen Platform', 'rft', 450, '2 ft deep, with edge polish'),
              ('Epoxy Grouting', 'sqft', 25, 'In place of cement grout'),
              ('Old Tile Removal', 'sqft', 20, 'Breaking and debris removal')],
    'construction': [('#', 'Construction'),
                     ('Building Construction (Standard)', 'sqft', 2000, 'Built-up area, with materials and labour'),
                     ('Building Construction (Premium)', 'sqft', 2500, 'Built-up area, premium finishes'),
                     ('RCC Slab', 'sqft', 280, 'With steel and shuttering'),
                     ('Brickwork (9 inch)', 'sqft', 140, 'Red brick or block wall'),
                     ('Brickwork (4.5 inch)', 'sqft', 75, 'Partition wall'),
                     ('Plastering (inside)', 'sqft', 35, '12 mm cement plaster'),
                     ('Plastering (outside)', 'sqft', 45, '20 mm cement plaster'),
                     ('Compound Wall', 'rft', 1800, '5 ft high, with foundation'),
                     ('#', 'Finishing'),
                     ('Flooring (Vitrified Tiles)', 'sqft', 120, 'With laying'),
                     ('Waterproofing', 'sqft', 45, 'Terrace and bathrooms'),
                     ('Electrical Point', 'point', 850, 'Wiring with conduit'),
                     ('Plumbing Point', 'point', 1500, 'CPVC lines, fittings extra'),
                     ('Painting', 'sqft', 28, 'Putty, primer and two coats')],
    'painting': [('#', 'Painting'),
                 ('Interior Emulsion', 'sqft', 22, 'Putty, primer and two coats'),
                 ('Premium Emulsion', 'sqft', 30, 'Washable, two coats'),
                 ('Exterior Emulsion', 'sqft', 28, 'Weatherproof, two coats'),
                 ('Texture Paint', 'sqft', 85, 'Designer texture, one wall'),
                 ('Enamel on Grills & Doors', 'sqft', 25, 'Primer and two coats'),
                 ('Wood Polish (PU)', 'sqft', 180, 'PU polish on doors and furniture'),
                 ('#', 'Waterproofing'),
                 ('Terrace Waterproofing', 'sqft', 55, 'Membrane or chemical coating'),
                 ('Bathroom Waterproofing', 'sqft', 65, 'Before tiling')],
    'ceiling': [('#', 'False ceiling'),
                ('Gypsum False Ceiling', 'sqft', 95, 'Gypsum board with framework'),
                ('POP False Ceiling', 'sqft', 110, 'POP with framework'),
                ('Grid Ceiling (2 x 2)', 'sqft', 75, 'Mineral fibre tiles'),
                ('PVC Ceiling', 'sqft', 120, 'PVC panels with framework'),
                ('Wooden Ceiling Panels', 'sqft', 350, 'Veneer or laminate panels'),
                ('#', 'Lights & finishing'),
                ('Cove Light Profile', 'rft', 120, 'With LED strip'),
                ('Ceiling Light Point', 'point', 350, 'Wiring for one light'),
                ('Ceiling Painting', 'sqft', 18, 'Primer and two coats')],
    'fabrication': [('#', 'Fabrication'),
                    ('MS Window Grill', 'sqft', 180, 'With primer and enamel'),
                    ('MS Gate', 'sqft', 450, 'With primer and enamel'),
                    ('MS Railing', 'rft', 650, 'Staircase or balcony'),
                    ('SS Railing', 'rft', 1400, 'SS 304 with glass or pipes'),
                    ('Collapsible Gate', 'sqft', 320, 'With lock'),
                    ('Rolling Shutter', 'sqft', 280, 'Galvanised, with lock'),
                    ('Roofing Shed', 'sqft', 160, 'MS structure with roofing sheets')],
    'curtains': [('#', 'Curtains'),
                 ('Curtain Stitching', 'nos', 450, 'Per panel, eyelet or pleated'),
                 ('Curtain Track', 'rft', 120, 'With installation'),
                 ('Curtain Rod', 'rft', 150, 'With brackets and installation'),
                 ('#', 'Blinds'),
                 ('Roller Blinds', 'sqft', 160, 'Blackout or sunscreen fabric'),
                 ('Zebra Blinds', 'sqft', 220, 'Day and night'),
                 ('Roman Blinds', 'sqft', 260, 'Fabric blinds'),
                 ('Wooden Blinds', 'sqft', 380, 'Venetian wooden slats'),
                 ('#', 'Others'),
                 ('Wallpaper (with fixing)', 'sqft', 90, 'Imported wallpaper'),
                 ('Pleated Mosquito Mesh', 'sqft', 140, 'For windows and doors')],
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
    """The tour is on this step (stored only when it changes)."""
    s = _state()
    if key in ORDER and not s.get('finished') and s.get('step') != key:
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


def set_kind(kind):
    """What they do, kept when their rates are saved (for the console)."""
    from . import business
    s = _state()
    if s.get('kind') != kind:
        s['kind'] = kind
        _store(s)
    business.set_kind(kind)


def set_pricing(mode):
    """How they price (step 3): by material or by item, as chosen; their rates step follows it."""
    s = _state()
    if s.get('pricing') != mode:
        s['pricing'] = mode
        _store(s)


def by_material():
    """Their rates are by material (a rate per sqft for each material and work type): chosen on How you price, or,
    when that was skipped, set up that way from their old quotation."""
    from . import boq, setup_guide
    chosen = _state().get('pricing')
    if chosen:
        return chosen == 'material'
    return not boq.enabled() and 'import' in (setup_guide._state().get('done') or [])


def pricing_examples(kind):
    """Two small quotations to choose between on How you price, in the business's units: by material (an interiors
    job: measured items at a rate per sqft for their material and work type, and a fitting) and by item (lines with
    a quantity and rate: their own kind's typical items)."""
    from . import boq, units
    def money(v):
        return f'₹{v:,.0f}'
    measured = [('Wardrobe', 7, 8, 'Laminates – Box Work', 1600), ('Loft', 7, 2, 'Laminates – Box Work', 1100),
                ('TV Unit', 6, 4, 'Acrylic – Frame Work', 1400)]
    by_material = [{'name': n, 'size': f'{units.length(l)} × {units.length(w)}', 'material': m,
                    'area': units.area(l * w, 1), 'rate': money(units.rate_value(r)) + units.rate_label(),
                    'amount': money(l * w * r)} for n, l, w, m, r in measured]
    by_material.append({'name': 'Tandem Drawer', 'size': '2 nos', 'material': 'Fitting', 'area': '',
                        'rate': money(4500), 'amount': money(9000)})
    rows, seen = [], set()
    for row in typical_rows(kind) or typical_rows('interiors'):   # the first item of each section, up to 3
        if row[0] not in seen and row[2] != boq.LUMP_SUM:
            seen.add(row[0])
            rows.append(row)
    for row in typical_rows(kind):                                   # one section only: its next items
        if len(rows) < 3 and row not in rows and row[2] != boq.LUMP_SUM:
            rows.append(row)
    sample = {'sqft': (56, 24, 30), 'sq m': (5.2, 2.2, 2.8), 'rft': (20, 12, 30), 'rmt': (6, 4, 9), 'nos': (2, 1, 4),
              'point': (12, 6, 20), 'set': (1, 1, 1)}
    by_item = []
    for n, (_, name, unit, rate, _) in enumerate(rows[:3]):
        qty = sample.get(unit, (1, 1, 1))[n]
        by_item.append({'name': name, 'qty': f'{qty:g}', 'unit': boq.unit_text(unit), 'rate': money(rate),
                        'amount': money(qty * rate)})
    if kind in ('interiors', 'turnkey'):
        by_item.append({'name': '3D Design', 'qty': '1', 'unit': 'LS', 'rate': money(45000), 'amount': money(45000)})
    return {'material': by_material, 'item': by_item}


def remember_project(project_id):
    """The quotation rebuilt from their old one (Bring your old quotation): step 4 opens it."""
    s = _state()
    s['project'] = project_id
    _store(s)


def note_added(ids):
    """Items saved on "These are your rates": made in this tour (see own_items)."""
    s = _state()
    s['added'] = sorted(set(s.get('added') or []) | {int(i) for i in ids})
    _store(s)


def own_items():
    """Their items from outside this tour (an old quotation read, a price list loaded from the console), not the ones
    saved on "These are your rates". Lump sums don't count."""
    from . import boq
    from .models import BoqItem
    ids = set(_state().get('added') or [])
    return [b for b in BoqItem.query.filter(BoqItem.unit != boq.LUMP_SUM).all() if b.id not in ids]


def typical_rows(kind):
    """[(section, name, unit, rate, description)]: the typical items for this kind of business, in their own units.
    Only shown on "These are your rates" until saved: nothing is written to their app by choosing a business."""
    from . import boq, units
    metric = units.area_unit() == 'sqm'
    out, group = [], 'Other'
    for row in TYPICAL.get(kind, []):
        if row[0] == '#':
            group = row[1]
            continue
        name, unit, rate, description = row
        if metric and unit == 'sqft':
            unit, rate = 'sq m', boq._metric_rate(rate, boq.AREA_UNITS['sq m'])
        elif metric and unit == 'rft':
            unit, rate = 'rmt', boq._metric_rate(rate, boq.LENGTH_UNITS['rmt'])
        out.append((group, name, unit, rate, description))
    return out


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
        from . import business
        hint = (f'Add a {business.profile()["section"].lower()}, add an item, type its size, then tap '
                '<strong>Save quotation</strong>.')
        nxt, back = None, 'welcome.materials' if by_material() else 'welcome.check'
    elif key == 'rates' and endpoint == 'admin.ai_import':
        from flask import request
        hint = ('Check the lines we read, then set up your app with them.' if request.method == 'POST' else
                'Upload your file. You check every line before anything is saved.')
        nxt, back = None, 'welcome.file'
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
    kind = OLD_KINDS.get(s.get('kind'), s.get('kind'))
    if kind in KINDS:
        tail += f' · {KINDS[kind].lower()}'
    if s.get('finished') == 'done':
        return 'finished' + tail
    where = TITLES.get(s['step'], s['step']).lower()
    if s.get('finished') == 'exit':
        return f'left at step {number(s["step"]) or "?"}, {where}' + tail
    return f'at step {number(s["step"]) or "?"}, {where}' + tail
