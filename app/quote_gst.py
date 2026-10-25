"""GST on quotations: the quotation shows its total, then GST at the business's rate, then the grand total with GST
(e.g. Total ₹18,09,753 · GST @ 18% ₹3,25,756 · Grand total ₹21,35,509). Turned on per business from the console
(Features → GST on quotations, with the rate), off by default.

Prices on the quotation stay without GST (project.final_total); GST is added on top. While it's on, what the customer
owes (balance, payment reminders, the customer's link) is the grand total with GST, and a new invoice adds GST on the
quoted prices at this rate (not a second time). Reports keep using the amount before GST (that's the business's).
"""
from flask import g, has_app_context

KEY = 'feature_quote_gst'
RATE_KEY = 'quote_gst_rate'
RATES = (5, 12, 18, 28)
DEFAULT_RATE = 18


def _settings(values=None):
    """values: app settings already loaded (get_many with KEY and RATE_KEY), to save a query."""
    from . import tenancy
    schema = tenancy.current_schema()                 # per business: the console opens several in one request
    cache = g.setdefault('_quote_gst', {}) if has_app_context() else {}
    if values is None and schema in cache:
        return cache[schema]
    from .models import AppSetting
    s = values if values is not None else AppSetting.get_many([KEY, RATE_KEY])
    try:
        rate = float(s[RATE_KEY]) if s[RATE_KEY] else DEFAULT_RATE
    except ValueError:
        rate = DEFAULT_RATE
    out = {'on': s[KEY] == '1', 'rate': rate if rate in RATES else DEFAULT_RATE}
    cache[schema] = out
    return out


def prime(values):
    """Remember the settings from values already loaded (one query for several features on a page)."""
    _settings(values)


def enabled():
    return _settings()['on']


def rate():
    """The GST % added to quotations (0 when off)."""
    s = _settings()
    return s['rate'] if s['on'] else 0


def amount(total):
    """GST on a quotation total (0 when off)."""
    r = rate()
    return round((total or 0) * r / 100, 2) if r else 0.0


def console_status():
    """{'on', 'rate'} read afresh (the console opens many businesses in one process)."""
    if has_app_context():
        g.pop('_quote_gst', None)
    return dict(_settings())


def set_gst(on, rate_value):
    from .models import AppSetting
    try:
        r = float(rate_value)
    except (TypeError, ValueError):
        r = DEFAULT_RATE
    if r not in RATES:
        raise ValueError(f'GST rate should be one of {", ".join(f"{x}%" for x in RATES)}.')
    AppSetting.set(KEY, '1' if on else '')
    AppSetting.set(RATE_KEY, f'{r:g}')
    if has_app_context():
        g.pop('_quote_gst', None)
