"""The Initial Quotation (what the customer gets): room by room, or by material.

Room by room (the default): one row per room with what it's made of, its items with their sizes and count ("No's"),
and ONE amount for the room; each room's fittings get their own "<Room> – Hardware" row with one amount. No rates,
no areas, no per-item prices. Then Basic Total, discount and Total. Built from a quotation snapshot
(billing.quotation_snapshot), so the PDF and the customer's online link show exactly the same rows.

Also the business's quotation sections (Settings → Quotation PDFs): Material Specifications, Payment Terms,
Delivery Terms, Important Notes and Terms & Conditions, each a numbered list (one point per line).
"""
import re

from flask import g, has_app_context

from . import db

LAYOUT_ROOMS = 'rooms'
LAYOUT_MATERIALS = 'materials'
LAYOUT_BOQ = 'boq'
LAYOUTS = {LAYOUT_ROOMS: 'By room: items with sizes, one amount per room', LAYOUT_MATERIALS: 'By material: amount per material',
           LAYOUT_BOQ: 'BOQ: every line with its description, quantity, unit, rate and amount'}
LAYOUT_KEY = 'initial_layout'
HIDE_RATE_KEY = 'boq_hide_rate'      # '1': the customer's BOQ shows quantities and amounts, no Rate column


def show_rate():
    """The Rate column on the customer's BOQ (PDF, link, WhatsApp). On unless the business turned it off."""
    from .models import AppSetting
    return AppSetting.get(HIDE_RATE_KEY, '') != '1'


# Some firms' customers want the BOQ without a price on each line (only each section's total), or without the board
# (plywood) on every line: it goes in the Terms instead, with {plywood}. Settings → Quotation PDFs.
ROOM_TOTALS_KEY = 'boq_room_totals'  # '1': lines show their quantity; only each room (section) has an amount
HIDE_BOARD_KEY = 'boq_hide_board'    # '1': a line says "TV Unit Ledge box (Laminate Finish)", not "… · 16mm Sainik"


def room_totals_only():
    """The customer's BOQ shows an amount per room only (PDF, link, WhatsApp)."""
    from .models import AppSetting
    return AppSetting.get(ROOM_TOTALS_KEY, '') == '1'


def show_board():
    from .models import AppSetting
    return AppSetting.get(HIDE_BOARD_KEY, '') != '1'


def line_material(text):
    """A line's material as the customer sees it; without the board ('… · 16mm Century Sainik') when the firm
    prints that in its Terms instead."""
    from .materials import customer_label
    text = customer_label(text)
    return text if show_board() else text.partition(' · ')[0]


SECTION_KEYS = [('material_specs', 'Material Specifications'), ('payment_terms', 'Payment Terms'),
                ('delivery_terms', 'Delivery Terms'), ('important_notes', 'Important Notes')]


BREAKS_KEY = 'pdf_page_breaks'      # JSON [section key, …]: those start on a new page in the PDF; not set: automatic
BREAK_KEYS = [k for k, _ in SECTION_KEYS] + ['terms_conditions']


def page_breaks():
    """The sections (Settings → Quotation PDFs) that start on a new page, or None: never chosen, so the sections
    start on a new page together only when less than half a page is left after the quotation."""
    import json
    from .models import AppSetting
    raw = AppSetting.get(BREAKS_KEY, None)
    if raw is None or raw == '':
        return None
    try:
        keys = json.loads(raw)
    except ValueError:
        return None
    return [k for k in keys if k in BREAK_KEYS] if isinstance(keys, list) else None


def set_page_breaks(keys):
    import json
    from .models import AppSetting
    AppSetting.set(BREAKS_KEY, json.dumps([k for k in BREAK_KEYS if k in set(keys or [])]))


DESCRIPTIONS_KEY = 'room_descriptions'
DESCRIPTION_MAX = 500


def description_options():
    """The admin's room descriptions (Settings → Quotation PDFs), one per line, in order, without duplicates."""
    from .models import AppSetting
    out = []
    for line in (AppSetting.get(DESCRIPTIONS_KEY, '') or '').splitlines():
        line = ' '.join(line.split())[:DESCRIPTION_MAX]
        if line and line not in out:
            out.append(line)
    return out[:100]


def choosing():
    """The business chooses what each quotation's PDF shows (console: Choose what the PDF shows, app/pdf_choices.py):
    one Quotation PDF, the item table shaped by its tick-boxes, priced by item or by material."""
    from . import boq, pdf_choices
    return pdf_choices.enabled() and boq.ready()


def initial_layout():
    from .models import AppSetting
    if choosing():
        return LAYOUT_BOQ                      # (its columns chosen per quotation)
    value = AppSetting.get(LAYOUT_KEY, '')
    if value == LAYOUT_BOQ:                    # (pricing by material too: every item on its own line)
        from . import boq
        return value if boq.ready() else LAYOUT_ROOMS
    return value if value in LAYOUTS else LAYOUT_ROOMS


def layouts():
    """The Initial Quotation layouts this business can choose. BOQ (every line numbered, in sections A, B, C) also
    suits a business pricing by material that wants each item on its own line with its photo."""
    from . import boq
    return {k: v for k, v in LAYOUTS.items() if k != LAYOUT_BOQ or boq.ready()}


def single_pdf():
    """A business that prices by item has one quotation PDF (its Initial Quotation, the BOQ): the Full Quotation would
    show the same lines, rates and amounts. So does one that chooses what the PDF shows (by material too): sizes,
    rates and amounts are its tick-boxes. Every "full" request (Full Quotation, email attachment, customer link)
    gives that one."""
    from . import boq
    return boq.enabled() or choosing()         # (by material too, when choosing what the PDF shows)


def boq_rows(snapshot, show=None):
    """Sections A, B, C… (the rooms), each with numbered lines: {'letter', 'name', 'description', 'lines': [{'no',
    'title', 'description', 'qty', 'unit', 'rate', 'amount', 'tbc'}]} (tbc: "Price to follow"). Measured items show their area, rate per area and
    size; fittings their quantity and price; BOQ lines exactly as typed. Amounts come from the snapshot.
    A measured line says its material and size first, then what the business typed about it.
    show: what to print (app/pdf_choices.py: description, material, size…); None: everything."""
    from . import boq, units
    show = show or {}
    on = lambda k: show.get(k, True)
    out = []
    for r_i, room in enumerate(snapshot.get('rooms', [])):
        letter = chr(ord('A') + r_i) if r_i < 26 else str(r_i + 1)
        lines = []
        for n, it in enumerate(room['items'], 1):
            desc = it.get('description') or ''
            if it['type'] == 'measured':
                size = f"{units.length(it['length'])} × {units.length(it['width'])}" if it.get('length') else ''
                if size and it.get('count', 1) > 1:
                    size += f" × {it['count']} No's"
                mat = line_material(it['material'])
                if mat.partition(' · ')[0].strip().lower() == (it['name'] or '').strip().lower():
                    mat = mat.partition(' · ')[2]      # the item is named after its material: not said twice
                detail = ' · '.join(x for x in (mat if on('material') else '', size if on('size') else '') if x)
                lines.append({'no': n, 'title': it['name'],
                              'description': '\n'.join(x for x in (detail, desc if on('description') else '') if x),
                              'image_id': it.get('image_id'),
                              'qty': units.area_value(it['area']), 'unit': units.area_label(),
                              'rate': units.rate_value(it['rate']), 'amount': it['amount']})
            else:
                unit = it.get('unit') or 'nos'
                lump = unit == boq.LUMP_SUM
                size = boq.size_text(it)
                desc = '\n'.join(x for x in (desc if on('description') else '',
                                              f'Size: {size}' if size and on('size') else '') if x)
                from .finishes import label
                lines.append({'no': n, 'title': label(it['name'], it.get('finish')), 'description': desc, 'qty': it['quantity'],
                              'image_id': it.get('image_id'),
                              'unit': boq.unit_text(unit), 'rate': None if lump or not it['unit_price'] else it['unit_price'],
                              'amount': it['amount'], 'tbc': bool(it.get('tbc'))})
        total = round(sum(l['amount'] or 0 for l in lines if not l.get('tbc')), 2)   # rate-only lines are 0
        out.append({'letter': letter, 'name': room['name'], 'description': room.get('description') or '', 'lines': lines,
                    'total': total})
    return out


_ready_forever = {}


def description_ready():
    """False until the database update that adds rooms.description has run (checked once per request)."""
    from . import tenancy
    schema = tenancy.current_schema()
    if _ready_forever.get(schema):
        return True
    if has_app_context() and '_room_desc_ready' in g:
        return g._room_desc_ready
    from sqlalchemy import inspect
    try:
        ready = 'description' in {c['name'] for c in inspect(db.session.connection()).get_columns('rooms', schema=schema)}
    except Exception:
        ready = False
    if ready:
        _ready_forever[schema] = True
    if has_app_context():
        g._room_desc_ready = ready
    return ready


def room_description(room):
    """A room's own description, or '' (never reads the column before the update)."""
    return (room.description or '') if description_ready() else ''


def auto_description(items):
    """What a room is made of, from its measured items' materials (snapshot items), as the customer sees them, e.g.
    'Laminate Finish · 18mm BWP, Glass'."""
    seen = []
    for it in items:                           # (as the customer sees them: "Laminate Finish", once)
        text = line_material(it.get('material')) if it.get('type') == 'measured' else ''
        if text and text not in seen:
            seen.append(text)
    return ', '.join(seen)


def room_rows(snapshot):
    """[{'no', 'title', 'description', 'items': [{'name', 'length', 'width', 'count'}], 'amount', 'hardware'}] plus
    totals. Room rows hold measured items; a room's fittings follow as their own Hardware row, and each lump sum as its
    own row. Every amount comes
    from the snapshot's own item amounts, so rows add up to the quotation subtotal."""
    from .boq import LUMP_SUM
    rows, n = [], 0
    for room in snapshot.get('rooms', []):
        is_lump = lambda it: it['type'] == 'boq' and it.get('unit') == LUMP_SUM and it.get('quantity')
        measured = [it for it in room['items'] if it['type'] != 'fixed' and not is_lump(it)]   # BOQ lines go with them
        fittings = [it for it in room['items'] if it['type'] == 'fixed']
        lumps = [it for it in room['items'] if is_lump(it)]
        if measured:
            n += 1
            rows.append({'no': n, 'title': room['name'], 'hardware': False,
                         'description': room.get('description') or auto_description(measured),
                         'items': [_room_item(it) for it in measured],
                         'amount': round(sum(it['amount'] for it in measured), 2)})
        if fittings:
            n += 1
            rows.append({'no': n, 'title': f"{room['name']} – Hardware" if measured else room['name'], 'hardware': True,
                         'description': '', 'items': [{'name': it['name'], 'length': None, 'width': None,
                                                       'count': it['quantity'], 'image_id': it.get('image_id')}
                                                      for it in fittings],
                         'amount': round(sum(it['amount'] for it in fittings), 2)})
        for it in lumps:                        # a lump sum (pooja civil works ₹30,000): its own row and amount
            n += 1
            rows.append({'no': n, 'title': f"{room['name']} – {it['name']}" if measured or fittings or len(lumps) > 1
                         else room['name'], 'hardware': False, 'description': it.get('description') or '',
                         'items': [{'name': it['name'], 'length': None, 'width': None, 'count': '1 LS',
                                    'image_id': it.get('image_id')}],
                         'amount': round(it['amount'], 2)})
    return rows


def _room_item(it):
    if it['type'] == 'boq':                    # no sizes: its quantity and unit, e.g. "696 Sq.ft"
        from . import boq
        return {'name': it['name'], 'length': it.get('length') or None, 'width': it.get('width') or None,
                'count': f"{boq.qty_text(it['quantity'])} {boq.unit_text(it.get('unit'))}".strip(),
                'image_id': it.get('image_id')}
    if not it.get('length'):                   # its area typed directly (no size): the area in No's, e.g. "42.5 sqft"
        from . import units
        return {'name': it['name'], 'length': None, 'width': None, 'count': units.area(it.get('area') or 0),
                'image_id': it.get('image_id'), 'description': it.get('description') or ''}
    return {'name': it['name'], 'length': it['length'], 'width': it['width'], 'count': it.get('count', 1),
            'image_id': it.get('image_id'), 'description': it.get('description') or ''}


def count_text(count):
    return f'{count:g}' if isinstance(count, float) else str(count)


# ── Sections (Settings → Quotation PDFs) ─────────────────────────────────────

_NUMBERED = re.compile(r'^\s*(\d+[.)]|[•●\-–*])\s*')


def section_lines(text):
    """Non-empty lines, without any numbering or bullets the business typed (the PDF numbers them)."""
    return [_NUMBERED.sub('', line).strip() for line in (text or '').splitlines() if line.strip()
            and _NUMBERED.sub('', line).strip()]


# Placeholders the business can put in any section (Settings → Quotation PDFs offers them as buttons)
VARIABLES = [('plywood', 'Plywood'), ('plywood_details', 'Plywood details'), ('materials', 'Materials used'),
             ('customer', 'Customer name'), ('company', 'Your company'), ('quotation_no', 'Quotation no.'), ('date', 'Date')]
_VAR = re.compile(r'\{\s*(' + '|'.join(k for k, _ in VARIABLES) + r')\s*\}')


def variables(project, rooms=None):
    """{placeholder: text} for a quotation. Plywood: the quotation's plywood(s) (items can use their own)."""
    from datetime import timedelta
    from . import plywood
    from .branding import get_brand
    rooms = rooms if rooms is not None else project.rooms_with_items()
    used = plywood.used_on(project, rooms) if plywood.enabled() else []
    from . import materials as M
    materials = []
    for room in rooms:
        for i in room.item_list:
            if not i.is_fixed:
                label = M.label(i.wood_type, i.work_type)
                if label not in materials:
                    materials.append(label)
    return {'plywood': ', '.join(used), 'plywood_details': '; '.join(plywood.details_of(n) for n in used),
            'materials': ', '.join(materials), 'customer': project.customer_name or '', 'company': get_brand()['name'],
            'quotation_no': str(project.id),
            'date': (project.created_at + timedelta(hours=5, minutes=30)).strftime('%d %b %Y') if project.created_at else ''}


def fill(text, values):
    """Replace {placeholders} with the quotation's values; unknown {words} are left as typed."""
    return _VAR.sub(lambda m: values.get(m.group(1), ''), text or '') if values else (text or '')


def fill_html(html, values):
    """fill() for formatted text: the values are escaped (a plywood name with & or < stays text)."""
    from html import escape
    return _VAR.sub(lambda m: escape(values.get(m.group(1), '')), html or '') if values else (html or '')


def sections(settings, terms_text, values=None):
    """[(title, [lines], html)] in print order, placeholders filled in; empty sections are left out. T&C last.
    A section typed in the rich text editor (Settings → Quotation PDFs) has its cleaned HTML (lines: its plain text);
    plain text (from before, or a price list file) has html None and prints as a numbered list."""
    from . import richtext
    out = []
    for key, title in SECTION_KEYS + [('terms_conditions', 'Terms & Conditions')]:
        raw = terms_text if key == 'terms_conditions' else settings.get(key)
        if richtext.is_html(raw):
            html = richtext.clean(fill_html(raw, values))
            lines = [l.strip() for l in richtext.plain_text(html).split('  ') if l.strip()]
            if html:
                out.append((title, lines, html))
        else:
            lines = section_lines(fill(raw, values))
            if lines:
                out.append((title, lines, None))
    return out


def section_editor_html(raw):
    """What the rich text editor opens with: the saved HTML, or plain text as the numbered list the PDF prints."""
    from . import richtext
    return richtext.clean(raw) if richtext.is_html(raw) else richtext.from_plain(raw, numbered=True)


# ── How long a quotation is valid (Settings → Quotation PDFs → Validity) ──
VALID_KEY = 'quote_valid_days'
VALID_MAX = 3650


def valid_days():
    """Days a quotation is valid from its date; None when left empty (then no "Valid until" on the PDFs)."""
    from .models import AppSetting
    try:
        n = int((AppSetting.get(VALID_KEY, '') or '').strip())
    except ValueError:
        return None
    return n if 0 < n <= VALID_MAX else None


def set_valid_days(raw):
    """From the Settings box: a number of days, or empty (off). Returns an error message or None."""
    from .models import AppSetting
    raw = (raw or '').strip()
    if not raw:
        AppSetting.set(VALID_KEY, '')
        return None
    try:
        n = int(float(raw))
    except ValueError:
        return 'Valid for: type a number of days, or leave it empty.'
    if not 0 < n <= VALID_MAX:
        return f'Valid for: between 1 and {VALID_MAX} days, or leave it empty.'
    AppSetting.set(VALID_KEY, str(n))
    return None


def valid_until(dated):
    """The date a quotation dated `dated` (UTC datetime) is valid until, in India time; None when not set."""
    from datetime import timedelta
    n = valid_days()
    return (dated + timedelta(hours=5, minutes=30, days=n)) if (n and dated) else None
