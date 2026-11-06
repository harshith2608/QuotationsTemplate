"""Plans and prices, set in the console (Pricing): no code change to change a price or offer a plan.

Each plan is a length (monthly by autopay, 3, 6 or 12 months paid once) without or with AI, switched on or off with
its price. The console keeps them in public.console_state (the shared app and the console read it, within a minute)
and writes a copy to the website's own database (app_settings, kept on the nightly reset), as with the kinds of
business. Nothing saved yet: the prices below, or the old PLAN_PRICE_* variables when set.

Changing a price affects new payments only. A monthly autopay already running keeps its amount (each amount is its
own Razorpay plan: app/subscription.razorpay_plan).
"""
import json
import os

from .numbers import inr

KEY = 'pricing'
LENGTHS = {'1m': 1, '3m': 3, '6m': 6, '1y': 12}          # months
HEADS = {'1m': 'Monthly', '3m': '3 months', '6m': '6 months', '1y': '12 months'}
ALL = ('1m', '3m', '6m', '1y', '1m_ai', '3m_ai', '6m_ai', '1y_ai')
ADDON = 'ai40'
DEFAULTS = {'1m': (599, True), '3m': (1699, False), '6m': (4999, False), '1y': (5999, True),
            '1m_ai': (749, True), '3m_ai': (2099, False), '6m_ai': (5999, False), '1y_ai': (7499, True)}
DEFAULT_ADDON = 99
_ENV = {'1m': 'PLAN_PRICE_1M', '1y': 'PLAN_PRICE_1Y', '1m_ai': 'PLAN_PRICE_1M_AI', '1y_ai': 'PLAN_PRICE_1Y_AI',
        '6m': 'PLAN_PRICE_6M', '6m_ai': 'PLAN_PRICE_6M_AI'}
MAX_PRICE = 1_000_000


def _int(value, default):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _stored():
    """The saved JSON: the console's (shared app, console), or the website's copy (its own database)."""
    from . import platform_switch, tenancy
    from .models import AppSetting
    try:
        raw = platform_switch.value(KEY) if tenancy.tenant_mode() else AppSetting.get(KEY)
        found = json.loads(raw) if raw else None
    except Exception:
        found = None
    return found if isinstance(found, dict) else {}


def parse(found):
    """{'plans': {key: {'price', 'on'}}, 'addon': price} from a saved value (anything missing: the defaults)."""
    plans = {}
    saved = (found or {}).get('plans') or {}
    for key in ALL:
        price, on = DEFAULTS[key]
        price = _int(os.environ.get(_ENV.get(key, ''), ''), price) if _ENV.get(key) else price
        s = saved.get(key) if isinstance(saved.get(key), dict) else {}
        price = _int(s.get('price'), price)
        plans[key] = {'price': price if 0 < price <= MAX_PRICE else DEFAULTS[key][0],
                      'on': bool(s['on']) if 'on' in s else on}
    addon = _int((found or {}).get('addon'), _int(os.environ.get('AI_ADDON_PRICE', ''), DEFAULT_ADDON))
    return {'plans': plans, 'addon': addon if 0 < addon <= MAX_PRICE else DEFAULT_ADDON}


def load():
    return parse(_stored())


def prices(data=None):
    """{'1m': 599, '1y': 5999, …, 'ai40': 99} in rupees: every plan (on or off: payments by hand, old records)."""
    data = data or load()
    return {**{k: v['price'] for k, v in data['plans'].items()}, ADDON: data['addon']}


def offered(data=None, ai=None):
    """The plans a business can choose now, in order (monthly first). ai: only those with / without AI."""
    data = data or load()
    return [k for k in ALL if data['plans'][k]['on'] and (ai is None or k.endswith('_ai') == ai)]


def length(key):
    return key.removesuffix('_ai')


def months(key):
    return LENGTHS[length(key)]


def is_monthly(key):
    return length(key) == '1m'


def monthly_of(key):
    return '1m_ai' if key.endswith('_ai') else '1m'


def saving(key, data=None):
    """₹ saved against paying monthly for as long (0 for monthly, or when it isn't cheaper)."""
    p = prices(data)
    return max(0, p[monthly_of(key)] * months(key) - p[key]) if not is_monthly(key) else 0


def free_months(key, data=None):
    """Months free against monthly, to the nearest (e.g. 12 months for ₹5,999 at ₹599 a month: 2)."""
    p = prices(data)
    return int(round(saving(key, data) / p[monthly_of(key)])) if p[monthly_of(key)] else 0


def per_month(key, data=None):
    return round(prices(data)[key] / months(key))


def per_word(key):
    return {'1m': 'a month', '3m': 'for 3 months', '6m': 'for 6 months', '1y': 'a year'}[length(key)]


def badge(key, data=None):
    """"2 months free" (only while the monthly plan it's measured against is offered)."""
    data = data or load()
    if not data['plans'][monthly_of(key)]['on']:
        return ''
    n = free_months(key, data)
    return f'{n} month{"s" if n > 1 else ""} free' if n else ''


def summary(data=None):
    """"₹599 a month by autopay or ₹5,999 for 12 months (with AI: ₹749 / ₹7,499)": the plans on, for messages."""
    data = data or load()
    p = prices(data)

    def part(keys):
        bits = []
        for k in keys:
            if is_monthly(k):
                bits.append(f'₹{inr(p[k], 0)} a month by autopay')
            else:
                bits.append(f'₹{inr(p[k], 0)} for {HEADS[length(k)].lower()}')
        return ' or '.join(bits)
    std, ai = offered(data, ai=False), offered(data, ai=True)
    text = part(std) or part(ai)
    if std and ai:
        text += ' (with AI: ' + ' / '.join(f'₹{inr(p[k], 0)}' for k in ai) + ')'
    return text


def fields(data=None):
    """Placeholders for messages and sales texts: {price_1m}, {price_1y}, … (Indian style, no ₹), {addon_price},
    {free_1y} ("2 months free" or ""), {prices} (the summary)."""
    data = data or load()
    p = prices(data)
    out = {f'price_{k}': inr(p[k], 0) for k in ALL}
    out.update(addon_price=inr(p[ADDON], 0), prices=summary(data),
               **{f'free_{k}': badge(k, data) for k in ALL if not is_monthly(k)})
    return out


FIELD_HELP = {'price_1m': 'monthly price', 'price_1y': '12-month price', 'price_1m_ai': 'monthly price with AI',
              'price_1y_ai': '12-month price with AI', 'price_6m': '6-month price', 'price_3m': '3-month price',
              'addon_price': 'price of 40 more AI uses', 'free_1y': '"2 months free" on 12 months (or empty)',
              'prices': 'the plans on, in one line'}


def validate(form):
    """(data, errors) from the console's Pricing form."""
    plans, errors = {}, []
    for key in ALL:
        raw = (form.get(f'price_{key}') or '').replace(',', '').replace('₹', '').strip()
        price = _int(raw, None)
        on = bool(form.get(f'on_{key}'))
        if price is None or not 0 < price <= MAX_PRICE:
            if on:
                errors.append(f'Type a price for {HEADS[length(key)]}{" with AI" if key.endswith("_ai") else ""}.')
            price = DEFAULTS[key][0]
        plans[key] = {'price': price, 'on': on}
    addon = _int((form.get('addon') or '').replace(',', '').replace('₹', '').strip(), None)
    if addon is None or not 0 < addon <= MAX_PRICE:
        errors.append('Type a price for the extra AI uses.')
        addon = DEFAULT_ADDON
    if not any(v['on'] for k, v in plans.items() if not k.endswith('_ai')):
        errors.append('Keep at least one plan without AI on.')
    return {'plans': plans, 'addon': addon}, errors
