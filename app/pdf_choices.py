"""Choose what the quotation PDF shows: tapping Quotation PDF opens tick-boxes (description, material, size,
quantity, rate, amount on each line, room total, photos) and the PDF, the customer's link and the emailed PDF show
only those. The item name is always shown. For the BOQ table (every business pricing by item, and any that chose it).

Off unless the operator turns it on for the business (console → Features). Stored in app_settings, no database update:
  pdf_choices            '1': the business gets the tick-boxes
  quote_pdf_<project>    the quotation's choice, JSON {field: true/false}; none yet: from the business's settings
"""
import json

SWITCH_KEY = 'pdf_choices'
FIELDS = [('description', 'Description'), ('material', 'Material'), ('size', 'Size (length × width)'),
          ('qty', 'Quantity & unit (area)'), ('rate', 'Rate'), ('amount', 'Amount on each line'),
          ('room_total', 'Room total'), ('photos', 'Photos on lines')]
KEYS = [k for k, _ in FIELDS]


def _key(project_id):
    return f'quote_pdf_{int(project_id)}'


def enabled():
    from .models import AppSetting
    return AppSetting.get(SWITCH_KEY, '') == '1'


def set_enabled(on):
    from .models import AppSetting
    AppSetting.set(SWITCH_KEY, '1' if on else '')


LAST_KEY = 'pdf_choices_last'          # the business's last choice: where a new quotation's tick-boxes start


def defaults():
    """Before a quotation has its own choice: the last one made in this business (with the feature on), else what
    the business's settings (Settings → Quotation PDFs, before the tick-boxes) printed."""
    from . import layout
    from .models import AppSetting
    if enabled():
        try:
            last = json.loads(AppSetting.get(LAST_KEY, '') or '{}')
        except ValueError:
            last = {}
        if isinstance(last, dict) and last:
            return {k: bool(last.get(k, True)) for k in KEYS}
    per_room = layout.room_totals_only()
    return {'description': True, 'material': True, 'size': True, 'qty': True,
            'rate': layout.show_rate() and not per_room, 'amount': not per_room, 'room_total': True, 'photos': True,
}


def for_project(project_id):
    """{field: shown} for this quotation: its own choice (with the feature on), else the business's settings."""
    from .models import AppSetting
    base = defaults()
    if project_id and enabled():
        try:
            saved = json.loads(AppSetting.get(_key(project_id), '') or '{}')
        except ValueError:
            saved = {}
        base = {k: bool(saved[k]) if k in saved else v for k, v in base.items()}
    return _without_rates(base, project_id)


def _without_rates(show, project_id):
    """An employee who can't see rates (app/rate_access.py), or a customer's link made by one: no rates or line
    amounts, whatever the quotation says (its room totals and total stay)."""
    from flask import g, has_app_context
    from . import rate_access
    hide = (has_app_context() and g.get('link_no_rates')) or not rate_access.current_can_see(project_id)
    return {**show, 'rate': False, 'amount': False} if hide else show


def save(project_id, form):
    """The tick-boxes sent (a box not sent is unticked)."""
    from .models import AppSetting
    chosen = {k: form.get(k) == '1' for k in KEYS}
    AppSetting.set(_key(project_id), json.dumps(chosen))
    AppSetting.set(LAST_KEY, json.dumps(chosen))       # (the next new quotation starts from this)
    return chosen


def forget(project_id):
    from .models import AppSetting, db
    row = db.session.get(AppSetting, _key(project_id))
    if row:
        db.session.delete(row)
