"""How the business's PDFs look (Settings → Quotation PDFs → How your PDF looks): colours, font, header and logo watermark.

Logo watermark: the logo, faint, in the middle of every page of the quotation PDFs (not invoices). An employee's
quotation gets it once the admin approves it (before that it opens marked Draft instead); an admin's always.

Font: modern (Helvetica, as before) or classic (Times, a serif). The PDF code asks for its fonts here when it builds
(app/pdf_utils.py _F and _styles); the canvas also swaps any Helvetica it is still given (plain table cells, the demo
watermark), so the whole page is in one font.

Header: logo, name and details centred (as before), or the logo on the left and the details on the right.

Colours: their brand colours (Settings → Appearance, as before) or black & white. Black & white is applied while each
page is drawn (a reportlab canvas whose colour hook turns every colour grey), so text, lines, table shading and the
colours from the rich text editor all follow without each table knowing about it; dark colours become pure black so
text prints crisp. Photos and the logo are left as they are. Covers the quotation PDFs (both), revisions and invoices.
"""
COLOURS_KEY = 'pdf_colours'
BRAND, BW = 'brand', 'bw'
COLOURS = {BRAND: 'Your brand colours (from Appearance)', BW: 'Black & white: black text and lines, grey shading'}
BLACK_BELOW = 0.35        # luminance under this prints as pure black

FONT_KEY = 'pdf_font'
MODERN, CLASSIC = 'modern', 'classic'
FONTS = {MODERN: 'Modern (clean, without serifs)', CLASSIC: 'Classic (with serifs, like a printed letter)'}
_FACES = {MODERN: {'r': 'Helvetica', 'b': 'Helvetica-Bold', 'i': 'Helvetica-Oblique', 'bi': 'Helvetica-BoldOblique'},
          CLASSIC: {'r': 'Times-Roman', 'b': 'Times-Bold', 'i': 'Times-Italic', 'bi': 'Times-BoldItalic'}}

HEADER_KEY = 'pdf_header'
CENTRE, LEFT = 'centre', 'left'
HEADERS = {CENTRE: 'Logo and details in the centre', LEFT: 'Logo on the left, your name and details on the right'}


def colours():
    from .models import AppSetting
    value = AppSetting.get(COLOURS_KEY, '')
    return value if value in COLOURS else BRAND


def font():
    from .models import AppSetting
    value = AppSetting.get(FONT_KEY, '')
    return value if value in FONTS else MODERN


def fonts():
    """{'r', 'b', 'i', 'bi'}: the PDF font's regular, bold, italic and bold italic."""
    return _FACES[font()]


def font_for(name):
    """A Helvetica face as the same face of the business's font (anything else as it is)."""
    for k, face in _FACES[MODERN].items():
        if name == face:
            return fonts()[k]
    return name


def header():
    from .models import AppSetting
    value = AppSetting.get(HEADER_KEY, '')
    return value if value in HEADERS else CENTRE


LOGO_MARK_KEY = 'pdf_logo_mark'   # '1': the firm's logo, faint, in the middle of every quotation page
LOGO_MARK_OPACITY = 0.08


def logo_mark():
    from .models import AppSetting
    return AppSetting.get(LOGO_MARK_KEY, '') == '1'


def logo_mark_image():
    """The logo (Settings → Company, or another company's on its quotations), faded, for the watermark; None without
    one. Its transparency is kept, so only the logo shows."""
    import os
    from io import BytesIO
    from flask import current_app
    from PIL import Image
    from reportlab.lib.utils import ImageReader
    from .branding import get_brand, load_logo_png
    brand = get_brand()
    try:
        if brand.get('logo_version'):
            png = load_logo_png()
            if not png:
                return None
            img = Image.open(BytesIO(png))
        elif brand.get('logo_file'):
            img = Image.open(os.path.join(current_app.static_folder, brand['logo_file']))
        else:
            return None
        img = img.convert('RGBA')
        img.putalpha(img.getchannel('A').point(lambda a: int(a * LOGO_MARK_OPACITY)))
        return ImageReader(img)
    except Exception:
        current_app.logger.warning('Logo could not be loaded for the PDF watermark.')
        return None


def logo_canvas_class(image, base=None):
    """A canvas that puts `image` (logo_mark_image) in the middle of each finished page, over the content (faint
    enough to read through, and seen over shaded tables too)."""
    if base is None:
        from reportlab.pdfgen.canvas import Canvas as base
    iw, ih = image.getSize()

    class LogoMarkCanvas(base):
        def showPage(self):
            w, h = self._pagesize
            scale = min(0.6 * w / iw, 0.35 * h / ih)
            dw, dh = iw * scale, ih * scale
            self.saveState()
            self.drawImage(image, (w - dw) / 2, (h - dh) / 2, dw, dh, mask='auto')
            self.restoreState()
            super().showPage()

    return LogoMarkCanvas


def save(form):
    """From Settings → Quotation PDFs (the defaults are stored as empty)."""
    from .models import AppSetting
    if 'pdf_logo_mark' in form:
        AppSetting.set(LOGO_MARK_KEY, '1' if '1' in form.getlist('pdf_logo_mark') else '')
    for field, key, choices, default in (('pdf_colours', COLOURS_KEY, COLOURS, BRAND), ('pdf_font', FONT_KEY, FONTS, MODERN),
                                         ('pdf_header', HEADER_KEY, HEADERS, CENTRE)):
        if form.get(field) in choices:
            AppSetting.set(key, '' if form[field] == default else form[field])


def choices():
    """For the Settings card: [(field, title, {key: label}, chosen)]."""
    return [('pdf_colours', 'Colours', COLOURS, colours()), ('pdf_font', 'Font', FONTS, font()),
            ('pdf_header', 'Header', HEADERS, header())]


def grey(colour):
    """Any reportlab colour (Color, CMYK, hex/name string, RGB or CMYK tuple) as black or a grey of the same lightness."""
    from reportlab.lib import colors
    c = colour
    if isinstance(c, str):
        c = colors.toColor(c)
    elif isinstance(c, (tuple, list)):
        c = colors.Color(*c) if len(c) == 3 else colors.CMYKColor(*c)
    lum = 0.299 * c.red + 0.587 * c.green + 0.114 * c.blue
    v = 0 if lum < BLACK_BELOW else round(lum, 3)
    return colors.Color(v, v, v, alpha=getattr(c, 'alpha', None))


def canvas_class(base=None):
    """The canvas to build with: `base` (or reportlab's) as is, or one that turns every colour grey (black & white)
    and / or sets Helvetica in the business's font."""
    bw, swap = colours() == BW, font() != MODERN
    if not (bw or swap):
        return base
    if base is None:
        from reportlab.pdfgen.canvas import Canvas as base

    class LookCanvas(base):
        def __init__(self, *args, **kwargs):
            if swap:
                kwargs['initialFontName'] = fonts()['r']      # each page starts in it (the doc template passes None)
            super().__init__(*args, **kwargs)
            if bw:
                self._enforceColorSpace = grey      # read by setFillColor / setStrokeColor here and in text objects

        def setFont(self, psfontname, size, leading=None):
            super().setFont(font_for(psfontname) if swap else psfontname, size, leading)

    return LookCanvas
