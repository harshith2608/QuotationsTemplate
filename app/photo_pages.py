"""Photo pages and the designed cover page.

Photo pages: full-page pictures a business puts at the front of a quotation's PDF (its own designed cover, an
About us page with photos, a gallery of past work), in the order it chooses. Shown at the top of the customer's link
too. Whether they print is the quotation's choice ("Photo pages at the front" in What should the PDF show?,
app/pdf_choices.py). Saving the quotation as a template, or duplicating it, copies them (by id: nothing is re-stored).

The designed cover page (first, when the quotation has a cover photo): the logo and firm name, the slogan and tagline
(Settings → Quotation PDFs → Cover page), the package name (the template it was started from, e.g. "DIY Package";
editable per quotation) and the quotation's cover photo. It takes the place of the presentation title page.

For businesses with Item photos or "Choose what the PDF shows" on (console → Features; the latter is on for new trials
and customers). Stored like line photos (item_images, never changed) but at
print size (PAGE_SIDE). The list per quotation is one app_settings row: quote_pages_<project> = JSON [image ids].
"""
import io
import json

PAGE_SIDE = 2200          # px on the long side: a sharp A4 page (~190 dpi)
MAX_PAGES = 12
SLOGAN_KEY, TAGLINE_KEY = 'cover_slogan', 'cover_tagline'    # Settings → Quotation PDFs → Cover page
TEXT_MAX = 120


def _cover_key(project_id):
    return f'quote_cover_{int(project_id)}'


def _package_key(project_id):
    return f'quote_package_{int(project_id)}'


# ── The designed cover page: logo, firm name, slogan, tagline, package name, the quotation's cover photo ──

def cover_photo(project_id):
    from . import item_images
    from .models import AppSetting
    try:
        i = int(AppSetting.get(_cover_key(project_id), '') or 0) if project_id else 0
    except ValueError:
        return None
    return i if i and item_images.valid_ids([i]) else None


def set_cover_photo(project_id, image_id):
    from .models import AppSetting
    AppSetting.set(_cover_key(project_id), str(int(image_id)) if image_id else '')


def package(project_id):
    from .models import AppSetting
    return (AppSetting.get(_package_key(project_id), '') or '') if project_id else ''


def set_package(project_id, name):
    from .models import AppSetting
    AppSetting.set(_package_key(project_id), ' '.join((name or '').split())[:60])


def texts():
    """{'slogan', 'tagline'} for the cover (the tagline: the company's own when none is set here)."""
    from .branding import get_brand
    from .models import AppSetting
    return {'slogan': AppSetting.get(SLOGAN_KEY, '') or '',
            'tagline': AppSetting.get(TAGLINE_KEY, '') or (get_brand().get('tagline') or '')}


def save_texts(slogan, tagline):
    from .models import AppSetting
    AppSetting.set(SLOGAN_KEY, ' '.join((slogan or '').split())[:TEXT_MAX])
    AppSetting.set(TAGLINE_KEY, ' '.join((tagline or '').split())[:TEXT_MAX])


def cover_shown(project):
    """The designed cover prints for this quotation: it has a cover photo and the quotation shows it."""
    from . import pdf_choices
    return bool(enabled() and cover_photo(project.id) and pdf_choices.for_project(project.id).get('cover', True))


def _draw_cover(c, project, photo):
    """The cover, laid out like a designed brochure page: a band in the brand colour down the left; the logo, firm
    name, slogan and tagline on white; the package name on a grey panel at the top right; the photo below."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.utils import ImageReader
    from reportlab.platypus import Paragraph
    from html import escape
    from .branding import get_brand, load_logo_png
    from .pdf_utils import _F, _ink
    pw, ph = A4
    brand = get_brand()
    dark = colors.HexColor(_ink(brand['primary']))
    t = texts()
    band = 52
    c.setFillColor(colors.white); c.rect(0, 0, pw, ph, stroke=0, fill=1)
    c.setFillColor(colors.HexColor('#e9ebee')); c.rect(pw * 0.58, ph * 0.62, pw * 0.42, ph * 0.38, stroke=0, fill=1)
    c.setFillColor(dark); c.rect(0, 0, band, ph, stroke=0, fill=1)
    x, y = band + 45, ph - 55                       # the left column, top down
    if brand.get('logo_version'):
        png = load_logo_png()
        if png:
            img = ImageReader(io.BytesIO(png))
            w, h = img.getSize()
            s = min(190 / w, 110 / h)
            c.drawImage(img, x, y - h * s, width=w * s, height=h * s, mask='auto')
            y -= h * s + 14
    name = ParagraphStyle('CvName', fontName=_F.b, fontSize=15, leading=19, textColor=dark)
    p = Paragraph(escape(brand.get('name') or ''), name)
    _, ph_ = p.wrap(pw * 0.5 - x, 200); p.drawOn(c, x, y - ph_); y -= ph_ + 26
    if t['slogan']:
        sl = ParagraphStyle('CvSlogan', fontName=_F.r, fontSize=17, leading=22, textColor=colors.HexColor('#263238'))
        p = Paragraph(escape(t['slogan'].upper()), sl)
        _, h_ = p.wrap(pw * 0.5 - x, 300); p.drawOn(c, x, y - h_); y -= h_ + 10
        c.setStrokeColor(colors.HexColor('#263238')); c.setLineWidth(1.4); c.line(x, y, x + 190, y); y -= 14
    if t['tagline']:
        tg = ParagraphStyle('CvTag', fontName=_F.r, fontSize=10.5, leading=14, textColor=colors.HexColor('#546e7a'))
        p = Paragraph(escape(t['tagline']), tg)
        _, h_ = p.wrap(min(210, pw * 0.5 - x), 200); p.drawOn(c, x, y - h_)
    pk = package(project.id)
    if pk:
        c.setFont(_F.b, 15); c.setFillColor(colors.HexColor('#111111'))
        label = pk.upper()
        tw = c.stringWidth(label, _F.b, 15)
        lx = pw - 42 - tw
        c.drawString(lx, ph - 82, label)
        c.setLineWidth(1.2); c.setStrokeColor(colors.HexColor('#111111')); c.line(lx, ph - 85, lx + tw, ph - 85)
    # the photo: filling a rounded frame (cropped to fit), the lower part of the page
    bx, by, bw, bh = band + 45, 46, pw - band - 45 - 52, ph * 0.56
    img = ImageReader(io.BytesIO(photo))
    w, h = img.getSize()
    s = max(bw / w, bh / h)
    c.saveState()
    path = c.beginPath(); path.roundRect(bx, by, bw, bh, 16)
    c.clipPath(path, stroke=0, fill=0)
    c.drawImage(img, bx + (bw - w * s) / 2, by + (bh - h * s) / 2, width=w * s, height=h * s)
    c.restoreState()
    c.showPage()


def _key(project_id):
    return f'quote_pages_{int(project_id)}'


def enabled():
    """With Item photos on, or Choose what the PDF shows (on for new trials and customers)."""
    from . import item_images, pdf_choices
    return item_images.ready() and (item_images.enabled() or pdf_choices.enabled())


def for_project(project_id):
    """[image ids] in order (only ones that still exist)."""
    from . import item_images
    from .models import AppSetting
    if not project_id:
        return []
    try:
        ids = [int(i) for i in json.loads(AppSetting.get(_key(project_id), '') or '[]')]
    except (ValueError, TypeError):
        return []
    have = item_images.valid_ids(ids) if ids else set()
    return [i for i in ids if i in have]


def set_for_project(project_id, ids):
    from .models import AppSetting
    ids = [int(i) for i in ids][:MAX_PAGES]
    AppSetting.set(_key(project_id), json.dumps(ids) if ids else '')


def add(project_id, raws):
    """Upload pictures (bytes) as pages at the end. Raises item_images.ImageError."""
    from . import item_images
    ids = for_project(project_id)
    if len(ids) + len(raws) > MAX_PAGES:
        raise item_images.ImageError(f'Up to {MAX_PAGES} photo pages on a quotation.')
    for raw in raws:
        ids.append(item_images.save_upload(raw, max_side=PAGE_SIDE).id)
    set_for_project(project_id, ids)
    return ids


def remove(project_id, image_id):
    set_for_project(project_id, [i for i in for_project(project_id) if i != int(image_id)])


def move(project_id, image_id, step):
    ids = for_project(project_id)
    if int(image_id) in ids:
        i = ids.index(int(image_id))
        j = max(0, min(len(ids) - 1, i + step))
        ids[i], ids[j] = ids[j], ids[i]
        set_for_project(project_id, ids)


def forget(project_id):
    from .models import AppSetting, db
    for k in (_key(project_id), _cover_key(project_id), _package_key(project_id)):
        row = db.session.get(AppSetting, k)
        if row:
            db.session.delete(row)


def with_pages(project, buffer):
    """The quotation PDF with its photo pages in front (each picture filling an A4 page, centred, nothing cut off),
    when the quotation shows them; else the PDF as it is."""
    from . import item_images, pdf_choices
    ids = for_project(project.id) if enabled() else []
    if not pdf_choices.for_project(project.id).get('photo_pages', True):
        ids = []
    cover = cover_photo(project.id) if cover_shown(project) else None
    if not ids and not cover:
        return buffer
    data = item_images.data_for(ids + ([cover] if cover else []))
    from pypdf import PdfReader, PdfWriter
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas
    pages = io.BytesIO()
    c = canvas.Canvas(pages, pagesize=A4)
    pw, ph = A4
    if cover and data.get(cover):
        _draw_cover(c, project, data[cover])
    for i in ids:
        if not data.get(i):
            continue
        img = ImageReader(io.BytesIO(data[i]))
        w, h = img.getSize()
        s = min(pw / w, ph / h)
        c.drawImage(img, (pw - w * s) / 2, (ph - h * s) / 2, width=w * s, height=h * s)
        c.showPage()
    c.save()
    out = PdfWriter()
    for src in (PdfReader(io.BytesIO(pages.getvalue())), PdfReader(buffer)):
        for page in src.pages:
            out.add_page(page)
    merged = io.BytesIO()
    out.write(merged)
    merged.seek(0)
    return merged
