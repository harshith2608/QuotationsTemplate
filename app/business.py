"""What kind of business this is (interiors, uPVC, tiles, construction…) and the words and examples that fit it.

The kind comes from "What do you mostly do?" in the guided first setup (welcome.KINDS), or from the trial form when
the trial was set up from it (KEY, set by the console). A business with neither, which is every business from before
there was a choice, is treated as interiors: what it sees doesn't change.

profile() gives each page what it needs: the word for a quotation's sections (Room, or Area for work that isn't done
room by room), an item and a room to use as examples, typical items for the AI helpers, and so on. Interiors keeps the
examples it always had.
"""
from flask import g, has_app_context

KEY = 'business_kind'
# Which kinds new businesses can choose (the website's trial form, the guided setup): the console's Features page.
# A JSON list of kinds, in console_state for the shared app and in the website's app_settings (kept on the demo's
# nightly reset). Interiors and "Something else" are always offered; until the console says, the ones offered before.
KINDS_KEY = 'business_kinds'
ALWAYS_OFFERED = ('interiors', 'other')
OFFERED_BEFORE = ('interiors', 'furniture', 'upvc', 'glass', 'other')
INTERIORS = ('interiors', 'turnkey', 'furniture')     # the app's own words (wardrobe, plywood, BHK) fit these
BY_ROOM = INTERIORS + ('upvc', 'glass', 'tiles', 'painting', 'ceiling', 'curtains')   # work done room by room

# kind: (a section to use as an example, more sections to suggest when not by room, what a customer might ask for,
#        a change a customer might ask for, what's often missed: for the AI check)
EXAMPLES = {
    'interiors': ('Living Room', [], '3 BHK. Wardrobes with lofts in both bedrooms, TV unit, L-shaped kitchen, false '
                  'ceiling in hall.', 'Please change the wardrobe to laminate and add a study table.',
                  'a kitchen with cabinets but no hob, chimney or drawers; wardrobes with lofts in one bedroom and not '
                  'the other'),
    'turnkey': ('Living Room', [], '2 BHK renovation. New flooring in hall and bedrooms, bathroom tiling, wardrobes in '
                'both bedrooms, false ceiling and painting.', 'Please add the balcony flooring and remove the false '
                'ceiling in the bedroom.', 'tiling with no waterproofing in a bathroom; new rooms with no electrical '
                'points; painting missing where the walls are being redone'),
    'furniture': ('Bedroom', [], 'Queen bed with storage, 2 door wardrobe, study table and a 6 seater dining table.',
                  'Please make the wardrobe 3 doors and add a dressing table.',
                  'a wardrobe with no loft; a bed with no mattress or storage mentioned; doors without hardware'),
    'upvc': ('Hall', [], 'Hall: 2 sliding windows 6x4 with mesh. Bedrooms: 3 casement windows 4x4. Kitchen ventilator.',
             'Please make the bedroom windows 3 track with mesh.',
             'windows with no mosquito mesh where the others have it; a sliding door with no lock; old frames not '
             'removed'),
    'glass': ('Bathroom', [], 'Shower partition 6x7, glass railing 20 rft on the balcony, 2 mirrors 4x3.',
              'Please use 12 mm toughened glass for the railing.',
              'glass thickness not stated; a shower partition with no fittings; railing with no handrail'),
    'tiles': ('Hall', [], 'Hall and 2 bedrooms 2x2 vitrified, about 900 sqft. Kitchen wall tiles 60 sqft, skirting.',
              'Please quote 4x2 tiles for the hall instead of 2x2.',
              'flooring with no skirting; old tiles not removed; bathrooms with no waterproofing'),
    'construction': ('Ground Floor', ['Ground Floor', 'First Floor', 'Second Floor', 'Terrace', 'Staircase',
                     'Compound', 'Parking', 'Site'], 'G+1 house, 1200 sqft per floor, with compound wall 120 rft and '
                     'terrace waterproofing.', 'Please add a second floor and quote premium finishes.',
                     'a slab with no waterproofing; plastering missing for new brickwork; no electrical or plumbing '
                     'points'),
    'painting': ('Living Room', [], '3 BHK interior painting, about 3,500 sqft of walls and ceiling, and the main door '
                 'in PU.', 'Please quote premium emulsion for the hall.',
                 'walls with no putty or primer; ceilings left out; a terrace with no waterproofing'),
    'ceiling': ('Living Room', [], 'Gypsum false ceiling in hall 15x12 and both bedrooms 12x11, with cove lights.',
                'Please add the kitchen ceiling and 6 more light points.',
                'false ceiling with no light points or cove profile; no painting for a new ceiling'),
    'fabrication': ('Main Gate', ['Main Gate', 'Front', 'Terrace', 'Staircase', 'Balcony', 'Compound', 'Shed',
                    'Site'], 'MS main gate 12x6, 4 window grills 4x4, staircase railing 30 rft.',
                    'Please make the railing in SS 304.',
                    'a gate or grill with no primer and paint; railing with no handrail; no lock on a gate'),
    'curtains': ('Bedroom', [], 'Hall: 2 windows with eyelet curtains and track. Bedrooms: roller blinds 5x4.',
                 'Please change the hall curtains to blackout.',
                 'curtains with no track or rod; blinds with no fixing'),
    'other': ('Ground Floor', ['Ground Floor', 'First Floor', 'Front', 'Back', 'Terrace', 'Site'],
              'What the customer asked for, with the sizes or quantities.', 'Please add one more of the same.',
              'items with no quantity or size'),
}


def kind():
    """The business's kind (a welcome.KINDS key); 'interiors' when it never said."""
    if has_app_context() and '_business_kind' in g:
        return g._business_kind
    from . import welcome
    from .models import AppSetting
    try:
        found = (AppSetting.get(KEY) or '').strip() or welcome.state().get('kind') or ''
    except Exception:            # no database (a cold start): as before there was a choice
        return 'interiors'
    found = welcome.OLD_KINDS.get(found, found)
    found = found if found in welcome.KINDS else 'interiors'
    if has_app_context():
        g._business_kind = found
    return found


def set_kind(value):
    """Keep what they do (the guided setup's answer, or the trial form's)."""
    from . import welcome
    from .models import AppSetting
    value = welcome.OLD_KINDS.get(value, value)
    if value in welcome.KINDS and AppSetting.get(KEY) != value:
        AppSetting.set(KEY, value)
    if has_app_context():
        g.pop('_business_kind', None)
        g.pop('_business_profile', None)


def is_interiors():
    return kind() in INTERIORS


def typical_items(k=None):
    """[(name, unit, description)] the guided setup offers this kind of business."""
    from . import welcome
    return [(r[0], r[1], r[3]) for r in welcome.TYPICAL.get(k or kind(), []) if r[0] != '#']


def profile():
    """Words and examples for this business's pages (cached for the request)."""
    if has_app_context() and '_business_profile' in g:
        return g._business_profile
    from . import welcome
    k = kind()
    section_example, sections, draft, change, missed = EXAMPLES[k]
    items = typical_items(k)
    by_room = k in BY_ROOM
    if k in INTERIORS:          # as it always was
        item, description, item_list = ('Wardrobe', 'Making safety door with block board, both side laminate finish, '
                                        'including safety grill', 'wardrobe, false ceiling, side table')
    elif items:
        item, description = items[0][0], items[0][2]
        item_list = ', '.join(n.lower() for n, _, _ in items[:3])
    else:
        item, description, item_list = 'Your item', 'What is included, size, finish…', 'each thing you quote'
    out = {
        'kind': k, 'label': welcome.KINDS[k], 'interiors': k in INTERIORS, 'by_room': by_room,
        'section': 'Room' if by_room else 'Area', 'sections': 'Rooms' if by_room else 'Areas',
        'section_example': section_example, 'section_suggestions': sections,
        'item_example': item, 'description_example': description, 'items_example': item_list,
        'draft_example': draft, 'change_example': change, 'often_missed': missed,
        'typical_names': [n for n, _, _ in items],
        'thank_you': 'We look forward to transforming your space' if k in INTERIORS   # + '!' or '.'
        else 'We look forward to working with you',
    }
    if has_app_context():
        g._business_profile = out
    return out


def room_names():
    """Suggestions for a section's name: the business's room list (Admin), less the built-in interiors rooms for a
    business that doesn't work room by room, which gets its own (Ground Floor, Terrace…)."""
    from . import catalog
    from .models import MasterRoom
    names = [r.name for r in MasterRoom.query.order_by(MasterRoom.name).all()]
    p = profile()
    if p['by_room']:
        return names
    return list(dict.fromkeys([n for n in names if n not in catalog.DEFAULT_ROOMS] + p['section_suggestions']))


def item_names():
    """Suggestions for an item's name: the business's item list, less the built-in interiors items (wardrobe, TV
    unit…) for other businesses, which get their own saved lines instead."""
    from . import boq, catalog
    from .models import BoqItem, MasterItem
    names = [i.name for i in MasterItem.query.order_by(MasterItem.name).all()]
    if is_interiors():
        return names
    own = [b.name for b in BoqItem.query.order_by(BoqItem.name)] if boq.ready() else []
    return list(dict.fromkeys([n for n in names if n not in catalog.DEFAULT_ITEMS] + own))


def parse_kinds(raw):
    """The kinds in a stored KINDS_KEY value, or None when there is none."""
    import json
    from . import welcome
    if raw is None:
        return None
    try:
        found = json.loads(raw)
    except ValueError:
        return None
    return [k for k in welcome.KINDS if k in found] if isinstance(found, list) else None


def kinds_offered():
    """The kinds a new business can choose, in welcome.KINDS order ('other' last)."""
    from . import platform_switch, tenancy, welcome
    from .models import AppSetting
    try:
        raw = platform_switch.value(KINDS_KEY) if tenancy.tenant_mode() else AppSetting.get(KINDS_KEY)
    except Exception:
        raw = None
    on = parse_kinds(raw)
    on = set(OFFERED_BEFORE if on is None else on) | set(ALWAYS_OFFERED)
    return [k for k in welcome.KINDS if k in on]


def offered(value):
    """A trial form's business type (marketing.BUSINESS_TYPES) is offered now."""
    from . import welcome
    return welcome.OLD_KINDS.get(value, value) in kinds_offered()
