"""How the business's PDFs look (Settings → Quotation PDFs → How your PDF looks): colours, font, header, page border and
logo watermark.

Page border: none (the default), a thin, thick or double line, or a thin line with rounded corners, in the brand colour,
20 pt in from the paper's edge, on the front page only (the title page when there is one, else page 1) or on every
page of the quotation PDFs (not invoices, not the designed photo cover or gallery, which are pictures of their own).

Logo watermark: the logo, faint, in the middle of every page of the quotation PDFs (not invoices), except the
presentation pages (title, About us, Next steps), which carry the logo already. An employee's
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


BORDER_KEY = 'pdf_border'
NO_BORDER, THIN, THICK, DOUBLE, ROUNDED = 'none', 'thin', 'thick', 'double', 'rounded'
BORDERS = {NO_BORDER: 'No border', THIN: 'Thin line', THICK: 'Thick line', DOUBLE: 'Double line',
           ROUNDED: 'Thin line with rounded corners'}
BORDER_ON_KEY = 'pdf_border_on'
FRONT, EVERY = 'front', 'every'
BORDERS_ON = {FRONT: 'Border on the front page only (your title page, or page 1)', EVERY: 'Border on every page'}
BORDER_INSET = 20         # points from the paper's edge (the text starts 1.5 cm in)


def border():
    from .models import AppSetting
    value = AppSetting.get(BORDER_KEY, '')
    return value if value in BORDERS else NO_BORDER


def border_on():
    from .models import AppSetting
    value = AppSetting.get(BORDER_ON_KEY, '')
    return value if value in BORDERS_ON else FRONT


def draw_border(c, style, colour, page_size):
    """The page border, in the brand colour (grey in black & white: the canvas turns it)."""
    w, h = page_size
    x = y = BORDER_INSET
    bw, bh = w - 2 * BORDER_INSET, h - 2 * BORDER_INSET
    c.saveState()
    c.setStrokeColor(colour)
    if style == DOUBLE:
        c.setLineWidth(1.4); c.rect(x, y, bw, bh, stroke=1, fill=0)
        c.setLineWidth(0.5); c.rect(x + 4, y + 4, bw - 8, bh - 8, stroke=1, fill=0)
    elif style == ROUNDED:
        c.setLineWidth(0.9); c.roundRect(x, y, bw, bh, 12, stroke=1, fill=0)
    else:
        c.setLineWidth(2.4 if style == THICK else 0.9); c.rect(x, y, bw, bh, stroke=1, fill=0)
    c.restoreState()


def border_canvas_class(style, every, colour, base=None):
    """A canvas that draws the border on each finished page (every) or the first one only."""
    if base is None:
        from reportlab.pdfgen.canvas import Canvas as base

    class BorderCanvas(base):
        def showPage(self):
            if every or self.getPageNumber() == 1:
                draw_border(self, style, colour, self._pagesize)
            super().showPage()

    return BorderCanvas


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


def no_logo_mark():
    """A flowable that takes nothing and keeps the logo watermark off the page it's on (the title, About us and Next
    steps pages: they carry the logo already)."""
    from reportlab.platypus import Flowable

    class NoLogoMark(Flowable):
        def wrap(self, *args):
            return 0, 0

        def draw(self):
            self.canv._no_logo_mark = True

    return NoLogoMark()


def logo_canvas_class(image, base=None):
    """A canvas that puts `image` (logo_mark_image) in the middle of each finished page, over the content (faint
    enough to read through, and seen over shaded tables too)."""
    if base is None:
        from reportlab.pdfgen.canvas import Canvas as base
    iw, ih = image.getSize()

    class LogoMarkCanvas(base):
        def showPage(self):
            if getattr(self, '_no_logo_mark', False):       # a presentation page (NoLogoMark on it): left clean
                self._no_logo_mark = False
                super().showPage()
                return
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
                                         ('pdf_header', HEADER_KEY, HEADERS, CENTRE), ('pdf_border', BORDER_KEY, BORDERS, NO_BORDER),
                                         ('pdf_border_on', BORDER_ON_KEY, BORDERS_ON, FRONT)):
        if form.get(field) in choices:
            AppSetting.set(key, '' if form[field] == default else form[field])


def choices():
    """For the Settings card: [(field, title, {key: label}, chosen)]."""
    return [('pdf_colours', 'Colours', COLOURS, colours()), ('pdf_font', 'Font', FONTS, font()),
            ('pdf_header', 'Header', HEADERS, header()), ('pdf_border', 'Page border', BORDERS, border()),
            ('pdf_border_on', 'Where the border goes', BORDERS_ON, border_on())]


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
