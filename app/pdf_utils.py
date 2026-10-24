import os
from datetime import timedelta
from io import BytesIO
from xml.sax.saxutils import escape
from flask import current_app
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                 TableStyle, HRFlowable, Image, KeepTogether)
from reportlab.lib.utils import ImageReader
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from . import db
from .models import AppSetting
from .catalog import BOQ_ITEMS_LABEL, FIXED_ITEMS_LABEL
from . import materials as M
from . import units
from .branding import get_brand, tint, luminance, readable_text_on, load_logo_png


DEFAULT_TERMS = (
    "1. This is a preliminary estimate. Final price may vary based on site conditions and material selection.\n"
    "2. This quotation is valid for 30 days from the date of issue.\n"
    "3. A 50% advance payment is required to commence work.\n"
    "4. Delivery and installation timelines will be communicated separately.\n"
    "5. Any changes to design or material after order confirmation may attract additional charges."
)


def terms_text():
    """The business's Terms & Conditions. The defaults only until they first save the setting; once saved, an empty
    box means no Terms & Conditions (the section is left out)."""
    row = db.session.get(AppSetting, 'terms_conditions')
    return DEFAULT_TERMS if row is None else (row.value or '')


def _get_terms_lines():
    """T&C as a list of non-empty lines."""
    return [l.strip() for l in terms_text().splitlines() if l.strip()]


def ft_in(decimal_ft):
    """A stored size (decimal feet) in the business's unit (Settings → Units)."""
    from . import units
    return units.length(decimal_ft) or '—'


GREY_BG = colors.HexColor('#f5f5f5')


def _money(value, spec=',.2f'):
    """Format an amount. In the public demo, amounts are deliberately wrong (see demo.scramble_amount)."""
    from .demo import demo_enabled, scramble_amount
    return format(scramble_amount(value) if demo_enabled() else value, spec)


def _build(doc, elements):
    """Build the PDF, adding the demo notice and watermark on every page when DEMO_MODE is on."""
    from .demo import demo_enabled, demo_notice_flowable, watermark_canvas_class
    if demo_enabled():
        doc.build([demo_notice_flowable(doc.width)] + list(elements), canvasmaker=watermark_canvas_class())
    else:
        doc.build(elements)


def _ink(hex_color):
    """Darken a colour until it reads well as text on white paper (WCAG ≥ 4.5:1)."""
    amount = 0.0
    shade = hex_color
    while 1.05 / (luminance(shade) + 0.05) < 4.5 and amount < 1:
        amount += 0.1
        r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
        shade = '#{:02x}{:02x}{:02x}'.format(*(round(c * (1 - amount)) for c in (r, g, b)))
    return shade


def _palette():
    """
    PDF colours from the current theme (Admin → Settings → Appearance):
    (BRAND_DARK, BRAND_ACCENT, BRAND_LIGHT, TABLE_HEADER_BG, ROOM_HEADER_BG,
     TABLE_HEADER_FG, TOTAL_ROW_BG, ON_BRAND)
    BRAND_DARK is the primary colour, darkened if needed so text stays legible.
    """
    brand = get_brand()
    primary = brand['primary']
    dark = colors.HexColor(_ink(primary))
    room_bg = colors.HexColor(tint(primary, 0.75))
    return (dark,
            colors.HexColor(brand['accent']),
            colors.HexColor(tint(primary, 0.9)),
            colors.HexColor(tint(primary, 0.85)),
            room_bg,
            dark,
            room_bg,
            colors.HexColor(readable_text_on(_ink(primary))))


def _logo_flowable(brand, max_height=1.6 * cm, max_width=6 * cm):
    """Logo uploaded in Settings (stored in the DB), else LOGO_FILE under static/, else None."""
    source = None
    if brand.get('logo_version'):
        png = load_logo_png()
        source = BytesIO(png) if png else None
    elif brand.get('logo_file'):
        source = os.path.join(current_app.static_folder, brand['logo_file'])
    if source is None:
        return None
    try:
        w, h = ImageReader(source).getSize()
        if isinstance(source, BytesIO):
            source.seek(0)
    except Exception:
        current_app.logger.warning('Logo could not be loaded for PDF.')
        return None
    scale = min(max_height / h, max_width / w)
    return Image(source, width=w * scale, height=h * scale)


def _header_elements(title_style, subtitle_style, accent):
    """Logo, company name, contact line and accent rule shared by both PDFs."""
    brand = get_brand()
    elements = []
    logo = _logo_flowable(brand)
    if logo:
        elements += [logo, Spacer(1, 4)]
    elements.append(Paragraph(escape(brand['name']), title_style))
    parts = []
    if brand['address']: parts.append(brand['address'].replace('\n', ', '))
    if brand['phone']:   parts.append(f"Ph: {brand['phone']}")
    if brand['email']:   parts.append(brand['email'])
    subtitle = '  |  '.join(parts) if parts else brand['tagline']
    elements.append(Paragraph(escape(subtitle), subtitle_style))
    if brand['gstin']:
        elements.append(Paragraph(f"GSTIN: {escape(brand['gstin'])}", subtitle_style))
    elements.append(HRFlowable(width='100%', thickness=2, color=accent, spaceAfter=8))
    return elements


def _thank_you_text():
    return (f"Thank you for choosing <b>{escape(get_brand()['name'])}</b>. "
            "We look forward to transforming your space!")


def _quote_ref(project):
    """'Quotation #: 12 · Rev 3\nDate: …' for the PDF header (the revision once revisions are kept)."""
    from .billing import latest_revision_number
    rev = latest_revision_number(project)
    return (f'Quotation #: {project.id}' + (f'  ·  Rev {rev}' if rev and rev > 1 else '')
            + f'\nDate: {(project.created_at + timedelta(hours=5, minutes=30)).strftime("%d %B %Y")}')


def _section_elements(styles, dark, project=None, rooms=None):
    """Material Specifications, Payment Terms, Delivery Terms, Important Notes and Terms & Conditions
    (Settings → Quotation PDFs): each a numbered list, empty ones left out."""
    from . import layout
    head = ParagraphStyle('SecHead', parent=styles['Normal'], fontSize=9, textColor=dark,
                          fontName='Helvetica-Bold', spaceBefore=4, spaceAfter=4)
    body = ParagraphStyle('SecBody', parent=styles['Normal'], fontSize=8, textColor=colors.HexColor('#333333'),
                          leading=12, leftIndent=12, firstLineIndent=-12, spaceAfter=1.5)
    settings = AppSetting.get_many([k for k, _ in layout.SECTION_KEYS])
    out = []
    values = layout.variables(project, rooms) if project is not None else None
    for title, lines in layout.sections(settings, _get_terms_lines(), values):
        points = [Paragraph(f'{i}.&nbsp;&nbsp;{escape(line)}', body) for i, line in enumerate(lines, 1)]
        out.append(KeepTogether([HRFlowable(width='100%', thickness=1, color=colors.HexColor('#bdbdbd'), spaceAfter=6),
                                 Paragraph(escape(title), head)] + points[:1]))   # the heading stays with its first point
        out += points[1:]
        out.append(Spacer(1, 10))
    return out


def _with_thanks(elements, paragraph):
    """End the PDF with the thank-you line kept on the same page as what comes before it."""
    tail = []
    while elements and isinstance(elements[-1], Spacer):        # the gap after the last section
        tail.insert(0, elements.pop())
    last = elements.pop() if elements else None
    elements.append(KeepTogether(([last] if last is not None else []) + tail + [Spacer(1, 8), paragraph]))


def _room_rows_elements(project, page_width, palette, styles):
    """The room-by-room table of the Initial Quotation (layout.room_rows), then Basic Total, discount and Total."""
    from . import billing, layout
    (BRAND_DARK, BRAND_ACCENT, BRAND_LIGHT, TABLE_HEADER_BG, ROOM_HEADER_BG,
     TABLE_HEADER_FG, TOTAL_ROW_BG, ON_BRAND) = palette
    snap = billing.quotation_snapshot(project)
    rows = layout.room_rows(snap)
    from . import item_images
    photos = item_images.data_for(it.get('image_id') for r in rows for it in r['items'])
    small = ParagraphStyle('RR', parent=styles['Normal'], fontSize=8, leading=10)
    bold = ParagraphStyle('RRB', parent=small, fontName='Helvetica-Bold')
    muted = ParagraphStyle('RRM', parent=small, textColor=colors.HexColor('#455a64'))
    cw = [page_width * f for f in (0.05, 0.15, 0.21, 0.22, 0.10, 0.10, 0.06, 0.11)]
    head = Table([['#', 'Room', 'Material Description', 'Item', 'Length', 'Width', "No's", 'Amount (Rs.)']], colWidths=cw)
    head.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), TABLE_HEADER_BG), ('TEXTCOLOR', (0, 0), (-1, -1), TABLE_HEADER_FG),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'), ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('ALIGN', (4, 0), (-1, -1), 'CENTER'), ('ALIGN', (7, 0), (7, 0), 'RIGHT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'), ('PADDING', (0, 0), (-1, -1), 5),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#bdbdbd'))]))
    out = [head]
    for r in rows:
        data = []
        for i, it in enumerate(r['items']):
            size = (lambda v: units.length(v) if v else '—')
            data.append([str(r['no']) if i == 0 else '',
                         Paragraph(escape(r['title']), bold) if i == 0 else '',
                         Paragraph(escape(r['description']).replace('\n', '<br/>'), muted) if i == 0 and r['description'] else '',
                         ([Paragraph(escape(it['name']), small), item_images.pdf_image(photos[it['image_id']], 2.0, 2.0)]
                          if photos.get(it.get('image_id')) else Paragraph(escape(it['name']), small)),
                         size(it['length']), size(it['width']),
                         layout.count_text(it['count']), _money(r['amount']) if i == 0 else ''])
        n = len(data)
        t = Table(data, colWidths=cw)
        cmds = [('FONTSIZE', (0, 0), (-1, -1), 8), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('VALIGN', (0, 0), (2, -1), 'TOP'), ('ALIGN', (0, 0), (0, -1), 'CENTER'),
                ('ALIGN', (4, 0), (6, -1), 'CENTER'), ('ALIGN', (7, 0), (7, -1), 'RIGHT'),
                ('FONTNAME', (7, 0), (7, -1), 'Helvetica-Bold'), ('PADDING', (0, 0), (-1, -1), 5),
                ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#bdbdbd')),
                ('LINEBEFORE', (1, 0), (-1, -1), 0.5, colors.HexColor('#bdbdbd')),
                ('LINEBELOW', (3, 0), (6, -2), 0.25, colors.HexColor('#e0e0e0'))]
        if n > 1:
            cmds += [('SPAN', (c, 0), (c, n - 1)) for c in (0, 1, 2, 7)]
        if r['hardware']:
            cmds.append(('BACKGROUND', (0, 0), (-1, -1), BRAND_LIGHT))
        t.setStyle(TableStyle(cmds))
        out.append(t)
    return out + _totals_elements(snap, page_width, palette)


def _totals_elements(snap, page_width, palette):
    """Basic Total, discount and Total under an Initial Quotation table."""
    (BRAND_DARK, BRAND_ACCENT, BRAND_LIGHT, TABLE_HEADER_BG, ROOM_HEADER_BG,
     TABLE_HEADER_FG, TOTAL_ROW_BG, ON_BRAND) = palette
    tot = [['Basic Total', f'Rs. {_money(snap["subtotal"])}']]
    cmds = [('FONTSIZE', (0, 0), (-1, -1), 10), ('ALIGN', (0, 0), (-1, -1), 'RIGHT'), ('PADDING', (0, 0), (-1, -1), 7),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'), ('BACKGROUND', (0, 0), (-1, 0), BRAND_LIGHT),
            ('TEXTCOLOR', (0, 0), (-1, 0), BRAND_DARK)]
    disc = snap['discount']
    if disc.get('amount'):
        label = f"Discount ({disc['value']:g}%)" if disc.get('type') == 'percentage' else 'Discount'
        tot.append([label, f'- Rs. {_money(disc["amount"])}'])
        cmds += [('TEXTCOLOR', (0, 1), (-1, 1), colors.HexColor('#b91c1c')), ('FONTNAME', (0, 1), (-1, 1), 'Helvetica-Bold')]
    tot.append(['TOTAL', f'Rs. {_money(snap["total"])}'])
    k = len(tot) - 1
    cmds += [('BACKGROUND', (0, k), (-1, k), TOTAL_ROW_BG), ('TEXTCOLOR', (0, k), (-1, k), TABLE_HEADER_FG),
             ('FONTNAME', (0, k), (-1, k), 'Helvetica-Bold'), ('FONTSIZE', (0, k), (-1, k), 12)]
    tt = Table(tot, colWidths=[page_width * 0.72, page_width * 0.28])
    tt.setStyle(TableStyle(cmds))
    return [Spacer(1, 6), KeepTogether([tt])]             # Basic Total, discount and Total on one page


def _boq_elements(project, page_width, palette, styles):
    """The BOQ layout of the Initial Quotation (layout.boq_rows): sections A, B, C… with numbered lines — description,
    quantity, unit, rate and amount — then Basic Total, discount and Total."""
    from . import billing, layout
    (BRAND_DARK, BRAND_ACCENT, BRAND_LIGHT, TABLE_HEADER_BG, ROOM_HEADER_BG,
     TABLE_HEADER_FG, TOTAL_ROW_BG, ON_BRAND) = palette
    snap = billing.quotation_snapshot(project)
    small = ParagraphStyle('BQ', parent=styles['Normal'], fontSize=8, leading=10)
    title = ParagraphStyle('BQT', parent=small, fontName='Helvetica-Bold')
    sections = layout.boq_rows(snap)
    from . import item_images
    photos = item_images.data_for(ln.get('image_id') for sec in sections for ln in sec['lines'])
    grid = colors.HexColor('#bdbdbd')
    if photos:                                 # a Photo column only when some line has a photo
        cw = [page_width * f for f in (0.06, 0.38, 0.15, 0.08, 0.08, 0.10, 0.15)]
        data = [['Sr. No.', 'Description', 'Photo', 'Qty', 'Unit', 'Rate', 'Amount (Rs.)']]
    else:
        cw = [page_width * f for f in (0.07, 0.49, 0.09, 0.09, 0.11, 0.15)]
        data = [['Sr. No.', 'Description', 'Qty', 'Unit', 'Rate', 'Amount (Rs.)']]
    pc = 1 if photos else 0                    # columns after Description shift by one with a Photo column
    cmds = [('BACKGROUND', (0, 0), (-1, 0), TABLE_HEADER_BG), ('TEXTCOLOR', (0, 0), (-1, 0), TABLE_HEADER_FG),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'), ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('ALIGN', (0, 0), (0, -1), 'CENTER'), ('ALIGN', (2, 0), (4 + pc, -1), 'CENTER'),
            ('ALIGN', (5 + pc, 0), (5 + pc, -1), 'RIGHT'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'), ('PADDING', (0, 0), (-1, -1), 5),
            ('GRID', (0, 0), (-1, -1), 0.5, grid)]
    for sec in sections:
        k = len(data)
        head = escape(sec['name'])
        if sec['description']:
            head += f'<br/><font size="7" color="#455a64">{escape(sec["description"]).replace(chr(10), "<br/>")}</font>'
        data.append([sec['letter'], Paragraph(head, title)] + [''] * (4 + pc))
        cmds += [('BACKGROUND', (0, k), (-1, k), BRAND_LIGHT), ('SPAN', (1, k), (-1, k)),
                 ('FONTNAME', (0, k), (0, k), 'Helvetica-Bold'), ('TEXTCOLOR', (0, k), (-1, k), BRAND_DARK)]
        if sec['lines']:
            cmds.append(('NOSPLIT', (0, k), (-1, k + 1)))      # a section heading stays with its first line
        for ln in sec['lines']:
            text = f'<b>{escape(ln["title"])}</b>'
            if ln['description']:
                text += '<br/><font color="#455a64">' + escape(ln['description']).replace('\n', '<br/>') + '</font>'
            amount = 'Price to follow' if ln.get('tbc') else _money(ln['amount']) if ln['amount'] else '—'
            data.append([str(ln['no']), Paragraph(text, small)]
                        + ([item_images.pdf_image(photos.get(ln.get('image_id')), 2.6, 2.6) or ''] if photos else [])
                        + [f'{ln["qty"]:,.2f}'.rstrip('0').rstrip('.') if ln['qty'] else '—', ln['unit'],
                           _money(ln['rate'], ',.0f') if ln['rate'] else '', amount])
    table = Table(data, colWidths=cw, repeatRows=1)
    table.setStyle(TableStyle(cmds))
    return [table] + _totals_elements(snap, page_width, palette)


def generate_pdf(project, payment_settings=None, total_paid=0.0):
    """
    Generate a professional PDF quotation and return a BytesIO buffer.
    payment_settings: dict with keys upi_id, bank_name, account_name,
                      account_number, ifsc_code  (optional)
    total_paid: float – amount already received (optional)
    """
    """Generate a professional PDF quotation and return a BytesIO buffer."""
    (BRAND_DARK, BRAND_ACCENT, BRAND_LIGHT, TABLE_HEADER_BG, ROOM_HEADER_BG,
     TABLE_HEADER_FG, TOTAL_ROW_BG, ON_BRAND) = _palette()
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=1.5 * cm,
        leftMargin=1.5 * cm,
        topMargin=1.5 * cm,
        bottomMargin=2 * cm
    )

    styles = getSampleStyleSheet()
    elements = []

    # --- Custom Styles ---
    title_style = ParagraphStyle(
        'Title', parent=styles['Title'],
        fontSize=22, fontName='Helvetica-Bold',
        textColor=BRAND_DARK, alignment=TA_CENTER, spaceAfter=2
    )
    subtitle_style = ParagraphStyle(
        'Subtitle', parent=styles['Normal'],
        fontSize=11, fontName='Helvetica',
        textColor=colors.HexColor('#546e7a'), alignment=TA_CENTER, spaceAfter=4
    )
    section_style = ParagraphStyle(
        'Section', parent=styles['Normal'],
        fontSize=10, fontName='Helvetica-Bold',
        textColor=BRAND_DARK
    )
    normal_style = ParagraphStyle(
        'NormalCustom', parent=styles['Normal'],
        fontSize=9, fontName='Helvetica'
    )
    right_style = ParagraphStyle(
        'Right', parent=styles['Normal'],
        fontSize=9, alignment=TA_RIGHT
    )
    total_style = ParagraphStyle(
        'Total', parent=styles['Normal'],
        fontSize=13, fontName='Helvetica-Bold',
        textColor=BRAND_DARK, alignment=TA_RIGHT
    )

    # -------  HEADER -------
    elements += _header_elements(title_style, subtitle_style, BRAND_ACCENT)

    # QUOTATION LABEL
    quot_header = Table(
        [['INTERIOR DESIGN QUOTATION',
          _quote_ref(project)]],
        colWidths=['65%', '35%']
    )
    quot_header.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, 0), BRAND_DARK),
        ('BACKGROUND', (1, 0), (1, 0), BRAND_LIGHT),
        ('TEXTCOLOR', (0, 0), (0, 0), ON_BRAND),
        ('TEXTCOLOR', (1, 0), (1, 0), BRAND_DARK),
        ('FONTNAME', (0, 0), (0, 0), 'Helvetica-Bold'),
        ('FONTNAME', (1, 0), (1, 0), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('ALIGN', (0, 0), (0, 0), 'CENTER'),
        ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('PADDING', (0, 0), (-1, -1), 8),
        ('ROUNDEDCORNERS', [4, 4, 4, 4]),
    ]))
    elements.append(quot_header)
    elements.append(Spacer(1, 12))

    # ------- CUSTOMER DETAILS -------
    elements.append(Paragraph("Customer Details", section_style))
    elements.append(Spacer(1, 4))
    cust_data = [
        ['Customer Name', project.customer_name, 'Mobile', project.mobile],
        ['Email', project.email or '—', 'Prepared By', project.creator.display_name],
    ]
    if project.address:
        cust_data.append(['Address', Paragraph(project.address, normal_style), '', ''])
    cust_table = Table(cust_data, colWidths=['18%', '32%', '18%', '32%'])
    span_cmds = []
    if project.address:
        last = len(cust_data) - 1
        span_cmds = [('SPAN', (1, last), (3, last))]
    cust_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), GREY_BG),
        ('BACKGROUND', (2, 0), (2, -1), GREY_BG),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTNAME', (2, 0), (2, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#bdbdbd')),
        ('PADDING', (0, 0), (-1, -1), 7),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TEXTCOLOR', (0, 0), (0, -1), BRAND_DARK),
        ('TEXTCOLOR', (2, 0), (2, -1), BRAND_DARK),
    ] + span_cmds))
    elements.append(cust_table)
    elements.append(Spacer(1, 14))

    # ------- ROOM-BY-ROOM BREAKDOWN -------
    elements.append(Paragraph("Room-by-Room Breakdown", section_style))
    elements.append(Spacer(1, 6))

    item_col_widths = ['20%', '10%', '10%', '31%', '12%', '17%']
    page_width = A4[0] - 3 * cm
    col_widths = [page_width * float(p.strip('%')) / 100 for p in item_col_widths]

    from . import plywood
    _item_rates_map = plywood.rate_map()
    _project_ply = plywood.project_plywood(project)
    material_style = ParagraphStyle('ItemMaterial', parent=styles['Normal'], fontSize=8, leading=10, alignment=1)
    material_style_left = ParagraphStyle('ItemName', parent=material_style, alignment=0)

    from . import layout as _layout
    rooms = project.rooms_with_items()
    section_totals = []                       # (room, amount): the summary of a quotation priced by item

    from . import item_images
    photos = item_images.data_for(i.photo_id for r in rooms for i in r.item_list)

    def _name_cell(item, extra=''):
        text = escape(item.display_name + (f' × {item.count}' if not item.is_fixed and item.count > 1 else ''))
        notes = '\n'.join(x for x in (item.note, extra) if x)
        if notes:
            text += f'<br/><font size="7" color="#546e7a">{escape(notes).replace(chr(10), "<br/>")}</font>'
        pic = item_images.pdf_image(photos.get(item.photo_id), 2.4, 2.4) if photos.get(item.photo_id) else None
        return [Paragraph(text, material_style_left), pic] if pic else Paragraph(text, material_style_left)

    def _size_note(item):
        if not (item.is_boq and item.length):
            return ''
        size = ft_in(item.length) + (f' × {ft_in(item.width)}' if item.width else '')
        return f'Size: {size}' + (f' × {item.boq_count} Nos.' if item.boq_count > 1 else '')

    for room in rooms:
        items = room.item_list
        priced_only = all(i.is_fixed for i in items)          # BOQ lines / fittings: no sizes or materials
        room_total_area = 0.0
        room_total_cost = 0.0
        head_text = f'<b>{escape(room.name.upper())}</b>'
        notes = _layout.room_description(room) if priced_only else ''
        if notes:
            head_text += f'<br/><font size="7">{escape(notes).replace(chr(10), "<br/>")}</font>'
        head_style = ParagraphStyle('RoomHead', parent=styles['Normal'], fontSize=9, leading=11, textColor=TABLE_HEADER_FG)

        if priced_only:
            # Item | Qty | Unit | Rate | Amount — each line as quoted
            widths = [page_width * f for f in (0.48, 0.11, 0.11, 0.13, 0.17)]
            rows = [[Paragraph(head_text, head_style), '', '', '', ''],
                    ['Item', 'Qty', 'Unit', 'Rate (Rs.)', 'Amount (Rs.)']]
            for item in items:
                amount = item.cost(_item_rates_map, _project_ply)
                room_total_cost += amount
                unit = item.unit_text if item.is_boq else 'Nos.'
                if item.price_to_follow:
                    cells = [f'{item.quantity:g}' if item.quantity else '—', unit, '—', 'Price to follow']
                elif not item.quantity:                     # rate only: printed with its rate, not added
                    cells = ['—', unit, _money(item.unit_price, ',.0f'), '—']
                elif item.is_boq and item.unit_text == 'LS':
                    cells = ['1', 'LS', _money(item.unit_price, ',.0f'), _money(amount)]
                else:
                    cells = [f'{item.quantity:g}', unit, _money(item.unit_price, ',.0f'), _money(amount)]
                rows.append([_name_cell(item, _size_note(item))] + cells)
            rates_only = room_total_cost == 0 and all(not i.quantity for i in items if not i.price_to_follow)
            rows.append(['Rates for reference, not added to the total' if rates_only else 'Section Total', '', '', '',
                         '—' if rates_only else f'Rs. {_money(room_total_cost)}'])
            total_cmds = [('SPAN', (0, -1), (3, -1)), ('ALIGN', (0, -1), (3, -1), 'RIGHT' if not rates_only else 'LEFT'),
                          ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'), ('ALIGN', (1, 1), (3, -2), 'CENTER'),
                          ('ALIGN', (4, 1), (4, -1), 'RIGHT'), ('ALIGN', (3, 2), (3, -2), 'RIGHT')]
            if rates_only:
                total_cmds += [('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Oblique'), ('TEXTCOLOR', (0, -1), (-1, -1), colors.HexColor('#546e7a'))]
            section_totals.append((room, room_total_cost))
        else:
            widths = col_widths
            rows = [[Paragraph(head_text, head_style), '', '', '', '', ''],
                    ['Item Name', 'Length', 'Width', 'Material', f'Area ({units.area_label()})', 'Subtotal (Rs.)']]
            for item in items:
                if item.is_fixed:
                    # Fitting/accessory or BOQ line in a room with measured items: quantity × unit price
                    subtotal = item.cost(_item_rates_map, _project_ply)
                    room_total_cost += subtotal
                    if item.price_to_follow:
                        what = f'{item.quantity:g} {item.unit_text}, price to follow' if item.quantity else 'Price to follow'
                    elif item.is_boq and not item.quantity:
                        what = f'Rate only: Rs. {_money(item.unit_price, ",.0f")} / {item.unit_text}'
                    elif item.is_boq:
                        what = f'{item.quantity:g} {item.unit_text} × Rs. {_money(item.unit_price, ",.0f")}'
                    else:
                        what = f'Fitting: {item.quantity:g} × Rs. {_money(item.unit_price, ",.0f")}'
                    sized = item.is_boq and item.length
                    rows.append([_name_cell(item), ft_in(item.length) if sized else '—',
                                 ft_in(item.width) if sized and item.width else '—', Paragraph(escape(what), material_style),
                                 '—', _money(subtotal) if item.quantity and not item.price_to_follow else '—'])
                    continue
                _key       = plywood.item_key(item, _project_ply)
                rate       = _item_rates_map.get(_key, 0.0)
                subtotal   = item.area * rate
                room_total_area += item.area
                room_total_cost += subtotal
                rows.append([
                    _name_cell(item),
                    ft_in(item.length),
                    ft_in(item.width),
                    Paragraph(escape(plywood.finish_label(_key, project)), material_style),   # wraps: never cut off
                    f'{units.area_value(item.area):,.2f}',
                    f'{_money(subtotal)}'
                ])
            rows.append(['', '', '', 'Room Total:', units.area(room_total_area), f'Rs. {_money(room_total_cost)}'])
            total_cmds = [('FONTNAME', (3, -1), (-1, -1), 'Helvetica-Bold'), ('ALIGN', (1, 1), (-1, -1), 'CENTER'),
                          ('ALIGN', (5, 1), (5, -1), 'RIGHT')]

        item_table = Table(rows, colWidths=widths, repeatRows=2)
        item_table.setStyle(TableStyle([
            # Room name: the table's first row (repeated with the headings on a new page)
            ('SPAN', (0, 0), (-1, 0)),
            ('BACKGROUND', (0, 0), (-1, 0), ROOM_HEADER_BG),
            ('TOPPADDING', (0, 0), (-1, 0), 8),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
            # Column headings
            ('BACKGROUND', (0, 1), (-1, 1), TABLE_HEADER_BG),
            ('TEXTCOLOR', (0, 1), (-1, 1), TABLE_HEADER_FG),
            ('FONTNAME', (0, 1), (-1, 1), 'Helvetica-Bold'),
            ('ALIGN', (1, 1), (-1, 1), 'CENTER'),
            # Data rows
            ('FONTNAME', (0, 2), (-1, -2), 'Helvetica'),
            ('FONTSIZE', (0, 1), (-1, -1), 8),
            ('ALIGN', (0, 2), (0, -1), 'LEFT'),
            ('ROWBACKGROUNDS', (0, 2), (-1, -2), [colors.white, colors.HexColor('#fafafa')]),
            # Total row
            ('BACKGROUND', (0, -1), (-1, -1), BRAND_LIGHT),
            ('TEXTCOLOR', (0, -1), (-1, -1), BRAND_DARK),
            ('GRID', (0, 1), (-1, -1), 0.5, colors.HexColor('#e0e0e0')),
            ('LINEBELOW', (0, 1), (-1, 1), 1, BRAND_DARK),
            ('PADDING', (0, 0), (-1, -1), 5),
            ('TOPPADDING', (0, 1), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 1), (-1, -1), 6),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            # the room's name, the column headings and the first item never end a page on their own
            ('NOSPLIT', (0, 0), (-1, min(2, len(rows) - 1))),
        ] + total_cmds))
        elements.append(item_table)
        elements.append(Spacer(1, 8))

    # ------- COST SUMMARY -------
    elements.append(Spacer(1, 6))
    summary_head = [HRFlowable(width='100%', thickness=1, color=colors.HexColor('#bdbdbd'), spaceAfter=8),
                    Paragraph("Cost Summary", section_style), Spacer(1, 6)]

    item_totals = project.get_item_totals(rooms)  # { 'wood|work': area }
    summary_cw = [page_width * p for p in [0.35, 0.22, 0.22, 0.21]]
    by_sections = not any(a > 0 for a in item_totals.values())     # nothing measured: a total per section instead

    # Combined material + work cost table
    combo_data = ([['Section', '', 'Amount (Rs.)']] if by_sections
                  else [['Material & Work Type', f'Total Area ({units.area_label()})', 'Amount (Rs.)']])  # no rate per area
    combo_total = 0.0
    combo_area_total = 0.0
    for key in M.ordered_keys(item_totals):
        area = item_totals.get(key, 0.0)
        if area > 0:
            rate = _item_rates_map.get(key, 0.0)
            subtotal = area * rate
            combo_total += subtotal
            combo_area_total += area
            combo_data.append([plywood.label(key, project), f'{units.area_value(area):,.2f}', f'{_money(subtotal)}'])
    if by_sections:
        for r_i, (room, amount) in enumerate((r, a) for r, a in section_totals if a > 0):
            combo_total += amount
            combo_data.append([room.name, '', f'{_money(amount)}'])
    else:
        fixed_total = project.fixed_items_total(rooms)
        if fixed_total > 0:
            combo_total += fixed_total
            combo_data.append([FIXED_ITEMS_LABEL, '—', f'{_money(fixed_total)}'])
        boq_total = project.boq_items_total(rooms)
        if boq_total > 0:
            combo_total += boq_total
            combo_data.append([BOQ_ITEMS_LABEL, '—', f'{_money(boq_total)}'])
    combo_data.append(['', 'Subtotal', f'Rs. {_money(combo_total)}'])

    combo_table = Table(combo_data, colWidths=[page_width * p for p in [0.57, 0.22, 0.21]])
    combo_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), TABLE_HEADER_BG),
        ('TEXTCOLOR', (0, 0), (-1, 0), TABLE_HEADER_FG),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 9),
        ('FONTNAME', (0, 1), (-1, -2), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -1), 9),
        ('ROWBACKGROUNDS', (0, 1), (-1, -2), [colors.white, BRAND_LIGHT]),
        ('BACKGROUND', (0, -1), (-1, -1), BRAND_LIGHT),
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
        ('TEXTCOLOR', (1, -1), (-1, -1), BRAND_DARK),
        ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
        ('ALIGN', (0, 0), (0, -1), 'LEFT'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e0e0e0')),
        ('PADDING', (0, 0), (-1, -1), 7),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ] + ([('SPAN', (0, r), (1, r)) for r in range(len(combo_data) - 1)] if by_sections else [])))   # no area column
    elements.append(KeepTogether(summary_head + [combo_table]))       # the heading never ends a page on its own
    elements.append(Spacer(1, 8))

    # Discount + Final total rows
    discount_amount = getattr(project, 'discount_amount', 0.0)
    final_total     = getattr(project, 'final_total',     project.grand_total)
    total_rows = []
    total_style_cmds = []

    if discount_amount > 0:
        dtype = getattr(project, 'discount_type', 'none')
        dval  = getattr(project, 'discount_value', 0) or 0
        disc_label = f'Discount ({dval:.0f}%)' if dtype == 'percentage' else 'Discount (Fixed)'
        total_rows.append(['', '', disc_label, f'- Rs. {_money(discount_amount)}'])
        total_style_cmds += [
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#fef2f2')),
            ('TEXTCOLOR', (2, 0), (-1, 0), colors.HexColor('#b91c1c')),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('ALIGN', (2, 0), (-1, 0), 'RIGHT'),
            ('PADDING', (0, 0), (-1, 0), 7),
        ]

    fi = len(total_rows)
    total_rows.append(['', '' if by_sections else units.area(combo_area_total), 'FINAL TOTAL', f'Rs. {_money(final_total)}'])
    total_style_cmds += [
        ('BACKGROUND', (0, fi), (-1, fi), TOTAL_ROW_BG),
        ('TEXTCOLOR', (0, fi), (-1, fi), TABLE_HEADER_FG),
        ('FONTNAME', (0, fi), (-1, fi), 'Helvetica-Bold'),
        ('FONTSIZE', (0, fi), (-1, fi), 12),
        ('ALIGN', (0, fi), (1, fi), 'LEFT'),
        ('ALIGN', (2, fi), (-1, fi), 'RIGHT'),
        ('PADDING', (0, fi), (-1, fi), 9),
        ('TOPPADDING', (0, fi), (-1, fi), 10),
        ('BOTTOMPADDING', (0, fi), (-1, fi), 10),
    ]

    grand_total_table = Table(total_rows, colWidths=summary_cw)
    grand_total_table.setStyle(TableStyle(total_style_cmds))
    elements.append(grand_total_table)
    elements.append(Spacer(1, 20))

    # ------- SECTIONS: material specifications, payment & delivery terms, notes, T&C -------
    elements += _section_elements(styles, BRAND_DARK, project, rooms)
    _with_thanks(elements, Paragraph(
        _thank_you_text(),
        ParagraphStyle('Footer', parent=styles['Normal'],
                       fontSize=9, textColor=BRAND_DARK, alignment=TA_CENTER)
    ))

    # ------- PAYMENT DETAILS -------
    ps = payment_settings or {}
    has_payment_info = any([
        ps.get('upi_id'), ps.get('account_number'),
        ps.get('bank_name'), total_paid > 0
    ])
    if has_payment_info:
        elements.append(Spacer(1, 14))
        elements.append(HRFlowable(width='100%', thickness=1, color=BRAND_ACCENT, spaceAfter=8))
        elements.append(Paragraph("Payment Details", section_style))
        elements.append(Spacer(1, 6))

        pay_rows = []

        # Payment status row
        balance = max(project.final_total - total_paid, 0)
        if total_paid > 0:
            pay_rows.append(['Amount Paid', f'Rs. {_money(total_paid)}',
                             'Balance Due', f'Rs. {_money(balance)}'])

        upi   = ps.get('upi_id', '')
        bname = ps.get('bank_name', '')
        aname = ps.get('account_name', '')
        accno = ps.get('account_number', '')
        ifsc  = ps.get('ifsc_code', '')

        if upi:
            pay_rows.append(['UPI ID', upi, '', ''])
        if accno:
            pay_rows.append(['Bank', bname or '—', 'Account Holder', aname or '—'])
            pay_rows.append(['Account No.', accno, 'IFSC Code', ifsc or '—'])

        if pay_rows:
            pay_cw = ['18%', '32%', '18%', '32%']
            pay_cw_abs = [page_width * float(p.strip('%')) / 100 for p in pay_cw]
            pay_table = Table(pay_rows, colWidths=pay_cw_abs)
            span_cmds_pay = []
            for i, row in enumerate(pay_rows):
                if row[2] == '' and row[3] == '':
                    span_cmds_pay.append(('SPAN', (1, i), (3, i)))
            pay_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (0, -1), GREY_BG),
                ('BACKGROUND', (2, 0), (2, -1), GREY_BG),
                ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
                ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
                ('FONTNAME', (2, 0), (2, -1), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 9),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#bdbdbd')),
                ('PADDING', (0, 0), (-1, -1), 7),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('TEXTCOLOR', (0, 0), (0, -1), BRAND_DARK),
                ('TEXTCOLOR', (2, 0), (2, -1), BRAND_DARK),
            ] + span_cmds_pay))
            elements.append(pay_table)

    _build(doc, elements)
    buffer.seek(0)
    return buffer


def generate_customer_pdf(project, payment_settings=None, total_paid=0.0):
    """
    The Initial Quotation (customer copy). Room by room (default, Settings → Quotation PDFs): each room with what it's
    made of, its items with sizes and No's, and one amount; fittings as a Hardware row per room. Or by material:
    amount per material. Then the sections (specifications, terms, notes) and payment details.
    """
    (BRAND_DARK, BRAND_ACCENT, BRAND_LIGHT, TABLE_HEADER_BG, ROOM_HEADER_BG,
     TABLE_HEADER_FG, TOTAL_ROW_BG, ON_BRAND) = _palette()
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=1.5 * cm,
        leftMargin=1.5 * cm,
        topMargin=1.5 * cm,
        bottomMargin=2 * cm
    )

    styles = getSampleStyleSheet()
    elements = []
    page_width = A4[0] - 3 * cm

    # --- Styles (same as main PDF) ---
    title_style = ParagraphStyle(
        'Title2', parent=styles['Title'],
        fontSize=22, fontName='Helvetica-Bold',
        textColor=BRAND_DARK, alignment=TA_CENTER, spaceAfter=2
    )
    subtitle_style = ParagraphStyle(
        'Subtitle2', parent=styles['Normal'],
        fontSize=11, fontName='Helvetica',
        textColor=colors.HexColor('#546e7a'), alignment=TA_CENTER, spaceAfter=4
    )
    section_style = ParagraphStyle(
        'Section2', parent=styles['Normal'],
        fontSize=10, fontName='Helvetica-Bold',
        textColor=BRAND_DARK
    )
    normal_style = ParagraphStyle(
        'NormalCustom2', parent=styles['Normal'],
        fontSize=9, fontName='Helvetica'
    )

    # ------- HEADER -------
    elements += _header_elements(title_style, subtitle_style, BRAND_ACCENT)

    # QUOTATION LABEL
    quot_header = Table(
        [['CUSTOMER QUOTATION',
          _quote_ref(project)]],
        colWidths=['65%', '35%']
    )
    quot_header.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, 0), BRAND_DARK),
        ('BACKGROUND', (1, 0), (1, 0), BRAND_LIGHT),
        ('TEXTCOLOR', (0, 0), (0, 0), ON_BRAND),
        ('TEXTCOLOR', (1, 0), (1, 0), BRAND_DARK),
        ('FONTNAME', (0, 0), (0, 0), 'Helvetica-Bold'),
        ('FONTNAME', (1, 0), (1, 0), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('ALIGN', (0, 0), (0, 0), 'CENTER'),
        ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('PADDING', (0, 0), (-1, -1), 8),
    ]))
    elements.append(quot_header)
    elements.append(Spacer(1, 12))

    # ------- CUSTOMER DETAILS -------
    elements.append(Paragraph("Customer Details", section_style))
    elements.append(Spacer(1, 4))
    cust_data = [
        ['Customer Name', project.customer_name, 'Mobile', project.mobile],
        ['Email', project.email or '—', 'Prepared By', project.creator.display_name],
    ]
    if project.address:
        cust_data.append(['Address', Paragraph(project.address, normal_style), '', ''])
    cust_table = Table(cust_data, colWidths=['18%', '32%', '18%', '32%'])
    span_cmds = []
    if project.address:
        last = len(cust_data) - 1
        span_cmds = [('SPAN', (1, last), (3, last))]
    cust_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), GREY_BG),
        ('BACKGROUND', (2, 0), (2, -1), GREY_BG),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTNAME', (2, 0), (2, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#bdbdbd')),
        ('PADDING', (0, 0), (-1, -1), 7),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TEXTCOLOR', (0, 0), (0, -1), BRAND_DARK),
        ('TEXTCOLOR', (2, 0), (2, -1), BRAND_DARK),
    ] + span_cmds))
    elements.append(cust_table)
    elements.append(Spacer(1, 18))

    from . import layout, plywood
    _rooms2 = project.rooms_with_items()
    if layout.initial_layout() == layout.LAYOUT_BOQ:
        # ------- BOQ: sections A, B, C… with every line's description, quantity, unit, rate and amount -------
        elements.append(HRFlowable(width='100%', thickness=1, color=colors.HexColor('#bdbdbd'), spaceAfter=8))
        elements.append(Paragraph("Bill of Quantities", section_style))
        elements.append(Spacer(1, 8))
        elements += _boq_elements(project, page_width, (BRAND_DARK, BRAND_ACCENT, BRAND_LIGHT, TABLE_HEADER_BG,
                                                        ROOM_HEADER_BG, TABLE_HEADER_FG, TOTAL_ROW_BG, ON_BRAND), styles)
        elements.append(Spacer(1, 20))
    elif layout.initial_layout() == layout.LAYOUT_ROOMS:
        # ------- ROOM BY ROOM: items with sizes and No's, one amount per room, a Hardware row per room -------
        elements.append(HRFlowable(width='100%', thickness=1, color=colors.HexColor('#bdbdbd'), spaceAfter=8))
        elements.append(Paragraph("Quotation", section_style))
        elements.append(Spacer(1, 8))
        elements += _room_rows_elements(project, page_width, (BRAND_DARK, BRAND_ACCENT, BRAND_LIGHT, TABLE_HEADER_BG,
                                                              ROOM_HEADER_BG, TABLE_HEADER_FG, TOTAL_ROW_BG, ON_BRAND), styles)
        elements.append(Spacer(1, 20))
    else:
        # ------- COST SUMMARY -------
        elements.append(HRFlowable(width='100%', thickness=1, color=colors.HexColor('#bdbdbd'), spaceAfter=8))
        elements.append(Paragraph("Cost Summary", section_style))
        elements.append(Spacer(1, 8))

        from . import plywood
        _item_rates_map2 = plywood.rate_map()
        _project_ply2 = plywood.project_plywood(project)
        item_totals2 = project.get_item_totals(_rooms2)  # { price key: area }

        # Cost summary — show material+work combo and amount only (no area, no rate)
        cost_cw   = [page_width * p for p in [0.60, 0.40]]
        cost_data = [['Material & Work Type', 'Amount (Rs.)']]
        mat_total = 0.0
        total_area_all = 0.0
        for key in M.ordered_keys(item_totals2):
            area = item_totals2.get(key, 0.0)
            if area > 0:
                subtotal      = area * _item_rates_map2.get(key, 0.0)
                mat_total    += subtotal
                total_area_all += area
                cost_data.append([plywood.label(key, project), f'{_money(subtotal)}'])
        # Customer copy: all fittings & accessories as one line (itemised in the Full Quotation)
        fixed_total2 = project.fixed_items_total(_rooms2)
        if fixed_total2 > 0:
            mat_total += fixed_total2
            cost_data.append([FIXED_ITEMS_LABEL, f'{_money(fixed_total2)}'])
        boq_total2 = project.boq_items_total(_rooms2)
        if boq_total2 > 0:
            mat_total += boq_total2
            cost_data.append([BOQ_ITEMS_LABEL, f'{_money(boq_total2)}'])
        cost_data.append(['Total', f'Rs. {_money(mat_total)}'])

        cost_table = Table(cost_data, colWidths=cost_cw)
        cost_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), TABLE_HEADER_BG),
            ('TEXTCOLOR', (0, 0), (-1, 0), TABLE_HEADER_FG),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('FONTNAME', (0, 1), (-1, -2), 'Helvetica'),
            ('FONTSIZE', (0, 1), (-1, -1), 10),
            ('ROWBACKGROUNDS', (0, 1), (-1, -2), [colors.white, BRAND_LIGHT]),
            ('BACKGROUND', (0, -1), (-1, -1), BRAND_LIGHT),
            ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
            ('TEXTCOLOR', (0, -1), (-1, -1), BRAND_DARK),
            ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
            ('ALIGN', (0, 0), (0, -1), 'LEFT'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e0e0e0')),
            ('PADDING', (0, 0), (-1, -1), 8),
        ]))
        elements.append(cost_table)
        elements.append(Spacer(1, 10))

        # Discount + Final total
        discount_amount = getattr(project, 'discount_amount', 0.0)
        final_total     = getattr(project, 'final_total', project.grand_total)
        total_rows      = []
        total_style_cmds = []

        if discount_amount > 0:
            dtype = getattr(project, 'discount_type', 'none')
            dval  = getattr(project, 'discount_value', 0) or 0
            disc_label = f'Discount ({dval:.0f}%)' if dtype == 'percentage' else 'Discount (Fixed)'
            total_rows.append([disc_label, f'- Rs. {_money(discount_amount)}'])
            total_style_cmds += [
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#fef2f2')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.HexColor('#b91c1c')),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 10),
                ('ALIGN', (1, 0), (-1, 0), 'RIGHT'),
                ('PADDING', (0, 0), (-1, 0), 8),
            ]

        fi = len(total_rows)
        total_rows.append([f'FINAL TOTAL  ({units.area(total_area_all)})', f'Rs. {_money(final_total)}'])
        ft_cw = cost_cw
        total_style_cmds += [
            ('BACKGROUND', (0, fi), (-1, fi), TOTAL_ROW_BG),
            ('TEXTCOLOR', (0, fi), (-1, fi), TABLE_HEADER_FG),
            ('FONTNAME', (0, fi), (-1, fi), 'Helvetica-Bold'),
            ('FONTSIZE', (0, fi), (-1, fi), 12),
            ('ALIGN', (1, fi), (-1, fi), 'RIGHT'),
            ('PADDING', (0, fi), (-1, fi), 9),
            ('TOPPADDING', (0, fi), (-1, fi), 10),
            ('BOTTOMPADDING', (0, fi), (-1, fi), 10),
        ]
        grand_total_table = Table(total_rows, colWidths=ft_cw)
        grand_total_table.setStyle(TableStyle(total_style_cmds))
        elements.append(grand_total_table)
        elements.append(Spacer(1, 20))

    # ------- SECTIONS: material specifications, payment & delivery terms, notes, T&C -------
    elements += _section_elements(styles, BRAND_DARK, project, _rooms2)
    _with_thanks(elements, Paragraph(
        _thank_you_text(),
        ParagraphStyle('Footer2', parent=styles['Normal'],
                       fontSize=9, textColor=BRAND_DARK, alignment=TA_CENTER)
    ))

    # ------- PAYMENT DETAILS -------
    ps = payment_settings or {}
    has_payment_info = any([ps.get('upi_id'), ps.get('account_number'), ps.get('bank_name'), total_paid > 0])
    if has_payment_info:
        elements.append(Spacer(1, 14))
        elements.append(HRFlowable(width='100%', thickness=1, color=BRAND_ACCENT, spaceAfter=8))
        elements.append(Paragraph("Payment Details", section_style))
        elements.append(Spacer(1, 6))
        pay_rows = []
        balance = max(project.final_total - total_paid, 0)
        if total_paid > 0:
            pay_rows.append(['Amount Paid', f'Rs. {_money(total_paid)}', 'Balance Due', f'Rs. {_money(balance)}'])
        if ps.get('upi_id'):
            pay_rows.append(['UPI ID', ps['upi_id'], '', ''])
        if ps.get('account_number'):
            pay_rows.append(['Bank', ps.get('bank_name', '—'), 'Account Holder', ps.get('account_name', '—')])
            pay_rows.append(['Account No.', ps['account_number'], 'IFSC Code', ps.get('ifsc_code', '—')])
        if pay_rows:
            pay_cw_abs = [page_width * float(p) / 100 for p in [18, 32, 18, 32]]
            pay_table  = Table(pay_rows, colWidths=pay_cw_abs)
            span_cmds_pay = [('SPAN', (1, i), (3, i)) for i, r in enumerate(pay_rows) if r[2] == '' and r[3] == '']
            pay_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (0, -1), GREY_BG),
                ('BACKGROUND', (2, 0), (2, -1), GREY_BG),
                ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
                ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
                ('FONTNAME', (2, 0), (2, -1), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 9),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#bdbdbd')),
                ('PADDING', (0, 0), (-1, -1), 7),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('TEXTCOLOR', (0, 0), (0, -1), BRAND_DARK),
                ('TEXTCOLOR', (2, 0), (2, -1), BRAND_DARK),
            ] + span_cmds_pay))
            elements.append(pay_table)

    _build(doc, elements)
    buffer.seek(0)
    return buffer


def generate_invoice_pdf(invoice, data, total_paid=0.0):
    """Tax invoice PDF from the invoice's frozen data (see billing.build_invoice). Returns a BytesIO buffer."""
    from datetime import date as _date
    (BRAND_DARK, BRAND_ACCENT, BRAND_LIGHT, TABLE_HEADER_BG, ROOM_HEADER_BG,
     TABLE_HEADER_FG, TOTAL_ROW_BG, ON_BRAND) = _palette()
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=1.5 * cm, leftMargin=1.5 * cm,
                            topMargin=1.5 * cm, bottomMargin=2 * cm)
    styles = getSampleStyleSheet()
    page_width = A4[0] - 3 * cm
    small = ParagraphStyle('InvSmall', parent=styles['Normal'], fontSize=8.5, leading=11)
    small_b = ParagraphStyle('InvSmallB', parent=small, fontName='Helvetica-Bold', textColor=BRAND_DARK)
    title_style = ParagraphStyle('InvTitle', parent=styles['Title'], fontSize=20, fontName='Helvetica-Bold',
                                 textColor=BRAND_DARK, alignment=TA_CENTER, spaceAfter=2)
    subtitle_style = ParagraphStyle('InvSub', parent=styles['Normal'], fontSize=10,
                                    textColor=colors.HexColor('#546e7a'), alignment=TA_CENTER, spaceAfter=3)
    seller, buyer = data['seller'], data['buyer']
    elements = []

    # Seller (as it was when the invoice was issued)
    logo = _logo_flowable(get_brand())
    if logo:
        elements += [logo, Spacer(1, 4)]
    elements.append(Paragraph(escape(seller['name']), title_style))
    parts = [p for p in (seller['address'].replace('\n', ', '), seller['phone'] and f"Ph: {seller['phone']}",
                         seller['email']) if p]
    if parts:
        elements.append(Paragraph(escape('  |  '.join(parts)), subtitle_style))
    if seller['gstin']:
        elements.append(Paragraph(escape(f"GSTIN: {seller['gstin']}"
                                         + (f"  |  State: {seller['state']} ({seller['state_code']})" if seller['state'] else '')),
                                  subtitle_style))
    elements.append(HRFlowable(width='100%', thickness=2, color=BRAND_ACCENT, spaceAfter=8))

    issued = _date.fromisoformat(data['issued_on'])
    head = Table([[data['title'] + ('  (CANCELLED)' if invoice.status == 'cancelled' else ''),
                   f'Invoice No: {invoice.number}\nDate: {issued.strftime("%d %B %Y")}']],
                 colWidths=[page_width * 0.6, page_width * 0.4])
    head.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, 0), BRAND_DARK), ('BACKGROUND', (1, 0), (1, 0), BRAND_LIGHT),
        ('TEXTCOLOR', (0, 0), (0, 0), ON_BRAND), ('TEXTCOLOR', (1, 0), (1, 0), BRAND_DARK),
        ('FONTNAME', (0, 0), (0, 0), 'Helvetica-Bold'), ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('ALIGN', (0, 0), (0, 0), 'CENTER'), ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'), ('PADDING', (0, 0), (-1, -1), 8),
    ]))
    elements += [head, Spacer(1, 10)]

    # Bill to / supply details
    bill = [Paragraph('<b>Bill to</b>', small_b), Paragraph(escape(buyer['name']), small)]
    if buyer.get('address'):
        bill.append(Paragraph(escape(buyer['address']).replace('\n', '<br/>'), small))
    if buyer.get('mobile'):
        bill.append(Paragraph(escape(f"Mobile: {buyer['mobile']}"), small))
    if buyer.get('gstin'):
        bill.append(Paragraph(escape(f"GSTIN: {buyer['gstin']}"), small))
    supply = [Paragraph('<b>Details</b>', small_b),
              Paragraph(escape(f"Quotation #{data['quotation_id']}" + (f" (Rev {data['revision']})" if data.get('revision') else '')), small)]
    if data['place_of_supply']['state']:
        supply.append(Paragraph(escape(f"Place of supply: {data['place_of_supply']['state']} ({data['place_of_supply']['code']})"), small))
    if data['gst_rate']:
        supply.append(Paragraph('Prices include GST' if data['prices'] == 'inclusive' else 'GST added to quoted prices', small))
    box = Table([[bill, supply]], colWidths=[page_width * 0.55, page_width * 0.45])
    box.setStyle(TableStyle([('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#bdbdbd')),
                             ('LINEAFTER', (0, 0), (0, 0), 0.5, colors.HexColor('#bdbdbd')),
                             ('VALIGN', (0, 0), (-1, -1), 'TOP'), ('PADDING', (0, 0), (-1, -1), 7)]))
    elements += [box, Spacer(1, 12)]

    # Lines: room by room (a heading row per room, with a room total) or one line per material
    show_hsn = any(l.get('hsn') for l in data['lines'])
    header = ['#', 'Description'] + (['HSN/SAC'] if show_hsn else []) + ['Qty', 'Rate (Rs.)', 'Amount (Rs.)']
    ncols = len(header)
    detail_style = ParagraphStyle('InvDetail', parent=small, fontSize=7.5, textColor=colors.HexColor('#6b7280'))
    rows, extra_style, n = [header], [], 0

    def room_total(name, amount):
        rows.append([f'{name} total'] + [''] * (ncols - 2) + [_money(amount)])
        r = len(rows) - 1
        extra_style.extend([('SPAN', (0, r), (ncols - 2, r)), ('ALIGN', (0, r), (-1, r), 'RIGHT'),
                            ('FONTNAME', (0, r), (-1, r), 'Helvetica-Bold'), ('TEXTCOLOR', (0, r), (-1, r), BRAND_DARK),
                            ('BACKGROUND', (0, r), (-1, r), BRAND_LIGHT)])
    current, room_sum = None, 0.0
    for l in data['lines']:
        room = l.get('room')
        if room is not None and room != current:
            if current is not None:
                room_total(current, room_sum)
            current, room_sum = room, 0.0
            rows.append([room.upper()] + [''] * (ncols - 1))
            r = len(rows) - 1
            extra_style.extend([('SPAN', (0, r), (-1, r)), ('BACKGROUND', (0, r), (-1, r), ROOM_HEADER_BG),
                                ('TEXTCOLOR', (0, r), (-1, r), TABLE_HEADER_FG), ('FONTNAME', (0, r), (-1, r), 'Helvetica-Bold'),
                                ('ALIGN', (0, r), (-1, r), 'LEFT')])
        n += 1
        room_sum += l['amount']
        qty = f"{l['qty']:,.2f} {l['unit']}" if l['unit'] in ('sqft', 'sq m') else f"{l['qty']:g} {l['unit']}"
        desc = [Paragraph(escape(l['description']), small)]
        if l.get('detail'):
            desc.append(Paragraph(escape(l['detail']), detail_style))
        rows.append([str(n), desc] + ([l.get('hsn', '')] if show_hsn else []) + [qty, _money(l['rate']), _money(l['amount'])])
    if current is not None:
        room_total(current, room_sum)
    widths = [0.06, 0.40, 0.12, 0.14, 0.13, 0.15] if show_hsn else [0.06, 0.48, 0.16, 0.14, 0.16]
    lines_table = Table(rows, colWidths=[page_width * w for w in widths], repeatRows=1)
    lines_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), TABLE_HEADER_BG), ('TEXTCOLOR', (0, 0), (-1, 0), TABLE_HEADER_FG),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'), ('FONTSIZE', (0, 0), (-1, -1), 8.5),
        ('ALIGN', (2, 0), (-1, -1), 'RIGHT'), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#fafafa')]),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e0e0e0')), ('PADDING', (0, 0), (-1, -1), 5),
    ] + extra_style))
    elements += [lines_table, Spacer(1, 8)]

    # Totals
    tot = [['Total of items', f"Rs. {_money(data['gross'])}"]]
    if data['discount']:
        tot.append([data['discount_label'], f"- Rs. {_money(data['discount'])}"])
    if data['gst_rate']:
        tot.append(['Taxable value', f"Rs. {_money(data['taxable'])}"])
        for t in data['taxes']:
            tot.append([t['label'], f"Rs. {_money(t['amount'])}"])
    if data['round_off']:
        tot.append(['Round off', f"{'+' if data['round_off'] > 0 else '-'} Rs. {_money(abs(data['round_off']))}"])
    tot.append(['INVOICE TOTAL', f"Rs. {_money(data['total'])}"])
    if total_paid:
        tot.append(['Received', f"Rs. {_money(total_paid)}"])
        tot.append(['Balance due', f"Rs. {_money(max(data['total'] - total_paid, 0))}"])
    ti = len(tot) - (3 if total_paid else 1)
    totals = Table(tot, colWidths=[page_width * 0.25, page_width * 0.22], hAlign='RIGHT')
    totals.setStyle(TableStyle([
        ('FONTSIZE', (0, 0), (-1, -1), 9), ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
        ('PADDING', (0, 0), (-1, -1), 5), ('LINEBELOW', (0, 0), (-1, -1), 0.3, colors.HexColor('#e0e0e0')),
        ('BACKGROUND', (0, ti), (-1, ti), TOTAL_ROW_BG), ('TEXTCOLOR', (0, ti), (-1, ti), TABLE_HEADER_FG),
        ('FONTNAME', (0, ti), (-1, ti), 'Helvetica-Bold'), ('FONTSIZE', (0, ti), (-1, ti), 11),
    ]))
    elements += [totals, Spacer(1, 6)]
    from .demo import demo_enabled
    if not demo_enabled():          # demo amounts are altered, so the words would contradict them
        elements.append(Paragraph(f"<b>Amount in words:</b> {escape(data['total_words'])}", small))
    if data.get('notes'):
        elements += [Spacer(1, 10), Paragraph('<b>Notes</b>', small_b)]
        for line in data['notes'].splitlines():
            if line.strip():
                elements.append(Paragraph(escape(line.strip()), small))

    elements.append(Spacer(1, 24))
    elements.append(Paragraph(f"Thank you for your business. — <b>{escape(seller['name'])}</b>",
                              ParagraphStyle('InvThanks', parent=small, textColor=BRAND_DARK, alignment=TA_CENTER)))
    elements.append(Spacer(1, 6))
    elements.append(Paragraph('This is a computer-generated invoice and needs no signature.',
                              ParagraphStyle('InvFoot', parent=small, textColor=colors.HexColor('#757575'), alignment=TA_CENTER)))
    _build(doc, elements)
    buffer.seek(0)
    return buffer
