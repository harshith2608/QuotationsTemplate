"""The business's own app icon and web app manifest, for "Add to Home screen" on Android and iPhone.

The icon is the uploaded logo centred on white (within the middle 60%, so round icon masks never cut it), or the
business's initials on its primary colour when there is no logo. Full-bleed squares: the phone rounds the corners
itself. Built with Pillow (already installed for logos and ReportLab) and cached per logo/colour version.
"""
import io

from .branding import get_brand, load_logo_png

SIZES = (180, 192, 512)
_cache = {}


def initials(name):
    words = [w for w in (name or '').replace('&', ' ').split() if w[:1].isalnum()]
    return ''.join(w[0] for w in words[:2]).upper() or 'Q'


def _logo_bytes(brand):
    if brand.get('logo_version'):
        return load_logo_png()
    if brand.get('logo_file'):
        import os
        from flask import current_app
        path = os.path.join(current_app.static_folder, brand['logo_file'])
        if os.path.isfile(path):
            with open(path, 'rb') as f:
                return f.read()
    return None


def icon_png(size):
    """PNG bytes for a square icon of `size` pixels (one of SIZES)."""
    from PIL import Image, ImageDraw, ImageFont
    brand = get_brand()
    key = (brand.get('logo_version') or brand.get('logo_file') or '', brand['primary'], brand['name'], size)
    if key in _cache:
        return _cache[key]
    logo = _logo_bytes(brand)
    img = None
    if logo:
        try:
            mark = Image.open(io.BytesIO(logo)).convert('RGBA')
            img = Image.new('RGBA', (size, size), (255, 255, 255, 255))
            mark.thumbnail((int(size * 0.6), int(size * 0.6)), Image.LANCZOS)     # inside the round "maskable" safe zone
            img.alpha_composite(mark, ((size - mark.width) // 2, (size - mark.height) // 2))
        except OSError:
            img = None
    if img is None:
        img = Image.new('RGBA', (size, size), brand['primary'])
        text = initials(brand['name'])
        font = ImageFont.load_default(size=int(size * (0.42 if len(text) > 1 else 0.5)))
        ImageDraw.Draw(img).text((size / 2, size / 2), text, font=font, fill=brand['on_primary'], anchor='mm')
    out = io.BytesIO()
    img.convert('RGB').save(out, format='PNG', optimize=True)
    if len(_cache) > 200:
        _cache.clear()
    _cache[key] = out.getvalue()
    return _cache[key]


def manifest(icon_url):
    """The web app manifest: the business's name, colours and icon; opens on the quotations list."""
    brand = get_brand()
    name = brand['name']
    return {
        'name': name,
        'short_name': name,
        'start_url': '/projects',
        'scope': '/',
        'display': 'standalone',
        'background_color': brand['background'],
        'theme_color': brand['primary'],
        'icons': [{'src': icon_url(s), 'sizes': f'{s}x{s}', 'type': 'image/png', 'purpose': 'any'} for s in (192, 512)]
                 + [{'src': icon_url(512), 'sizes': '512x512', 'type': 'image/png', 'purpose': 'maskable'}],
    }
