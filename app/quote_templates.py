"""Quotation templates and "Duplicate": start a new quotation from an earlier one instead of from blank.

A template is a copy of a quotation's rooms and items (with BOQ lines, descriptions, sizes and rates), its discount
and plywood, saved under a name such as "2 BHK turnkey" (Save as template, admins). It is kept in app_settings
(one JSON list), not as a quotation, so it never appears in the quotations list, reports or totals, and editing the
quotation it came from later doesn't change it. New Quotation offers the templates ("Start from"); Duplicate on any
quotation does the same from that quotation. The new quotation gets everything but the customer.
"""
import json
import secrets
from datetime import datetime

KEY = 'quote_templates'
NAME_MAX = 60
LIMIT = 30


def _load():
    from .models import AppSetting
    try:
        data = json.loads(AppSetting.get(KEY, '') or '[]')
    except ValueError:
        data = []
    return [t for t in data if isinstance(t, dict) and t.get('id') and t.get('name')] if isinstance(data, list) else []


def _store(templates):
    from .models import AppSetting
    AppSetting.set(KEY, json.dumps(templates))


def all_templates():
    """[{id, name, rooms, lines, saved_at}] (without the content), newest first."""
    return [{'id': t['id'], 'name': t['name'], 'rooms': len(t.get('rooms') or []),
             'lines': sum(len(r.get('items') or []) for r in t.get('rooms') or []), 'saved_at': t.get('saved_at', '')}
            for t in sorted(_load(), key=lambda t: t.get('saved_at', ''), reverse=True)]


def get(template_id):
    return next((t for t in _load() if t['id'] == template_id), None)


def start_from_project(project):
    """What a new quotation copies from `project`: {'rooms_json', 'discount_type', 'discount_value', 'plywood'}."""
    from .projects import _build_rooms_json
    return {'rooms_json': _build_rooms_json(project), 'discount_type': project.discount_type or 'none',
            'discount_value': project.discount_value or 0, 'plywood_thickness': project.plywood_thickness or ''}


def start_from_template(template):
    return {'rooms_json': json.dumps(template.get('rooms') or []), 'discount_type': template.get('discount_type') or 'none',
            'discount_value': template.get('discount_value') or 0, 'plywood_thickness': template.get('plywood_thickness') or '',
            'plywood': template.get('plywood')}


def save(name, project):
    """Save `project` as a template called `name` (replacing one with the same name). Returns the template's id."""
    from . import plywood
    name = ' '.join((name or '').split())[:NAME_MAX]
    if not name:
        raise ValueError('Give the template a name, e.g. "2 BHK turnkey".')
    start = start_from_project(project)
    templates = [t for t in _load() if t['name'].lower() != name.lower()]
    if len(templates) >= LIMIT:
        raise ValueError(f'You have {LIMIT} templates already. Delete one first.')
    tid = secrets.token_hex(4)
    templates.append({'id': tid, 'name': name, 'rooms': json.loads(start['rooms_json']),
                      'discount_type': start['discount_type'], 'discount_value': start['discount_value'],
                      'plywood_thickness': start['plywood_thickness'], 'plywood': plywood.project_plywood(project),
                      'saved_at': datetime.utcnow().isoformat(timespec='seconds')})
    _store(templates)
    return tid


def put(name, rooms):
    """Save ready-made rooms (a firm's price list, app/price_list.py) as the template `name`, replacing one with the
    same name. Returns its id."""
    name = ' '.join((name or '').split())[:NAME_MAX]
    templates = [t for t in _load() if t['name'].lower() != name.lower()]
    if len(templates) >= LIMIT:
        raise ValueError(f'This business has {LIMIT} templates already.')
    tid = secrets.token_hex(4)
    templates.append({'id': tid, 'name': name, 'rooms': rooms, 'discount_type': 'none', 'discount_value': 0,
                      'plywood_thickness': '', 'plywood': None, 'saved_at': datetime.utcnow().isoformat(timespec='seconds')})
    _store(templates)
    return tid


def rename(template_id, name):
    name = ' '.join((name or '').split())[:NAME_MAX]
    templates = _load()
    if not name or any(t['name'].lower() == name.lower() and t['id'] != template_id for t in templates):
        raise ValueError('Choose a name that isn\'t used by another template.')
    for t in templates:
        if t['id'] == template_id:
            t['name'] = name
    _store(templates)


def delete(template_id):
    _store([t for t in _load() if t['id'] != template_id])
