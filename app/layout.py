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
LAYOUTS = {LAYOUT_ROOMS: 'By room: items with sizes, one amount per room', LAYOUT_MATERIALS: 'By material: amount per material'}
LAYOUT_KEY = 'initial_layout'
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
    return value if value in LAYOUTS else LAYOUT_ROOMS


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
        if it.get('type') != 'fixed' and it.get('material') and it['material'] not in seen:
            seen.append(it['material'])
    return ', '.join(seen)


def room_rows(snapshot):
    """[{'no', 'title', 'description', 'items': [{'name', 'length', 'width', 'count'}], 'amount', 'hardware'}] plus
    totals. Room rows hold measured items; a room's fittings follow as their own Hardware row. Every amount comes
    from the snapshot's own item amounts, so rows add up to the quotation subtotal."""
    rows, n = [], 0
    for room in snapshot.get('rooms', []):
        measured = [it for it in room['items'] if it['type'] != 'fixed']
        fittings = [it for it in room['items'] if it['type'] == 'fixed']
        if measured:
            n += 1
            rows.append({'no': n, 'title': room['name'], 'hardware': False,
                         'description': room.get('description') or auto_description(measured),
                         'items': [{'name': it['name'], 'length': it['length'], 'width': it['width'],
                                    'count': it.get('count', 1)} for it in measured],
                         'amount': round(sum(it['amount'] for it in measured), 2)})
        if fittings:
            n += 1
            rows.append({'no': n, 'title': f"{room['name']} – Hardware" if measured else room['name'], 'hardware': True,
                         'description': '', 'items': [{'name': it['name'], 'length': None, 'width': None,
                                                       'count': it['quantity']} for it in fittings],
                         'amount': round(sum(it['amount'] for it in fittings), 2)})
    return rows


def count_text(count):
    return f'{count:g}' if isinstance(count, float) else str(count)


# ── Sections (Settings → Quotation PDFs) ─────────────────────────────────────

_NUMBERED = re.compile(r'^\s*(\d+[.)]|[•●\-–*])\s*')


def section_lines(text):
    """Non-empty lines, without any numbering or bullets the business typed (the PDF numbers them)."""
    return [_NUMBERED.sub('', line).strip() for line in (text or '').splitlines() if line.strip()
            and _NUMBERED.sub('', line).strip()]


def sections(settings, terms_lines):
    """[(title, [lines])] in print order; empty sections are left out. Terms & Conditions last."""
    out = [(title, section_lines(settings.get(key))) for key, title in SECTION_KEYS]
    out.append(('Terms & Conditions', [_NUMBERED.sub('', t).strip() for t in terms_lines if _NUMBERED.sub('', t).strip()]))
    return [(t, lines) for t, lines in out if lines]
