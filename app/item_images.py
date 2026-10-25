"""Photos on quotation lines: a reference image for an item (a sofa, a chair, a wardrobe design), shown next to it on
the quotation page, the PDF and the customer's link. Optional on every line; turned on per business from the console
(Features → Item photos), off by default.

A photo is uploaded from the quotation form (one per line), checked and re-encoded by Pillow (anything that isn't
pixels is dropped), resized to MAX_SIDE and stored once as a JPEG in item_images. It is never changed: a line, a copied
quotation, a starting quotation or a revision points to it by id (items.image_id), so copying copies no bytes.
Needs the database update that adds item_images and items.image_id (ready()).
"""
import io

from flask import g, has_app_context

from . import db

KEY = 'feature_item_images'
MAX_UPLOAD_BYTES = 8 * 1024 * 1024        # phone photos are 2-6 MB
MAX_SIDE = 900                            # px: sharp in a PDF row, small in the database (~60-120 KB)
THUMB_PDF_CM = 2.2

_ready_forever = {}


class ImageError(ValueError):
    pass


def ready():
    """False until the database update that adds item_images and items.image_id has run (checked once per request)."""
    from . import tenancy
    schema = tenancy.current_schema()
    if _ready_forever.get(schema):
        return True
    if has_app_context() and '_img_ready' in g:
        return g._img_ready
    found = _tables_ready(schema)
    if found:
        _ready_forever[schema] = True
    if has_app_context():
        g._img_ready = found
    return found


def _tables_ready(schema):
    from sqlalchemy import inspect
    try:
        insp = inspect(db.session.connection())
        return 'image_id' in {c['name'] for c in insp.get_columns('items', schema=schema)} \
            and insp.has_table('item_images', schema=schema)
    except Exception:
        return False


def enabled():
    """Photos on lines are on for this business (and its database is ready for them)."""
    from .models import AppSetting
    return AppSetting.get(KEY, '') == '1' and ready()


def console_status():
    """{'ready', 'on'} checked afresh (the console opens many businesses in one process)."""
    from . import tenancy
    from .models import AppSetting
    return {'ready': _tables_ready(tenancy.current_schema()), 'on': AppSetting.get(KEY, '') == '1'}


def set_enabled(on):
    from .models import AppSetting
    AppSetting.set(KEY, '1' if on else '')


def save_upload(raw):
    """Check and store an uploaded photo. Returns the new ItemImage. Raises ImageError."""
    from PIL import Image, ImageOps, UnidentifiedImageError
    from .models import ItemImage
    if not raw:
        raise ImageError('Choose a photo.')
    if len(raw) > MAX_UPLOAD_BYTES:
        raise ImageError('The photo must be 8 MB or smaller.')
    try:
        img = Image.open(io.BytesIO(raw))
        if img.format not in ('PNG', 'JPEG', 'WEBP', 'MPO'):
            raise ImageError('Use a JPG, PNG or WebP photo.')
        if img.width * img.height > 50_000_000:
            raise ImageError('That photo is too large.')
        img.load()
    except (UnidentifiedImageError, OSError):
        raise ImageError("That file isn't a readable photo.")
    img = ImageOps.exif_transpose(img)                # phone photos: the right way up
    if img.mode in ('RGBA', 'LA', 'P'):
        img = img.convert('RGBA')
        bg = Image.new('RGB', img.size, (255, 255, 255))   # transparent PNG → white background
        bg.paste(img, mask=img.split()[-1])
        img = bg
    else:
        img = img.convert('RGB')
    img.thumbnail((MAX_SIDE, MAX_SIDE))
    out = io.BytesIO()
    img.save(out, format='JPEG', quality=82, optimize=True, progressive=True)
    row = ItemImage(data=out.getvalue(), mime='image/jpeg', width=img.width, height=img.height)
    db.session.add(row)
    db.session.flush()
    return row


def valid_id(value):
    """An image id from the form, if it exists (None otherwise)."""
    from .models import ItemImage
    try:
        i = int(value)
    except (TypeError, ValueError):
        return None
    return i if i > 0 and db.session.query(ItemImage.id).filter_by(id=i).first() else None


def valid_ids(values):
    """The ids among `values` that exist, in one query."""
    from .models import ItemImage
    ids = set()
    for v in values:
        try:
            if int(v) > 0:
                ids.add(int(v))
        except (TypeError, ValueError):
            pass
    if not ids:
        return set()
    return {i for (i,) in db.session.query(ItemImage.id).filter(ItemImage.id.in_(ids)).all()}


def data_for(ids):
    """{id: jpeg bytes} for the PDF, in one query."""
    from sqlalchemy.orm import undefer
    from .models import ItemImage
    ids = {i for i in ids if i}
    if not ids or not ready():
        return {}
    return {r.id: r.data for r in ItemImage.query.options(undefer(ItemImage.data)).filter(ItemImage.id.in_(ids)).all()}


def pdf_image(data, max_w_cm=THUMB_PDF_CM, max_h_cm=THUMB_PDF_CM):
    """A reportlab Image that fits in a max_w × max_h box (keeps its proportions), or None."""
    from reportlab.lib.units import cm
    from reportlab.platypus import Image as RLImage
    from reportlab.lib.utils import ImageReader
    if not data:
        return None
    try:
        w, h = ImageReader(io.BytesIO(data)).getSize()
    except Exception:
        return None
    scale = min(max_w_cm * cm / w, max_h_cm * cm / h)
    return RLImage(io.BytesIO(data), width=w * scale, height=h * scale)


LIBRARY_LIMIT = 300


def library(limit=LIBRARY_LIMIT):
    """[{'id', 'names': [item names it's on, most used first]}] newest first, for "My photos" (two queries)."""
    from .models import Item, ItemImage
    rows = db.session.query(ItemImage.id).order_by(ItemImage.id.desc()).limit(limit).all()
    ids = [r[0] for r in rows]
    if not ids:
        return []
    counts = {}
    for image_id, name in db.session.query(Item.image_id, Item.name).filter(Item.image_id.in_(ids)):
        per = counts.setdefault(image_id, {})
        key = (name or '').strip()
        if key:
            per[key] = per.get(key, 0) + 1
    return [{'id': i, 'names': [n for n, _ in sorted(counts.get(i, {}).items(), key=lambda kv: -kv[1])][:3]}
            for i in ids]
