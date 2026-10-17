"""Units of measurement, chosen by the admin for the whole business (Settings → Units).

Sizes are always STORED in feet (decimal), areas in sqft and rates per sqft, exactly as before. The business's units
only change how sizes are typed in and how sizes, areas and rates are shown, so switching units never changes a
measurement or a price:

    size unit:  'ftin' feet & inches (default) · 'mm' · 'cm' · 'in'
    area unit:  'sqft' (default) · 'sqm'   (rates follow it: ₹/sqft or ₹/sq m)
"""
from flask import g, has_app_context

SIZE_UNITS = {'ftin': 'Feet & inches', 'mm': 'Millimetres (mm)', 'cm': 'Centimetres (cm)', 'in': 'Inches (in)'}
AREA_UNITS = {'sqft': 'Square feet (sqft)', 'sqm': 'Square metres (sq m)'}
PER_FOOT = {'mm': 304.8, 'cm': 30.48, 'in': 12.0}          # 1 ft in each unit
SQM_PER_SQFT = 0.09290304                                  # exact: (0.3048 m)²
KEYS = ('size_unit', 'area_unit')


def _clean(raw):
    return {'size_unit': raw.get('size_unit') if raw.get('size_unit') in SIZE_UNITS else 'ftin',
            'area_unit': raw.get('area_unit') if raw.get('area_unit') in AREA_UNITS else 'sqft'}


def prime(raw):
    """Settings already fetched for this request (branding.get_brand reads them in its query)."""
    if has_app_context() and '_units' not in g:
        g._units = _clean(raw)


def _settings():
    if has_app_context() and '_units' in g:
        return g._units
    from .models import AppSetting
    try:
        raw = AppSetting.get_many(list(KEYS))
    except Exception:
        raw = {}
    s = _clean(raw)
    if has_app_context():
        g._units = s
    return s


def clear_cache():
    if has_app_context():
        g.pop('_units', None)


def size_unit():
    return _settings()['size_unit']


def area_unit():
    return _settings()['area_unit']


def _trim(value, dp):
    text = f'{value:,.{dp}f}'
    return text.rstrip('0').rstrip('.') if '.' in text else text


# ── Sizes ────────────────────────────────────────────────────────────────────

def ft_in(feet):
    whole = int(feet)
    inches = round((feet - whole) * 12)
    if inches == 12:
        whole, inches = whole + 1, 0
    return f'{whole} ft' if not inches else f'{whole} ft {inches} in'


def length(feet, unit=None):
    """A stored size (feet) in the business's unit: '7 ft 6 in', '2286 mm', '228.6 cm', '90 in'."""
    try:
        feet = float(feet or 0)
    except (TypeError, ValueError):
        return ''
    unit = unit or size_unit()
    if unit == 'ftin':
        return ft_in(feet)
    if unit == 'mm':
        return f'{round(feet * PER_FOOT["mm"]):,} mm'
    return f'{_trim(feet * PER_FOOT[unit], 1)} {unit}'


def length_value(feet, unit=None):
    """A stored size as the number typed in that unit (ftin: (feet, inches))."""
    unit = unit or size_unit()
    if unit == 'ftin':
        whole = int(feet or 0)
        inches = round(((feet or 0) - whole) * 12)
        return (whole + 1, 0) if inches == 12 else (whole, inches)
    return round((feet or 0) * PER_FOOT[unit], 1 if unit != 'mm' else 0)


def length_label(unit=None):
    unit = unit or size_unit()
    return {'ftin': 'ft & in', 'mm': 'mm', 'cm': 'cm', 'in': 'in'}[unit]


# ── Areas and rates ──────────────────────────────────────────────────────────

def area_value(sqft):
    return (sqft or 0) * SQM_PER_SQFT if area_unit() == 'sqm' else (sqft or 0)


def area_label():
    return 'sq m' if area_unit() == 'sqm' else 'sqft'


def area(sqft, dp=2):
    """'50.00 sqft' or '4.65 sq m'."""
    return f'{area_value(sqft):,.{dp}f} {area_label()}'


def rate_value(per_sqft):
    """A stored rate (₹ per sqft) per the business's area unit."""
    return (per_sqft or 0) / SQM_PER_SQFT if area_unit() == 'sqm' else (per_sqft or 0)


def rate_to_sqft(value):
    """A rate typed in the business's area unit → ₹ per sqft (as stored)."""
    return (value or 0) * SQM_PER_SQFT if area_unit() == 'sqm' else (value or 0)


def rate_label():
    return '/sq m' if area_unit() == 'sqm' else '/sqft'


def js():
    """What the quotation form's script needs."""
    unit = size_unit()
    return {'size': unit, 'perFoot': PER_FOOT.get(unit), 'sizeLabel': length_label(unit),
            'area': area_unit(), 'areaLabel': area_label(), 'areaFactor': SQM_PER_SQFT if area_unit() == 'sqm' else 1,
            'rateLabel': rate_label()}
