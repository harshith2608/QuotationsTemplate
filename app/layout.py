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
SECTION_KEYS = [('material_specs', 'Material Specifications'), ('payment_terms', 'Payment Terms'),
                ('delivery_terms', 'Delivery Terms'), ('important_notes', 'Important Notes')]


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


def initial_layout():
    from .models import AppSetting
    value = AppSetting.get(LAYOUT_KEY, '')
    if value == LAYOUT_BOQ:
        from . import boq
        return value if boq.enabled() else LAYOUT_ROOMS        # BOQ lines turned off: back to room by room
    return value if value in LAYOUTS else LAYOUT_ROOMS


def layouts():
    """The Initial Quotation layouts this business can choose (BOQ only with BOQ lines on)."""
    from . import boq
    return {k: v for k, v in LAYOUTS.items() if k != LAYOUT_BOQ or boq.enabled()}


def single_pdf():
    """A business that prices by item has one quotation PDF (its Initial Quotation, the BOQ): the Full Quotation would
    show the same lines, rates and amounts. Every "full" request (Full Quotation, email attachment, customer link)
    gives that one."""
    from . import boq
    return boq.enabled()


def boq_rows(snapshot):
    """Sections A, B, C… (the rooms), each with numbered lines: {'letter', 'name', 'description', 'lines': [{'no',
    'title', 'description', 'qty', 'unit', 'rate', 'amount', 'tbc'}]} (tbc: "Price to follow"). Measured items show their area, rate per area and
    size; fittings their quantity and price; BOQ lines exactly as typed. Amounts come from the snapshot."""
    from . import boq, units
    out = []
    for r_i, room in enumerate(snapshot.get('rooms', [])):
        letter = chr(ord('A') + r_i) if r_i < 26 else str(r_i + 1)
        lines = []
        for n, it in enumerate(room['items'], 1):
            desc = it.get('description') or ''
            if it['type'] == 'measured':
                size = f"{units.length(it['length'])} × {units.length(it['width'])}"
                if it.get('count', 1) > 1:
                    size += f" × {it['count']} No's"
                detail = f"{it['material']} · {size}"
                lines.append({'no': n, 'title': it['name'], 'description': '\n'.join(x for x in (desc, detail) if x),
                              'image_id': it.get('image_id'),
                              'qty': units.area_value(it['area']), 'unit': units.area_label(),
                              'rate': units.rate_value(it['rate']), 'amount': it['amount']})
            else:
                unit = it.get('unit') or 'nos'
                lump = unit == boq.LUMP_SUM
                size = boq.size_text(it)
                desc = '\n'.join(x for x in (desc, f'Size: {size}' if size else '') if x)
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
    """What a room is made of, from its measured items' materials (snapshot items), e.g.
    'Laminates – Box Work · 18mm BWP, Glass'."""
    seen = []
    for it in items:
        if it.get('type') == 'measured' and it.get('material') and it['material'] not in seen:
            seen.append(it['material'])
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
    return {'name': it['name'], 'length': it['length'], 'width': it['width'], 'count': it.get('count', 1),
            'image_id': it.get('image_id')}


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


def sections(settings, terms_lines, values=None):
    """[(title, [lines])] in print order, placeholders filled in; empty sections are left out. T&C last."""
    out = [(title, section_lines(fill(settings.get(key), values))) for key, title in SECTION_KEYS]
    terms = [_NUMBERED.sub('', fill(t, values)).strip() for t in terms_lines]
    out.append(('Terms & Conditions', [t for t in terms if t]))
    return [(t, lines) for t, lines in out if lines]
