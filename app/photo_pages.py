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


def _opts_key(project_id):
    return f'quote_photo_opts_{int(project_id)}'


def printing(project_id):
    """{'cover', 'gallery'}: whether this quotation prints them (ticked on the quotation's card; both by default)."""
    from .models import AppSetting
    try:
        saved = json.loads(AppSetting.get(_opts_key(project_id), '') or '{}') if project_id else {}
    except ValueError:
        saved = {}
    return {'cover': saved.get('cover', True) is not False, 'gallery': saved.get('gallery', True) is not False}


def set_printing(project_id, cover, gallery):
    from .models import AppSetting
    AppSetting.set(_opts_key(project_id), json.dumps({'cover': bool(cover), 'gallery': bool(gallery)}))


def cover_shown(project):
    """The designed cover prints for this quotation: it has a cover photo and "Print the cover" is ticked."""
    return bool(enabled() and cover_photo(project.id) and printing(project.id)['cover'])


def gallery_shown(project):
    return enabled() and printing(project.id)['gallery']


def details(project):
    """[(label, value)] for the cover: who it's for, its number (QT-016/Rev5, unless the business keeps it off the PDF),
    who made it, its date and (Settings → Quotation PDFs → Validity)
    how long it's valid; Valid until left out when that's empty."""
    from datetime import timedelta
    from . import layout
    dated = project.created_at
    from . import quote_numbers
    number = quote_numbers.for_pdf(project) if quote_numbers.on_pdf() else ''
    rows = [('Prepared for', project.customer_name or ''),
            ('Quotation No', number),
            ('Prepared by', project.creator.display_name if project.creator else ''),
            ('Date', (dated + timedelta(hours=5, minutes=30)).strftime('%d %B %Y') if dated else '')]
    until = layout.valid_until(dated)
    if until:
        rows.append(('Valid until', until.strftime('%d %B %Y')))
    return [(k, v) for k, v in rows if v]


def _draw_details(c, project, dark, x, bottom, width, top):
    """The quotation's details in the grey panel, from its bottom up (above them: the package name)."""
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import Paragraph
    from html import escape
    from .pdf_utils import _F
    label = ParagraphStyle('CvDL', fontName=_F.b, fontSize=7.5, leading=9, textColor=colors.HexColor('#78909c'))
    value = ParagraphStyle('CvDV', fontName=_F.b, fontSize=11, leading=14, textColor=dark)
    first = ParagraphStyle('CvDF', parent=value, fontSize=14, leading=17)
    blocks = []
    for i, (k, v) in enumerate(details(project)):
        lp, vp = Paragraph(escape(k.upper()), label), Paragraph(escape(v), first if i == 0 else value)
        _, lh = lp.wrap(width, 50)
        _, vh = vp.wrap(width, 80)
        blocks.append((lp, lh, vp, vh))
    y = bottom + sum(lh + vh + 2 + 10 for _, lh, _, vh in blocks) - 10
    y = min(y, top)
    c.setStrokeColor(dark); c.setLineWidth(2); c.line(x, y + 8, x + 28, y + 8)
    for lp, lh, vp, vh in blocks:
        lp.drawOn(c, x, y - lh); y -= lh + 2
        vp.drawOn(c, x, y - vh); y -= vh + 10


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
    _draw_details(c, project, dark, pw * 0.58 + 26, ph * 0.62 + 24, pw * 0.42 - 26 - 42, ph - 110)
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


SWITCH_KEY = 'feature_photo_pages'      # the operator's switch (console → Features → Cover & gallery)


def enabled():
    """On for this business (on for new trials and customers; console → Features), and its database is ready."""
    from . import item_images
    from .models import AppSetting
    return AppSetting.get(SWITCH_KEY, '') == '1' and item_images.ready()


def set_enabled(on):
    from .models import AppSetting
    AppSetting.set(SWITCH_KEY, '1' if on else '')


def console_status():
    from .models import AppSetting
    return {'on': AppSetting.get(SWITCH_KEY, '') == '1'}


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
    for k in (_key(project_id), _cover_key(project_id), _package_key(project_id), _opts_key(project_id)):
        row = db.session.get(AppSetting, k)
        if row:
            db.session.delete(row)


GALLERY_PER_ROW = 3           # at most this many photos side by side
GALLERY_ROWS = 3              # rows on a page (at most)
GALLERY_GAP = 9               # pt between photos
GALLERY_MARGIN = 36           # pt round the page


def gallery_layout(sizes, width, height):
    """Photos (their (w, h) in order) laid out like a photo book: rows of 2 or 3 sized by their shapes, each row
    exactly the page's width with no cropping, up to GALLERY_ROWS rows a page. Returns pages: [[(index, x, y, w, h)]]
    with y from the top of the content area. A last row of one or two isn't stretched taller than a normal row."""
    row_h_target = (height - GALLERY_GAP * (GALLERY_ROWS - 1)) / GALLERY_ROWS
    rows, cur = [], []
    for i, (w, h) in enumerate(sizes):
        cur.append((i, w / h))
        aspects = sum(a for _, a in cur)
        # a row is full at 3 photos, or at 2 when they're wide (landscapes) and already fill the width
        if len(cur) == GALLERY_PER_ROW or (len(cur) >= 2 and aspects * row_h_target >= width - GALLERY_GAP * (len(cur) - 1)):
            rows.append(cur)
            cur = []
    if cur:
        rows.append(cur)
    pages, page, used = [], [], 0.0
    for k, row in enumerate(rows):
        gaps = GALLERY_GAP * (len(row) - 1)
        aspects = sum(a for _, a in row)
        h = (width - gaps) / aspects                   # the row's height when it spans the width exactly
        last = k == len(rows) - 1
        if last and h > row_h_target * 1.15:           # a short last row: a normal height, not stretched
            h = row_h_target * 1.15
        h = min(h, height)
        if page and (used + h > height + 0.5 or len(page) == GALLERY_ROWS):
            pages.append([p for r in page for p in r])
            page, used = [], 0.0
        row_w = sum(a * h for _, a in row) + gaps
        x = (width - row_w) / 2
        placed = []
        for i, a in row:
            placed.append((i, x, used, a * h, h))
            x += a * h + GALLERY_GAP
        page.append(placed)
        used += h + GALLERY_GAP
    if page:
        pages.append([p for r in page for p in r])
    return pages


def _draw_gallery(c, photos):
    """The gallery pages: the photos (jpeg bytes, in order) laid out by gallery_layout, rounded corners."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.utils import ImageReader
    pw, ph = A4
    imgs = [ImageReader(io.BytesIO(d)) for d in photos]
    width, height = pw - 2 * GALLERY_MARGIN, ph - 2 * GALLERY_MARGIN
    for page in gallery_layout([im.getSize() for im in imgs], width, height):
        rows_h = max(y + h for _, _, y, _, h in page)
        top = ph - GALLERY_MARGIN - (height - rows_h) / 2     # the photos centred on the page
        for i, x, y, w, h in page:
            px, py = GALLERY_MARGIN + x, top - y - h
            c.saveState()
            path = c.beginPath(); path.roundRect(px, py, w, h, 8)
            c.clipPath(path, stroke=0, fill=0)
            c.drawImage(imgs[i], px, py, width=w, height=h)
            c.restoreState()
        c.showPage()


def with_pages(project, buffer):
    """The quotation PDF with its designed cover and photo gallery in front (when the quotation prints them); else the
    PDF as it is."""
    from . import item_images
    ids = for_project(project.id) if gallery_shown(project) else []
    cover = cover_photo(project.id) if cover_shown(project) else None
    if not ids and not cover:
        return buffer
    data = item_images.data_for(ids + ([cover] if cover else []))
    from pypdf import PdfReader, PdfWriter
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    pages = io.BytesIO()
    c = canvas.Canvas(pages, pagesize=A4)
    if cover and data.get(cover):
        _draw_cover(c, project, data[cover])
    photos = [data[i] for i in ids if data.get(i)]
    if photos:
        _draw_gallery(c, photos)
    c.save()
    out = PdfWriter()
    for src in (PdfReader(io.BytesIO(pages.getvalue())), PdfReader(buffer)):
        for page in src.pages:
            out.add_page(page)
    merged = io.BytesIO()
    out.write(merged)
    merged.seek(0)
    return merged
