"""Choose what the quotation PDF shows: tapping Quotation PDF opens tick-boxes (description, material, size,
quantity, rate, amount on each line, room total, photos) and the PDF, the customer's link and the emailed PDF show
only those. The item name is always shown. For the BOQ table (every business pricing by item, and any that chose it).

Off unless the operator turns it on for the business (console → Features). Stored in app_settings, no database update:
  pdf_choices            '1': the business gets the tick-boxes
  quote_pdf_<project>    the quotation's choice, JSON {field: true/false}; none yet: from the business's settings
"""
import json

SWITCH_KEY = 'pdf_choices'
FIELDS = [('cover', 'Cover page'), ('description', 'Description'), ('material', 'Material'), ('size', 'Size (length × width)'),
          ('qty', 'Quantity & unit (area)'), ('rate', 'Rate'), ('amount', 'Amount on each line'),
          ('room_total', 'Room total'), ('photos', 'Photos on lines'), ('photo_pages', 'Photo pages at the front')]
KEYS = [k for k, _ in FIELDS]


def _key(project_id):
    return f'quote_pdf_{int(project_id)}'


def enabled():
    from .models import AppSetting
    return AppSetting.get(SWITCH_KEY, '') == '1'


def set_enabled(on):
    from .models import AppSetting
    AppSetting.set(SWITCH_KEY, '1' if on else '')


def defaults():
    """Before a quotation has its own choice: what the business's settings print today."""
    from . import layout
    per_room = layout.room_totals_only()
    return {'description': True, 'material': True, 'size': True, 'qty': True,
            'rate': layout.show_rate() and not per_room, 'amount': not per_room, 'room_total': True, 'photos': True,
            'photo_pages': True, 'cover': True}


def for_project(project_id):
    """{field: shown} for this quotation: its own choice (with the feature on), else the business's settings."""
    from .models import AppSetting
    base = defaults()
    if not project_id or not enabled():
        return base
    try:
        saved = json.loads(AppSetting.get(_key(project_id), '') or '{}')
    except ValueError:
        saved = {}
    return {k: bool(saved[k]) if k in saved else v for k, v in base.items()}


def save(project_id, form):
    """The tick-boxes sent (a box not sent is unticked)."""
    from .models import AppSetting
    chosen = {k: form.get(k) == '1' for k in KEYS}
    AppSetting.set(_key(project_id), json.dumps(chosen))
    return chosen


def forget(project_id):
    from .models import AppSetting, db
    row = db.session.get(AppSetting, _key(project_id))
    if row:
        db.session.delete(row)
