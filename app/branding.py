"""
White-label branding and theming.

Every value has three layers, highest priority first:
  1. What an admin saved in Admin → Settings (stored in app_settings)
  2. The deployment's environment variable (see .env.example)
  3. The built-in default below

get_brand() merges them once per request and adds derived values (readable
text colours, tints, font stacks, corner radii) that templates and PDFs use.
"""
import base64
import hashlib
import io
import os
import re

from flask import g, url_for

_HEX_RE = re.compile(r'^#[0-9a-fA-F]{6}$')

# ── Choice lists (also drive the Settings UI) ─────────────────────────────────
HEADER_STYLES = {
    'gradient': 'Gradient',
    'solid':    'Solid colour',
    'light':    'Light',
}

CORNER_STYLES = {
    # key: (label, base radius, small, large, card)
    'sharp':   ('Sharp',         '0',       '0',      '0',      '0'),
    'rounded': ('Rounded',       '.375rem', '.25rem', '.5rem',  '10px'),
    'soft':    ('Extra rounded', '.75rem',  '.5rem',  '1rem',   '18px'),
}

BUTTON_SHAPES = {
    'standard': 'Match corners',
    'pill':     'Pill',
}

FONTS = {
    # key: (label, Google Fonts family param or None, CSS font stack)
    'system':     ('System default',  None,               "'Segoe UI', system-ui, -apple-system, Roboto, sans-serif"),
    'inter':      ('Inter',           'Inter',            "'Inter', system-ui, sans-serif"),
    'poppins':    ('Poppins',         'Poppins',          "'Poppins', system-ui, sans-serif"),
    'montserrat': ('Montserrat',      'Montserrat',       "'Montserrat', system-ui, sans-serif"),
    'lato':       ('Lato',            'Lato',             "'Lato', system-ui, sans-serif"),
    'nunito':     ('Nunito',          'Nunito',           "'Nunito', system-ui, sans-serif"),
    'dm-sans':    ('DM Sans',         'DM+Sans',          "'DM Sans', system-ui, sans-serif"),
    'lora':       ('Lora (serif)',    'Lora',             "'Lora', Georgia, serif"),
}

# Curated palettes: primary, secondary, accent, page background
PRESETS = {
    'Indigo':          ('#1a237e', '#283593', '#f57f17', '#f5f6fa'),
    'Walnut':          ('#3e2723', '#5d4037', '#c8a165', '#f8f5f1'),
    'Charcoal & Gold': ('#1f2937', '#374151', '#d4a017', '#f6f6f4'),
    'Emerald':         ('#065f46', '#047857', '#f59e0b', '#f3f7f5'),
    'Sage':            ('#3f5f4a', '#5b7f66', '#c9a227', '#f5f7f3'),
    'Ocean':           ('#0c4a6e', '#0369a1', '#f97316', '#f2f7fa'),
    'Teal':            ('#134e4a', '#0f766e', '#eab308', '#f2f8f7'),
    'Royal Purple':    ('#4c1d95', '#6d28d9', '#f472b6', '#f7f5fb'),
    'Crimson':         ('#7f1d1d', '#b91c1c', '#f59e0b', '#faf5f5'),
    'Terracotta':      ('#9a3412', '#c2410c', '#0f766e', '#fbf7f4'),
}

# ── Field table ───────────────────────────────────────────────────────────────
# brand key → (app_settings key, env var, default, kind)
# kind: 'text' | 'color' | one of the choice dicts above
FIELDS = {
    # Company
    'name':            ('company_name',     'COMPANY_NAME',     'Your Company Name', 'text'),
    'address':         ('company_address',  'COMPANY_ADDRESS',  '', 'text'),
    'phone':           ('company_mobile',   'COMPANY_PHONE',    '', 'text'),
    'email':           ('company_email',    'COMPANY_EMAIL',    '', 'text'),
    'gstin':           ('company_gstin',    'COMPANY_GSTIN',    '', 'text'),
    'tagline':         ('company_tagline',  'COMPANY_TAGLINE',  'Interior Design & Furnishing Solutions', 'text'),
    'signatory_name':  ('signatory_name',   'SIGNATORY_NAME',   '', 'text'),
    'signatory_title': ('signatory_title',  'SIGNATORY_TITLE',  'Proprietor', 'text'),
    # Theme
    'primary':         ('theme_primary',    'BRAND_PRIMARY',    '#1a237e', 'color'),
    'secondary':       ('theme_secondary',  'BRAND_SECONDARY',  '#283593', 'color'),
    'accent':          ('theme_accent',     'BRAND_ACCENT',     '#f57f17', 'color'),
    'background':      ('theme_background', 'BRAND_BACKGROUND', '#f5f6fa', 'color'),
    'header_style':    ('theme_header',     'BRAND_HEADER',     'gradient', HEADER_STYLES),
    'corners':         ('theme_corners',    'BRAND_CORNERS',    'rounded', CORNER_STYLES),
    'buttons':         ('theme_buttons',    'BRAND_BUTTONS',    'standard', BUTTON_SHAPES),
    'font':            ('theme_font',       'BRAND_FONT',       'system', FONTS),
}

COMPANY_KEYS = ['name', 'address', 'phone', 'email', 'gstin', 'tagline', 'signatory_name', 'signatory_title']
THEME_KEYS = ['primary', 'secondary', 'accent', 'background', 'header_style', 'corners', 'buttons', 'font']

LOGO_DATA_KEY = 'logo_png'        # base64 PNG — loaded only by the logo route and PDFs
LOGO_VERSION_KEY = 'logo_version'

# Page backgrounds darker than this would make body text unreadable
MIN_BACKGROUND_LUMINANCE = 0.6


# ── Colour helpers ────────────────────────────────────────────────────────────

def _rgb(hex_color):
    return tuple(int(hex_color[i:i + 2], 16) for i in (1, 3, 5))


def tint(hex_color, amount):
    """Mix a #rrggbb colour with white. amount=0 → original, 1 → white."""
    return '#{:02x}{:02x}{:02x}'.format(*(round(c + (255 - c) * amount) for c in _rgb(hex_color)))


def luminance(hex_color):
    """WCAG relative luminance, 0 (black) – 1 (white)."""
    def channel(c):
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g_, b = (channel(c) for c in _rgb(hex_color))
    return 0.2126 * r + 0.7152 * g_ + 0.0722 * b


def readable_text_on(hex_color):
    """White or near-black, whichever contrasts more with the given background."""
    lum = luminance(hex_color)
    dark = '#111827'
    contrast_white = 1.05 / (lum + 0.05)
    contrast_dark = (lum + 0.05) / (luminance(dark) + 0.05)
    return '#ffffff' if contrast_white >= contrast_dark else dark


# ── Validation ────────────────────────────────────────────────────────────────

def clean_value(brand_key, value):
    """Return a valid value for a field, or None if the input is invalid."""
    kind = FIELDS[brand_key][3]
    value = (value or '').strip()
    if kind == 'text':
        return value
    if kind == 'color':
        return value.lower() if _HEX_RE.match(value) else None
    return value if value in kind else None


def _env_or_default(brand_key):
    _, env_name, default, _ = FIELDS[brand_key]
    value = clean_value(brand_key, os.environ.get(env_name, ''))
    return value if value else default


def env_default(brand_key):
    """The deployment-level value (env var or built-in default) — shown as placeholders in Settings."""
    return _env_or_default(brand_key)


def _logo_file():
    """LOGO_FILE env var: a path inside static/, e.g. 'brand/logo.png'. Reject anything escaping it."""
    path = (os.environ.get('LOGO_FILE') or '').strip().lstrip('/')
    if not path or '..' in path.split('/'):
        return ''
    return path


# ── Brand assembly ────────────────────────────────────────────────────────────

def build_brand(saved):
    """Merge saved admin values over env/defaults and add derived values. `saved` maps app_settings keys → values."""
    brand = {}
    for key, (app_key, _, _, _) in FIELDS.items():
        value = clean_value(key, saved.get(app_key))
        brand[key] = value if value else _env_or_default(key)
    brand['signatory_name'] = brand['signatory_name'] or brand['name']

    # Derived colours
    brand['light'] = tint(brand['primary'], 0.9)
    brand['primary_rgb'] = ', '.join(str(c) for c in _rgb(brand['primary']))
    brand['on_primary'] = readable_text_on(brand['primary'])
    brand['on_secondary'] = readable_text_on(brand['secondary'])
    brand['header_dark'] = brand['header_style'] != 'light' and brand['on_primary'] == '#ffffff'

    # Shape & type
    _, r, r_sm, r_lg, r_card = CORNER_STYLES[brand['corners']]
    brand['radius'], brand['radius_sm'], brand['radius_lg'], brand['radius_card'] = r, r_sm, r_lg, r_card
    pill = brand['buttons'] == 'pill'
    brand['btn_radius'] = '50rem' if pill else r
    brand['btn_radius_sm'] = '50rem' if pill else r_sm
    _, family, stack = FONTS[brand['font']]
    brand['font_stack'] = stack
    brand['font_url'] = (f'https://fonts.googleapis.com/css2?family={family}:wght@400;500;600;700&display=swap'
                         if family else '')

    # Logo: uploaded (DB) wins over LOGO_FILE (static)
    version = (saved.get(LOGO_VERSION_KEY) or '').strip()
    brand['logo_version'] = version
    brand['logo_file'] = '' if version else _logo_file()
    if version:
        brand['logo_url'] = url_for('main.brand_logo', v=version)
    elif brand['logo_file']:
        brand['logo_url'] = url_for('static', filename=brand['logo_file'])
    else:
        brand['logo_url'] = ''

    # Cache-buster for the favicon
    brand['theme_version'] = hashlib.sha1(brand['primary'].encode()).hexdigest()[:8]
    return brand


def get_brand():
    """The merged brand dict for this request (cached on flask.g; one settings query)."""
    if 'brand' in g:
        return g.brand

    from .models import AppSetting
    saved = {}
    try:
        keys = [f[0] for f in FIELDS.values()] + [LOGO_VERSION_KEY]
        saved = {r.key: r.value for r in AppSetting.query.filter(AppSetting.key.in_(keys)).all()}
    except Exception:
        # DB unreachable (e.g. cold start) — render with env/default values
        pass

    g.brand = build_brand(saved)
    return g.brand


def ui_options():
    """Choice lists and presets for the Settings → Appearance UI (also serialised for its JS)."""
    return {
        'header_styles': HEADER_STYLES,
        'corners': {k: v[0] for k, v in CORNER_STYLES.items()},
        'corner_values': {k: {'r': v[1], 'sm': v[2], 'lg': v[3], 'card': v[4]} for k, v in CORNER_STYLES.items()},
        'buttons': BUTTON_SHAPES,
        'fonts': {k: {'label': v[0], 'family': v[1], 'stack': v[2]} for k, v in FONTS.items()},
        'presets': {name: dict(zip(('primary', 'secondary', 'accent', 'background'), p))
                    for name, p in PRESETS.items()},
        'defaults': {k: env_default(k) for k in THEME_KEYS},
    }


# ── Logo storage ──────────────────────────────────────────────────────────────

MAX_LOGO_UPLOAD_BYTES = 2 * 1024 * 1024
MAX_LOGO_SIDE = 600


class LogoError(ValueError):
    pass


def process_logo_upload(raw):
    """
    Validate an uploaded image and normalise it to a PNG no larger than
    MAX_LOGO_SIDE on its longest side. Returns (png_bytes, version).
    Re-encoding through Pillow also strips anything that isn't pixel data.
    """
    from PIL import Image, UnidentifiedImageError

    if not raw:
        raise LogoError('No file was uploaded.')
    if len(raw) > MAX_LOGO_UPLOAD_BYTES:
        raise LogoError('Logo must be 2 MB or smaller.')
    try:
        img = Image.open(io.BytesIO(raw))
        if img.format not in ('PNG', 'JPEG', 'WEBP'):
            raise LogoError('Logo must be a PNG, JPG or WebP image.')
        if img.width * img.height > 25_000_000:
            raise LogoError('Logo image dimensions are too large.')
        img.load()
    except (UnidentifiedImageError, OSError):
        raise LogoError('That file is not a readable image.')

    img = img.convert('RGBA')
    img.thumbnail((MAX_LOGO_SIDE, MAX_LOGO_SIDE))
    out = io.BytesIO()
    img.save(out, format='PNG', optimize=True)
    png = out.getvalue()
    return png, hashlib.sha1(png).hexdigest()[:12]


def load_logo_png():
    """Uploaded logo bytes, or None."""
    from .models import AppSetting
    data = AppSetting.get(LOGO_DATA_KEY, '')
    return base64.b64decode(data) if data else None


def save_logo_png(png, version):
    from .models import AppSetting
    AppSetting.set(LOGO_DATA_KEY, base64.b64encode(png).decode())
    AppSetting.set(LOGO_VERSION_KEY, version)


def remove_logo():
    from .models import AppSetting
    AppSetting.set(LOGO_DATA_KEY, '')
    AppSetting.set(LOGO_VERSION_KEY, '')
