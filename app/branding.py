"""
White-label branding.

Everything business-specific comes from environment variables (see .env.example).
The company contact fields can additionally be overridden by an admin from
Admin → Payment Settings; a non-empty value saved there wins over the env var,
and clearing it falls back to the env var again.
"""
import os
import re

from flask import g

_HEX_RE = re.compile(r'^#[0-9a-fA-F]{6}$')


def _env(name, default=''):
    return (os.environ.get(name) or default).strip()


def _hex(name, default):
    """Read a #rrggbb colour from env; fall back to the default if missing or malformed."""
    value = _env(name, default)
    return value if _HEX_RE.match(value) else default


def tint(hex_color, amount):
    """Mix a #rrggbb colour with white. amount=0 → original, 1 → white."""
    r, g_, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    mix = lambda c: round(c + (255 - c) * amount)
    return '#{:02x}{:02x}{:02x}'.format(mix(r), mix(g_), mix(b))


def _logo_file():
    """LOGO_FILE is a path inside static/, e.g. 'brand/logo.png'. Reject anything that escapes it."""
    path = _env('LOGO_FILE').lstrip('/')
    if not path or '..' in path.split('/'):
        return ''
    return path


# ── Deploy-time branding (env only) ───────────────────────────────────────────
PRIMARY   = _hex('BRAND_PRIMARY',   '#1a237e')
SECONDARY = _hex('BRAND_SECONDARY', '#283593')
ACCENT    = _hex('BRAND_ACCENT',    '#f57f17')

STATIC_BRAND = {
    'tagline':         _env('COMPANY_TAGLINE', 'Interior Design & Furnishing Solutions'),
    'signatory_name':  _env('SIGNATORY_NAME'),
    'signatory_title': _env('SIGNATORY_TITLE', 'Proprietor'),
    'logo_file':       _logo_file(),
    'primary':         PRIMARY,
    'secondary':       SECONDARY,
    'accent':          ACCENT,
    'light':           tint(PRIMARY, 0.9),
}

# ── Company details: env default, admin-overridable ───────────────────────────
# brand key → (AppSetting key, env var, default)
EDITABLE_FIELDS = {
    'name':    ('company_name',    'COMPANY_NAME',    'Your Company Name'),
    'address': ('company_address', 'COMPANY_ADDRESS', ''),
    'phone':   ('company_mobile',  'COMPANY_PHONE',   ''),
    'email':   ('company_email',   'COMPANY_EMAIL',   ''),
    'gstin':   ('company_gstin',   'COMPANY_GSTIN',   ''),
}


def env_default(setting_key):
    """The env-provided value for an admin-editable AppSetting key (used as a form placeholder)."""
    for app_key, env_name, default in EDITABLE_FIELDS.values():
        if app_key == setting_key:
            return _env(env_name, default)
    return ''


def get_brand():
    """
    Return the merged brand dict. Cached on flask.g so a request hits the
    settings table at most once.
    """
    if 'brand' in g:
        return g.brand

    from .models import AppSetting
    overrides = {}
    try:
        keys = [app_key for app_key, _, _ in EDITABLE_FIELDS.values()]
        rows = AppSetting.query.filter(AppSetting.key.in_(keys)).all()
        overrides = {r.key: (r.value or '').strip() for r in rows}
    except Exception:
        # DB unreachable (e.g. cold start) — render with env values only
        pass

    brand = dict(STATIC_BRAND)
    for brand_key, (app_key, env_name, default) in EDITABLE_FIELDS.items():
        brand[brand_key] = overrides.get(app_key) or _env(env_name, default)
    brand['signatory_name'] = brand['signatory_name'] or brand['name']

    g.brand = brand
    return brand
