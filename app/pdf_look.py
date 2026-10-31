"""How the business's PDFs look (Settings → Quotation PDFs → How your PDF looks).

Colours: their brand colours (Settings → Appearance, as before) or black & white. Black & white is applied while each
page is drawn (a reportlab canvas whose colour hook turns every colour grey), so text, lines, table shading and the
colours from the rich text editor all follow without each table knowing about it; dark colours become pure black so
text prints crisp. Photos and the logo are left as they are. Covers the quotation PDFs (both), revisions and invoices.
"""
COLOURS_KEY = 'pdf_colours'
BRAND, BW = 'brand', 'bw'
COLOURS = {BRAND: 'Your brand colours (from Appearance)', BW: 'Black & white: black text and lines, grey shading'}
BLACK_BELOW = 0.35        # luminance under this prints as pure black


def colours():
    from .models import AppSetting
    value = AppSetting.get(COLOURS_KEY, '')
    return value if value in COLOURS else BRAND


def save(form):
    from .models import AppSetting
    if form.get('pdf_colours') in COLOURS:
        AppSetting.set(COLOURS_KEY, '' if form['pdf_colours'] == BRAND else form['pdf_colours'])


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
    """The canvas to build with: `base` (or reportlab's) as is, or turning every colour grey for black & white."""
    if colours() != BW:
        return base
    if base is None:
        from reportlab.pdfgen.canvas import Canvas as base

    class GreyCanvas(base):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._enforceColorSpace = grey      # read by setFillColor / setStrokeColor here and in text objects

    return GreyCanvas
