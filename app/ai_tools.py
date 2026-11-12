"""AI helpers on quotations (Claude Haiku, Anthropic API, ANTHROPIC_API_KEY), each switched on or off for every
business at once (app/platform_switch.py: the console's AI helpers card for the shared app; AI_DRAFT=1 / AI_CHECK=1
for a single-business deployment), and always off in the public demo:

  * draft  "Draft from a message": the customer's requirements (a WhatsApp message) or site-visit notes → the new
           quotation form filled in with the business's OWN items, materials, fittings and lines. The AI only picks
           items, sizes and quantities; every rate comes from the business's rates, never from the AI. Lines without a
           size or quantity are left for the business to fill in; the AI lists what to ask the customer.
  * photos the same from photos of handwritten site notes (up to PHOTO_MAX pages; its own switch, AI_PHOTOS=1, and
           its own limit, counted per photo). Each photo is turned upright, shrunk and re-encoded here (only pixels
           go to the AI), read and discarded: never stored. The draft shows them small, from the page, for checking.
  * check  "Check before sending": a quotation is checked by rules here (no size or quantity, a rate different from
           the business's own, a bigger discount than usual, the same line twice) and by the AI (what such rooms
           usually need, sizes that look wrong, an item in the wrong room, spelling the customer will read).

All three draw on one allowance of "AI uses" per business (a draft from a message, each photo and each check is one
use): ALLOWANCE['trial'] in all during the free trial, ALLOWANCE['standard'] a month on the 6- or 12-month plan and
ALLOWANCE['ai'] a month on a plan with AI (plan.AI_PLANS). On a paid plan the business can buy more (plan.ADDON:
ADDON_USES for AI_ADDON_PRICE, Your plan page), kept until used; the month's allowance is used first. Every call is
logged in public.ai_imports (kind 'draft' / 'photos' / 'check') with the AI import's, for the console.
"""
import json
from datetime import datetime
from statistics import median
from typing import List, Literal, Optional

from pydantic import BaseModel

from . import ai_import, db
from .numbers import inr

MODEL = ai_import.MODEL
TIMEOUT = 50
MESSAGE_MAX = 6000
FEATURES = {
    'draft': {'switch': 'ai_draft', 'env': 'AI_DRAFT', 'label': 'Draft from a message'},
    'check': {'switch': 'ai_check', 'env': 'AI_CHECK', 'label': 'Check before sending'},
    'photos': {'switch': 'ai_photos', 'env': 'AI_PHOTOS', 'label': 'Draft from photos of site notes', 'unit': 'photo'},
}
ALLOWANCE = {'trial': 10, 'standard': 20, 'ai': 100}    # AI uses: in all during the trial; a month on a plan
ALLOWANCE_ENV = {'trial': 'AI_USES_TRIAL', 'standard': 'AI_USES_MONTH', 'ai': 'AI_USES_MONTH_AI'}
USAGE_KEY, CREDITS_KEY = 'ai_uses', 'ai_credits'         # AppSetting: {'trial' or '2026-11': used}; bought uses left
PHOTO_MAX = 3
PHOTO_BYTES = 10 * 1024 * 1024          # each, as uploaded (shrunk on the phone first, so usually ~300 KB)
PHOTO_SIDE = 1568                       # px, the longest side: what the AI reads at full detail
RATE_DIFF = 0.15               # a line's rate this far from the business's own rate is pointed out
BIG_SIZE_FT = 20               # a measured item longer or wider than this is pointed out


class AIProblem(ValueError):
    """A message for the person using the helper (the limit is reached, the AI couldn't answer…)."""


# ── On / off, limits ─────────────────────────────────────────────────────────

def switched_on(feature):
    from . import platform_switch
    f = FEATURES[feature]
    return platform_switch.is_on(f['switch'], f['env'])


def available(feature):
    """Shown and usable in this app: switched on, the API key set, not the public demo."""
    from .demo import demo_enabled
    return not demo_enabled() and bool(ai_import.api_key()) and switched_on(feature)


def _usage():
    from .models import AppSetting
    try:
        return json.loads(AppSetting.get(USAGE_KEY) or '{}')
    except ValueError:
        return {}


def _credits():
    from .models import AppSetting
    try:
        return max(int(AppSetting.get(CREDITS_KEY) or 0), 0)
    except ValueError:
        return 0


def tier():
    """'trial', 'ai' (a plan with AI) or 'standard' (any other plan, or none: a business on its own app)."""
    from . import plan as plan_mod
    status = plan_mod.load_status()
    if status.has_limit and status.is_trial:
        return 'trial'
    return 'ai' if status.plan in plan_mod.AI_PLANS else 'standard'


def allowance(kind=None):
    import os
    kind = kind or tier()
    try:
        return max(int(os.environ.get(ALLOWANCE_ENV[kind]) or ALLOWANCE[kind]), 0)
    except ValueError:
        return ALLOWANCE[kind]


def pool():
    """This business's AI uses now: {'tier', 'allowance', 'used', 'credits', 'left', 'words', 'can_buy'}.
    can_buy: more can be bought here (a paid plan in the shared app, with the platform's Razorpay keys)."""
    from . import subscription
    kind = tier()
    period = 'trial' if kind == 'trial' else datetime.utcnow().strftime('%Y-%m')
    total, used, credits = allowance(kind), _usage().get(period, 0), (0 if kind == 'trial' else _credits())
    words = f'{total} during your free trial' if kind == 'trial' else f'{total} a month'
    if credits:
        words += f' + {credits} bought'
    return {'tier': kind, 'period': period, 'allowance': total, 'used': used, 'credits': credits,
            'left': max(total - used, 0) + credits, 'words': words,
            'can_buy': kind != 'trial' and subscription.enabled()}


def left(feature=None):
    """(AI uses left, the allowance's wording): one allowance for every helper."""
    p = pool()
    return p['left'], p['words']


def _count(feature, n=1):
    """Spend n uses: the month's (or the trial's) allowance first, then bought ones."""
    from .models import AppSetting
    p = pool()
    from_allowance = min(n, max(p['allowance'] - p['used'], 0))
    use = _usage()
    use[p['period']] = p['used'] + from_allowance
    AppSetting.set(USAGE_KEY, json.dumps(use))
    if n > from_allowance and p['tier'] != 'trial':
        AppSetting.set(CREDITS_KEY, str(max(p['credits'] - (n - from_allowance), 0)))
    db.session.commit()


def add_credits(n):
    """Bought AI uses (the add-on), added to what's left of earlier ones. Commits."""
    from .models import AppSetting
    AppSetting.set(CREDITS_KEY, str(_credits() + int(n)))
    db.session.commit()


def limit_text(feature=None):
    """Why the helper can't be used now, and what to do."""
    from . import plan as plan_mod, subscription
    p = pool()
    if p['tier'] == 'trial':
        return (f'You\'ve used the {p["allowance"]} AI uses in your free trial. Choose a plan to keep using the AI '
                'helpers' + (' (Your plan).' if subscription.enabled() else '.'))
    if not p['can_buy']:
        return f'You\'ve used this month\'s {p["allowance"]} AI uses. Message us on WhatsApp if you need more.'
    more = f'buy {plan_mod.ADDON_USES} more for ₹{inr(subscription.prices()[plan_mod.ADDON], 0)} on Your plan'
    if p['tier'] == 'standard':
        more += f', or move to a plan with AI ({allowance("ai")} a month)'
    return f'You\'ve used this month\'s {p["allowance"]} AI uses. To carry on now, {more}.'


def _ask(feature, prompt, schema, max_tokens, n=1):
    """Claude's answer as `schema`, within the limit (counted, n uses). prompt: text, or content blocks (photos and
    text). Raises AIProblem."""
    import anthropic
    have = left()[0]
    if have < n:
        if have > 0:
            raise AIProblem(f'You have {have} AI use{"" if have == 1 else "s"} left and each photo is one: choose '
                            f'{"one photo" if have == 1 else f"up to {have} photos"}.')
        raise AIProblem(limit_text())
    client = anthropic.Anthropic(api_key=ai_import.api_key(), timeout=TIMEOUT, max_retries=1)
    try:
        r = client.messages.parse(model=MODEL, max_tokens=max_tokens, output_format=schema,
                                  messages=[{'role': 'user', 'content': prompt}])
    except (anthropic.APIStatusError, anthropic.APIConnectionError) as exc:
        ai_import._log(feature, False, note=type(exc).__name__)
        raise AIProblem('The AI couldn\'t answer just now. Try again in a minute.') from exc
    if r.stop_reason in ('max_tokens', 'refusal') or r.parsed_output is None:
        ai_import._log(feature, False, tokens_in=r.usage.input_tokens, tokens_out=r.usage.output_tokens,
                       note=str(r.stop_reason))
        raise AIProblem('The AI couldn\'t work this one out. Try again, or with a shorter message.')
    _count(feature, n)
    return r.parsed_output, {'in': r.usage.input_tokens, 'out': r.usage.output_tokens}


def _money(value):
    return f'₹{inr(value, 0)}' if value == int(value) else f'₹{inr(value)}'


# ── Draft from a message ─────────────────────────────────────────────────────

class DraftItem(BaseModel):
    kind: Literal['measured', 'fitting', 'line']
    name: str
    length_ft: Optional[float] = None
    width_ft: Optional[float] = None
    count: int = 1
    material: str = ''
    work_type: str = ''
    quantity: Optional[float] = None
    unit: str = ''


class DraftRoom(BaseModel):
    name: str
    items: List[DraftItem]


class Draft(BaseModel):
    job_title: str
    rooms: List[DraftRoom]
    questions: List[str]
    customer_name: str = ''         # the customer's details, when the notes or the message give them
    customer_mobile: str = ''
    customer_email: str = ''
    customer_address: str = ''


DRAFT_PROMPT = """Below is what a customer wants done (often a WhatsApp message), or an interior designer's notes from a
site visit. Draft a quotation for this business, using only the business's own items listed below.
- rooms: in the order they come up, with clear names (Living Room, Master Bedroom, Kids Room, Kitchen…).
- items, by kind:
{measured}  fitting: one of the business's fittings and accessories, by its exact name, only when that fitting itself is asked
    for (a loft is furniture, not a loft lift-up mechanism); quantity if given, or 1 for "a" / "an" (a pantry
    pull-out).
  line: one of the business's own lines, by its exact name; quantity in its unit if given (sqft of false ceiling,
    number of electrical points…); for a line priced by area or length, length_ft and width_ft if the text gives them;
    material: the finish asked for, if the business lists finishes.
- sizes (length_ft, width_ft): in feet (1 ft = 12 in = 30.48 cm = 304.8 mm), ONLY when the text gives that item's
  size. A room's size ("kitchen 10x8", "hall 15x12") is not an item's size: leave the sizes null.
- name: the business's own name for the item when one matches ("Wardrobe" for "almirah"), else a short clear name.
- count: how many of the same item ("wardrobes in both bedrooms" = one in each room; "2 lofts" = count 2).
- Only what the text asks for. Don't add extras; if something is usually needed and not mentioned, ask instead.
- questions: up to 6 short questions the business can send the customer for what's missing (sizes, finishes, how
  many), in plain words. Never ask about the business's own terms or methods (work types, plywood, how it prices).
- job_title: 2–4 words ("3 BHK interiors", "Kitchen and wardrobes").
- customer_name, customer_mobile, customer_email, customer_address: the CUSTOMER's details when the text gives them
  (often at the top of the notes: "Mr. Sharma 98765 43210, Flat 402, Green Park"), exactly as written; otherwise
  empty. Never the business's own name or number, and never guess.
There are no prices in your answer: the business's own rates are used."""

# only for a business that prices by material (one pricing by item has no measured items)
MEASURED_RULE = """  measured: furniture priced by its area (wardrobes, kitchen cabinets, lofts, TV units, panelling, beds, study
    tables…). length_ft and width_ft: the two sizes it is priced by (the width and height of a wardrobe's front; the
    run and height of a kitchen cabinet). material and work_type: from the business's list, copied exactly as listed.
    The one asked for; when the text names none, the material in the list that best fits the item, in its most
    basic finish (usually laminate). A business's materials are often its items ("TV Unit Ledge box (Laminate
    Finish)", "Kitchen Laminate Finish - Wall Unit" for an overhead cabinet, "Panelling with Laminate Finish" for a
    head panel): pick the one for that item. '' only when nothing in the list fits it. When you chose the finish
    yourself, ask the customer which finish they want (one question for all of them). A finish asked for an item
    also goes on what belongs with it (a wardrobe's loft).
"""


PHOTO_PROMPT = """The requirements are in the photos: pages of handwritten notes from a site visit, read in order.
Designers write sizes like 10'6 x 2'9 (10 ft 6 in by 2 ft 9 in), 7x8, 2400 x 600 (mm) and use short forms: W/R or WR =
wardrobe, OHC or O/H = overhead cabinet, BC or base = base cabinet, TV = TV unit, L = loft, KT or K = kitchen, MBR =
master bedroom, BR = bedroom, LR or hall = living room, nos = number of pieces. Copy only what you can read: a size you
can't read clearly is left null and asked about. Crossed-out writing is ignored. Sketches only help to tell which room
an item is in."""


def prepare_photo(raw):
    """An uploaded photo → JPEG bytes the AI reads: turned upright, at most PHOTO_SIDE px, plain pixels only."""
    import io
    from PIL import Image, ImageOps
    if not raw:
        raise AIProblem('One of the photos was empty. Choose it again.')
    if len(raw) > PHOTO_BYTES:
        raise AIProblem('A photo is larger than 10 MB. Take it again or choose a smaller one.')
    try:
        img = Image.open(io.BytesIO(raw))
        img = ImageOps.exif_transpose(img)
        img = img.convert('RGB')
    except Exception:
        raise AIProblem('A photo couldn\'t be opened. Use a JPG or PNG photo of the notes.')
    if min(img.size) < 200:
        raise AIProblem('A photo is too small to read. Take it closer, filling the screen with the page.')
    img.thumbnail((PHOTO_SIDE, PHOTO_SIDE))
    out = io.BytesIO()
    img.save(out, 'JPEG', quality=85)
    return out.getvalue()


def _catalog():
    """The business's own items for the AI (text) and for matching its answer: {'text', 'by_item', 'fittings',
    'lines', 'combos', 'finishes'}."""
    from . import boq, finishes, materials as M
    from .models import MasterItem, PriceListItem
    by_item = boq.enabled()
    combos = M.combos()
    fittings = {p.name.lower(): p for p in PriceListItem.query.order_by(PriceListItem.name)}
    lines = {}
    if boq.ready():
        lines = {b['name'].lower(): b for b in boq.saved_lines(lump_only=not by_item)}
    out = []
    if not by_item and combos:
        mats = {}
        for wood, work, _ in combos:
            mats.setdefault(wood, []).append(work)
        out.append('Measured items are priced by material' + (' and work type' if any(any(w) for w in mats.values())
                                                               else '') + ': ' +
                   '; '.join(f'{m} ({", ".join(w for w in ws if w)})' if any(ws) else m for m, ws in mats.items()))
        names = [i.name for i in MasterItem.query.order_by(MasterItem.name).limit(200)]
        if names:
            out.append('Their usual measured item names: ' + ', '.join(names))
    else:
        out.append(_for_business(
            'This business prices by item: there are no measured items, everything is a line (furniture too). '
            'Use its own line when one matches. Anything asked for that has no line of its own (a wardrobe, '
            'loft, kitchen cabinet, TV unit…) still goes in as a line, with a short clear name and its usual '
            'unit (sqft for furniture priced by area, rft by length, nos by the piece): the business prices it.',
            [(' (furniture too)', ''), ('(a wardrobe, loft, kitchen cabinet, TV unit…)', '({example}…)'),
             ('sqft for furniture priced by area', 'sqft for work priced by area')]))
    opts = finishes.options() if by_item else []
    if opts:
        out.append('Finishes (put the one asked for in material): ' + ', '.join(o['name'] for o in opts))
    if fittings:
        out.append('Fittings and accessories (per piece): ' + ', '.join(p.name for p in fittings.values()))
    if lines:
        out.append('Their own lines: ' + '; '.join(f'{b["name"]} [{b["unit"]}]' for b in lines.values()))
    return {'text': '\n'.join(out), 'by_item': by_item, 'fittings': fittings, 'lines': lines, 'combos': combos,
            'finishes': {o['name'].lower(): o for o in opts}}


def _finish(material, cat):
    """The business's finish asked for ('laminate finish' → Laminate), or None."""
    key = ' '.join((material or '').lower().replace('finish', ' ').split())
    return (cat.get('finishes') or {}).get(key) if key else None


def _words(text):
    import re
    return re.sub(r'[^a-z0-9]+', ' ', (text or '').lower()).split()


def _match_material(material, work, cat_combos):
    """The business's (material, work type) for what the AI wrote, or None when it isn't clear. Exact first; then
    ignoring capitals and punctuation ('TV Unit Ledge Box - Acrylic Finish'); then the one material containing all
    its words ('acrylic tv unit')."""
    if not (material or '').strip():
        return None
    woods = list(dict.fromkeys(w for w, _, _ in cat_combos))
    want = ' '.join(_words(material))
    pick = next((w for w in woods if w.lower() == material.strip().lower()), None) \
        or next((w for w in woods if ' '.join(_words(w)) == want), None)
    if not pick:
        found = [w for w in woods if set(_words(material)) <= set(_words(w))]
        pick = found[0] if len(found) == 1 else None
    if not pick:
        return None
    works = [k for w, k, _ in cat_combos if w == pick]
    k = next((x for x in works if (x or '').lower() == (work or '').strip().lower()), works[0])
    return pick, k


def _size(value):
    return value if value is not None and 0 < value <= 100 else None


def to_form(draft, cat):
    """The AI's draft → (the quotation form's rooms at the business's rates, names with no rate, measured items whose
    material wasn't clear)."""
    from . import boq, materials as M
    combos = {(w.lower(), (k or '').lower()): (w, k) for w, k, _ in cat['combos']}
    by_wood = {}
    for w, k, _ in cat['combos']:
        by_wood.setdefault(w.lower(), (w, k))
    default = M.default_combo(cat['combos'])
    descs = M.descriptions()
    rooms, no_rate = [], []
    unclear = []                                        # measured items whose material wasn't clear: to check
    for room in draft.rooms:
        items = []
        for it in room.items:
            name = ' '.join(it.name.split())[:100]
            if not name:
                continue
            count = max(min(int(it.count or 1), 50), 1)
            length, width = _size(it.length_ft), _size(it.width_ft)
            line = cat['lines'].get(name.lower())
            fit = cat['fittings'].get(name.lower())
            if it.kind == 'line' or (line and not fit) or (cat['by_item'] and it.kind == 'measured'):
                unit = (line['unit'] if line else boq.clean_unit(it.unit)) or 'nos'
                qty = it.quantity if it.quantity and it.quantity > 0 else None
                row = {'type': 'boq', 'name': line['name'] if line else name, 'unit': unit,
                       'description': line['description'] if line else ''}
                mode = boq.size_mode(unit)
                if length and mode and (width or mode == 'length'):
                    qty = boq.quantity_from_size(unit, length, width or 0, count)
                    row.update(length=length, width=width or 0, count=count)
                elif qty is None and unit == boq.LUMP_SUM:
                    qty = 1
                elif qty is None and not mode and unit == 'nos':
                    qty = count                                     # "a TV unit", "wardrobes in both bedrooms"
                row['quantity'] = qty if qty is not None else ''
                fin = _finish(it.material, cat) if (line is None or line.get('finish')) else None
                if fin and fin['extra']:
                    row['finish'] = fin['name']                     # the base finish prints nothing extra
                if line:
                    row['unit_price'] = round(line['rate'] * (1 + (fin['extra'] if fin else 0) / 100), 2)
                else:
                    row['tbc'] = True
                    row['check'] = 'price'                          # the step-by-step checklist: type its price
                    no_rate.append(name)
                if qty is None:
                    row['pending'] = True
            elif it.kind == 'fitting' or fit:
                qty = it.quantity if it.quantity and it.quantity > 0 else None
                row = {'type': 'fixed', 'name': fit.name if fit else name, 'quantity': qty or 1,
                       'unit_price': fit.price if fit else 0, 'description': ''}
                if not fit:
                    row['check'] = 'price'
                    no_rate.append(name)
                if qty is None:
                    row['pending'] = True
            else:
                found = _match_material(it.material, it.work_type, cat['combos'])
                if not found and len(by_wood) > 1:
                    unclear.append(name)
                    checking = 'material'
                else:
                    checking = None
                wood, work = found or default
                row = {'type': 'measured', 'name': name, 'wood_type': wood, 'work_type': work, 'count': count,
                       'description': descs.get(wood, '')}
                if checking:
                    row['check'] = checking
                if length and width:
                    row.update(length=length, width=width)
                else:
                    row['pending'] = True
            items.append(row)
        if items:
            rooms.append({'name': ' '.join(room.name.split())[:100] or 'Room', 'items': items})
    return rooms, no_rate, unclear


def draft(message, photos=()):
    """A customer's message and/or photos of site notes (prepare_photo'd JPEG bytes) → {'rooms_json', 'title',
    'customer' (name, mobile, email, address found in them: filled into the form to check), 'questions', 'no_rate',
    'waiting'}. Photos count against their own limit, one use each. Raises AIProblem."""
    import base64
    message = (message or '').strip()
    photos = list(photos)[:PHOTO_MAX]
    if not photos and len(message) < 15:
        raise AIProblem('Paste the customer\'s message or your notes: which rooms and what they want in each.')
    cat = _catalog()
    rules = _for_business(DRAFT_PROMPT.replace('{measured}', '' if cat['by_item'] else MEASURED_RULE), DRAFT_OTHER)
    text_part = (f'{rules}\n\n' + (f'{PHOTO_PROMPT}\n\n' if photos else '') +
                 f'<business_items>\n{cat["text"]}\n</business_items>' +
                 (f'\n\n<requirements>\n{message[:MESSAGE_MAX]}\n</requirements>' if message else ''))
    feature = 'photos' if photos else 'draft'
    if photos:
        prompt = [{'type': 'image', 'source': {'type': 'base64', 'media_type': 'image/jpeg',
                                               'data': base64.b64encode(p).decode()}} for p in photos]
        prompt.append({'type': 'text', 'text': text_part})
    else:
        prompt = text_part
    answer, used = _ask(feature, prompt, Draft, 6000, n=max(len(photos), 1))
    rooms, no_rate, unclear = to_form(answer, cat)
    if not rooms:
        ai_import._log(feature, False, tokens_in=used['in'], tokens_out=used['out'], note='nothing to quote')
        raise AIProblem('No rooms or items could be read from that. ' + (
            'Take the photos closer, one page at a time, in good light.' if photos else
            'Mention the rooms and what goes in each.'))
    lines = sum(len(r['items']) for r in rooms)
    ai_import._log(feature, True, lines=lines, tokens_in=used['in'], tokens_out=used['out'])
    from .marketing import normalise_phone
    mobile = normalise_phone(answer.customer_mobile or '') or ''
    email = (answer.customer_email or '').strip()
    customer = {'customer_name': ' '.join((answer.customer_name or '').split())[:80],
                'mobile': mobile[2:] if mobile else '',                    # (the form's 10 digits)
                'email': email[:120] if '@' in email else '',
                'address': ' '.join((answer.customer_address or '').split())[:300]}
    return {'rooms_json': json.dumps(rooms), 'title': ' '.join(answer.job_title.split())[:60],
            'customer': {k: v for k, v in customer.items() if v},
            'questions': [q.strip() for q in answer.questions if q.strip()][:6], 'no_rate': no_rate[:10],
            'check_material': list(dict.fromkeys(unclear))[:10],
            'waiting': sum(1 for r in rooms for i in r['items'] if i.get('pending'))}


# ── Check before sending ─────────────────────────────────────────────────────

class Finding(BaseModel):
    level: Literal['fix', 'check', 'idea']
    where: str
    message: str


class Review(BaseModel):
    findings: List[Finding]


CHECK_PROMPT = """You are checking an interior quotation before the business sends it to its customer. Point out real
problems only:
- something rooms like these almost always need that is missing (a kitchen with cabinets but no hob, chimney or
  drawers; wardrobes with lofts in one bedroom and not the other) as 'idea', unless it is clearly a mistake;
- sizes that look wrong (a wardrobe 18 ft high, a TV unit 0.5 ft wide, length and width that look swapped);
- an item in the wrong room, the same item twice by mistake, one item in a different material from the rest of its
  room when that looks unintended;
- spelling mistakes in names the customer will read.
Don't comment on rates, prices, the discount or totals (checked separately), the problems already found (listed
below), or design and style. At most 8 findings; none when it looks right. level: 'fix' (very likely a mistake),
'check' (worth a look), 'idea' (could be added). where: the room and item ("Kitchen · Base Cabinet"). message: one
short, plain sentence for the business owner."""


# A business that isn't interiors (app/business.py): the prompts' interiors words and examples, replaced
DRAFT_OTHER = [
    ("or an interior designer's notes from a\nsite visit.", "or the business's notes from a site visit. The business "
     "does {label}.\n"),
    ('(Living Room, Master Bedroom, Kids Room, Kitchen…)', '({sections}), as the business would name them'),
    ('("Wardrobe" for "almirah")', '("{item}" for what the customer calls it)'),
    ('("wardrobes in both bedrooms" = one in each room; "2 lofts" = count 2)', '("2 windows in each bedroom" = 2 in '
     'each room)'),
    ('(work types, plywood, how it prices)', '(how it prices, its materials)'),
    ('("3 BHK interiors", "Kitchen and wardrobes")', '(for example "{example}")'),
]
CHECK_OTHER = [
    ('You are checking an interior quotation', 'You are checking a quotation from a business that does {label},'),
    ('(a kitchen with cabinets but no hob, chimney or\n  drawers; wardrobes with lofts in one bedroom and not the other)',
     '(for this kind of work: {missed})'),
    ('(a wardrobe 18 ft high, a TV unit 0.5 ft wide, length and width that look swapped)',
     '(far too big or too small for what it is, length and width that look swapped)'),
]


def _for_business(prompt, swaps):
    """The prompt in this business's words: as written for interiors, else with `swaps` made."""
    from . import business
    p = business.profile()
    if p['interiors']:
        return prompt
    names = [p['section_example']] + [n for n in p['section_suggestions'] if n != p['section_example']][:3]
    words = {'label': p['label'].lower(), 'sections': ', '.join(names) if len(names) > 1 else
             f'{p["section_example"]}, Bedroom, Kitchen…', 'item': p['item_example'],
             'example': ', '.join(p['typical_names'][:2]) or 'the work asked for', 'missed': p['often_missed']}
    for old, new in swaps:
        prompt = prompt.replace(old, new.format(**words))
    return prompt


def _rooms_text(project, rooms):
    from . import units
    out = []
    for room in rooms:
        out.append(f'Room: {room.name}')
        for i in room.item_list:
            if i.is_boq:
                rate = 'price to follow' if i.price_to_follow else f'at {_money(i.unit_price or 0)}'
                out.append(f'- {i.display_name}: {i.quantity or 0:g} {i.unit_text} {rate}')
            elif i.is_fitting:
                out.append(f'- {i.name}: fitting × {i.quantity or 0:g} at {_money(i.unit_price or 0)}')
            else:
                size = f'{units.length(i.length)} × {units.length(i.width)}' if i.length else 'area typed directly'
                out.append(f'- {i.name}: {size}{f" × {i.count}" if i.count > 1 else ""} ({units.area(i.area)}), '
                           f'{i.wood_type}{f" {i.work_type}" if i.work_type else ""}')
    return '\n'.join(out)


def rule_findings(project, rooms):
    """What's checked here, exactly: [{'level', 'where', 'message'}]."""
    from . import boq, units
    from .models import BoqItem, PriceListItem, Project
    out = []
    add = lambda level, where, message: out.append({'level': level, 'where': where, 'message': message})
    prices = {p.name.lower(): p.price for p in PriceListItem.query}
    lines = {b.name.lower(): b.rate for b in BoqItem.query} if boq.ready() else {}
    seen = set()
    for room in rooms:
        for i in room.item_list:
            where = f'{room.name} · {i.display_name if i.is_boq else i.name}'
            if i.is_fixed:
                if not (i.quantity or 0):
                    add('fix', where, 'No quantity.')
                if i.price_to_follow:
                    add('check', where, 'Price to follow: it isn\'t in the total yet.')
                own = (lines if i.is_boq else prices).get(i.name.lower())
                if own and i.unit_price is not None and abs(i.unit_price - own) / own > RATE_DIFF:
                    add('check', where, f'Rate {_money(i.unit_price)}; your usual rate is {_money(own)}.')
                if i.is_fitting and not i.unit_price:
                    add('fix', where, 'No price.')
                key = (room.name.lower(), i.name.lower(), i.quantity, i.unit_price)
            else:
                if not (i.area or 0):
                    add('fix', where, 'No size.')
                elif max(i.length or 0, i.width or 0) > BIG_SIZE_FT:
                    add('check', where, f'{units.length(max(i.length, i.width))} is very large: is the size right?')
                key = (room.name.lower(), i.name.lower(), round(i.length or 0, 3), round(i.width or 0, 3), i.wood_type)
            if key in seen:
                add('check', where, 'This line is on the quotation twice with the same size and price.')
            seen.add(key)
    pct = lambda p: (p.discount_amount / p.grand_total * 100) if (p.grand_total or 0) > 0 else 0
    mine = pct(project)
    if mine > 0:
        others = [pct(p) for p in Project.query.filter(Project.id != project.id, Project.status == 'complete')
                  .order_by(Project.id.desc()).limit(30)]
        usual = median(others) if others else 0
        if mine >= 10 and mine > usual + 5:
            add('check', 'Discount', f'{mine:.0f}% discount; your quotations usually have {usual:.0f}%.')
    return out


def check(project):
    """{'findings': [...], 'ai': bool, 'note'} for a quotation: the rules' findings, then the AI's. When the AI isn't
    used (the limit is reached, or it can't answer), the rules' findings come back with 'ai': False and why."""
    rooms = project.rooms_with_items()
    found = rule_findings(project, rooms)
    already = '\n'.join(f'- {f["where"]}: {f["message"]}' for f in found) or '(none)'
    prompt = (f'{_for_business(CHECK_PROMPT, CHECK_OTHER)}\n\n<quotation>\n{_rooms_text(project, rooms)}\n</quotation>\n\n'
              f'<already_found>\n{already}\n</already_found>')
    try:
        answer, used = _ask('check', prompt, Review, 3000)
    except AIProblem as exc:
        return {'findings': found, 'ai': False, 'note': str(exc)}
    ai = [{'level': f.level, 'where': ' '.join(f.where.split())[:120], 'message': ' '.join(f.message.split())[:300]}
          for f in answer.findings[:8] if f.message.strip()]
    ai_import._log('check', True, lines=len(ai), tokens_in=used['in'], tokens_out=used['out'])
    order = {'fix': 0, 'check': 1, 'idea': 2}
    return {'findings': sorted(found + ai, key=lambda f: order[f['level']]), 'ai': True, 'note': ''}
