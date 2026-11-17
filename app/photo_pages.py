"""Photo pages: full-page pictures a business puts at the front of a quotation's PDF (its own designed cover, an
About us page with photos, a gallery of past work), in the order it chooses. Shown at the top of the customer's link
too. Whether they print is the quotation's choice ("Photo pages at the front" in What should the PDF show?,
app/pdf_choices.py). Saving the quotation as a template, or duplicating it, copies them (by id: nothing is re-stored).

For businesses with Item photos on (console → Features). Stored like line photos (item_images, never changed) but at
print size (PAGE_SIDE). The list per quotation is one app_settings row: quote_pages_<project> = JSON [image ids].
"""
import io
import json

PAGE_SIDE = 2200          # px on the long side: a sharp A4 page (~190 dpi)
MAX_PAGES = 12


def _key(project_id):
    return f'quote_pages_{int(project_id)}'


def enabled():
    from . import item_images
    return item_images.enabled()


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
    row = db.session.get(AppSetting, _key(project_id))
    if row:
        db.session.delete(row)


def with_pages(project, buffer):
    """The quotation PDF with its photo pages in front (each picture filling an A4 page, centred, nothing cut off),
    when the quotation shows them; else the PDF as it is."""
    from . import item_images, pdf_choices
    ids = for_project(project.id) if enabled() else []
    if not ids or not pdf_choices.for_project(project.id).get('photo_pages', True):
        return buffer
    data = item_images.data_for(ids)
    from pypdf import PdfReader, PdfWriter
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas
    pages = io.BytesIO()
    c = canvas.Canvas(pages, pagesize=A4)
    pw, ph = A4
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
