import os
import re
from datetime import timedelta
from io import BytesIO
from xml.sax.saxutils import escape
from flask import current_app
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                 TableStyle, HRFlowable, Image, KeepTogether, PageBreak)
from reportlab.lib.utils import ImageReader
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT, TA_JUSTIFY
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


class _Fonts:
    """The business's PDF font (app/pdf_look.py), read when each PDF is made: _F.r regular, _F.b bold, _F.i italic."""
    r = property(lambda self: self._font('r'))
    b = property(lambda self: self._font('b'))
    i = property(lambda self: self._font('i'))

    @staticmethod
    def _font(k):
        from . import pdf_look
        return pdf_look.fonts()[k]


_F = _Fonts()


def _styles():
    """reportlab's sample styles in the business's PDF font."""
    from . import pdf_look
    styles = getSampleStyleSheet()
    for st in styles.byName.values():
        if hasattr(st, 'fontName'):              # (list styles have none)
            st.fontName = pdf_look.font_for(st.fontName)
    return styles


def _money(value, spec=',.2f'):
    return format(value, spec)


def _build(doc, elements):
    """Build the PDF, adding the demo notice and watermark on every page when DEMO_MODE is on, in black & white when the
    business chose it (app/pdf_look.py)."""
    from .demo import demo_enabled, demo_notice_flowable, watermark_canvas_class
    from . import pdf_look
    if demo_enabled():
        elements = [demo_notice_flowable(doc.width)] + list(elements)
    canvas = pdf_look.canvas_class(watermark_canvas_class() if demo_enabled() else None)
    if canvas:
        doc.build(elements, canvasmaker=canvas)
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


def _logo_flowable(brand, max_height=2 * cm, max_width=6 * cm):
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
    parts = []
    if brand['address']: parts.append(brand['address'].replace('\n', ', '))
    if brand['phone']:   parts.append(f"Ph: {brand['phone']}")
    if brand['email']:   parts.append(brand['email'])
    lines = ['  |  '.join(parts) if parts else brand['tagline']]
    if brand['gstin']:
        lines.append(f"GSTIN: {brand['gstin']}")
    return _letterhead(brand['name'], lines, title_style, subtitle_style, accent)


def _letterhead(name, lines, title_style, subtitle_style, accent):
    """The top of the quotation and invoice PDFs: logo, name and contact lines (centred, or with the logo on the left and
    the details on the right: Settings → Quotation PDFs → How your PDF looks), then the accent rule."""
    from . import pdf_look
    logo = _logo_flowable(get_brand())
    lines = [l for l in lines if l]
    if pdf_look.header() == pdf_look.LEFT:
        right = lambda st: ParagraphStyle(st.name + 'R', parent=st, alignment=TA_RIGHT)
        lines = [part for l in lines for part in l.split('  |  ')]          # one detail per line, none split mid-number
        details = [Paragraph(escape(name), right(title_style))] + [Paragraph(escape(l), right(subtitle_style)) for l in lines]
        if logo:
            logo.hAlign = 'LEFT'
        page_width = A4[0] - 3 * cm
        top = Table([[logo or '', details]], colWidths=[page_width * 0.4, page_width * 0.6])
        top.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'MIDDLE'), ('LEFTPADDING', (0, 0), (0, 0), 0),
                                 ('RIGHTPADDING', (1, 0), (1, 0), 0)]))
        elements = [top]
    else:
        elements = [logo, Spacer(1, 4)] if logo else []
        elements.append(Paragraph(escape(name), title_style))
        elements += [Paragraph(escape(l), subtitle_style) for l in lines]
    elements.append(HRFlowable(width='100%', thickness=2, color=accent, spaceAfter=8))
    return elements


def _thank_you_text():
    return (f"Thank you for choosing <b>{escape(get_brand()['name'])}</b>. "
            "We look forward to transforming your space!")


def _quote_ref(project):
    """'Rev 3\nDate: …' for the PDF header (just the date before a second revision). The quotation's number is the
    firm's own reference in the app; customers don't see it (firms asked for that)."""
    from .billing import latest_revision_number
    rev = latest_revision_number(project)
    return ((f'Rev {rev}\n' if rev and rev > 1 else '')
            + f'Date: {(project.created_at + timedelta(hours=5, minutes=30)).strftime("%d %B %Y")}')


def pdf_filename(project, prefix='Quotation'):
    """'Quotation_Priya_Sharma_27-10-2026.pdf': the customer sees it when the PDF is shared, so no quotation number."""
    when = (project.created_at + timedelta(hours=5, minutes=30)).strftime('%d-%m-%Y')
    name = re.sub(r'[^A-Za-z0-9]+', '_', project.customer_name or '').strip('_') or 'Customer'
    return f'{prefix}_{name}_{when}.pdf'


def _section_elements(styles, dark, project=None, rooms=None):
    """Material Specifications, Payment Terms, Delivery Terms, Important Notes and Terms & Conditions
    (Settings → Quotation PDFs): each a numbered list, empty ones left out."""
    from . import layout
    head = ParagraphStyle('SecHead', parent=styles['Normal'], fontSize=9, textColor=dark,
                          fontName=_F.b, spaceBefore=4, spaceAfter=4)
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


def _room_rows_elements(project, page_width, palette, styles, snap=None):
    """The room-by-room table of the Initial Quotation (layout.room_rows), then Basic Total, discount and Total.
    snap: a saved revision's snapshot (default: the quotation as it is now)."""
    from . import billing, layout
    (BRAND_DARK, BRAND_ACCENT, BRAND_LIGHT, TABLE_HEADER_BG, ROOM_HEADER_BG,
     TABLE_HEADER_FG, TOTAL_ROW_BG, ON_BRAND) = palette
    snap = snap or billing.quotation_snapshot(project)
    rows = layout.room_rows(snap)
    from . import item_images
    photos = item_images.data_for(it.get('image_id') for r in rows for it in r['items'])
    small = ParagraphStyle('RR', parent=styles['Normal'], fontSize=8, leading=10)
    bold = ParagraphStyle('RRB', parent=small, fontName=_F.b)
    muted = ParagraphStyle('RRM', parent=small, textColor=colors.HexColor('#455a64'))
    cw = [page_width * f for f in (0.05, 0.15, 0.21, 0.22, 0.10, 0.10, 0.06, 0.11)]
    head = Table([['#', 'Room', 'Material Description', 'Item', 'Length', 'Width', "No's", 'Amount (Rs.)']], colWidths=cw)
    head.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), TABLE_HEADER_BG), ('TEXTCOLOR', (0, 0), (-1, -1), TABLE_HEADER_FG),
        ('FONTNAME', (0, 0), (-1, -1), _F.b), ('FONTSIZE', (0, 0), (-1, -1), 8),
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
                ('FONTNAME', (7, 0), (7, -1), _F.b), ('PADDING', (0, 0), (-1, -1), 5),
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
            ('FONTNAME', (0, 0), (-1, 0), _F.b), ('BACKGROUND', (0, 0), (-1, 0), BRAND_LIGHT),
            ('TEXTCOLOR', (0, 0), (-1, 0), BRAND_DARK)]
    disc = snap['discount']
    if disc.get('amount'):
        label = f"Discount ({disc['value']:g}%)" if disc.get('type') == 'percentage' else 'Discount'
        tot.append([label, f'- Rs. {_money(disc["amount"])}'])
        cmds += [('TEXTCOLOR', (0, 1), (-1, 1), colors.HexColor('#b91c1c')), ('FONTNAME', (0, 1), (-1, 1), _F.b)]
    if snap.get('gst'):                        # GST on quotations: Total, GST, then the grand total with GST
        tot.append(['Total', f'Rs. {_money(snap["total"])}'])
        tot.append([f"GST @ {snap['gst_rate']:g}%", f'Rs. {_money(snap["gst"])}'])
        tot.append(['GRAND TOTAL (incl. GST)', f'Rs. {_money(snap["payable"])}'])
    else:
        tot.append(['TOTAL', f'Rs. {_money(snap["total"])}'])
    k = len(tot) - 1
    cmds += [('BACKGROUND', (0, k), (-1, k), TOTAL_ROW_BG), ('TEXTCOLOR', (0, k), (-1, k), TABLE_HEADER_FG),
             ('FONTNAME', (0, k), (-1, k), _F.b), ('FONTSIZE', (0, k), (-1, k), 12)]
    tt = Table(tot, colWidths=[page_width * 0.72, page_width * 0.28])
    tt.setStyle(TableStyle(cmds))
    return [Spacer(1, 6), KeepTogether([tt])]             # Basic Total, discount and Total on one page


def _boq_elements(project, page_width, palette, styles, snap=None):
    """The BOQ layout of the Initial Quotation (layout.boq_rows): sections A, B, C… with numbered lines — description,
    quantity, unit, rate and amount — then Basic Total, discount and Total."""
    from . import billing, layout
    (BRAND_DARK, BRAND_ACCENT, BRAND_LIGHT, TABLE_HEADER_BG, ROOM_HEADER_BG,
     TABLE_HEADER_FG, TOTAL_ROW_BG, ON_BRAND) = palette
    snap = snap or billing.quotation_snapshot(project)
    small = ParagraphStyle('BQ', parent=styles['Normal'], fontSize=8, leading=10)
    title = ParagraphStyle('BQT', parent=small, fontName=_F.b)
    sections = layout.boq_rows(snap)
    from . import item_images
    photos = item_images.data_for(ln.get('image_id') for sec in sections for ln in sec['lines'])
    grid = colors.HexColor('#bdbdbd')
    rate_col = layout.show_rate()              # some firms show quantities and amounts only (Settings → Quotation PDFs)
    # columns: Sr. No., Description, [Photo only when some line has one], Qty, Unit, [Rate], Amount
    heads = ['Sr. No.', 'Description'] + (['Photo'] if photos else []) + ['Qty', 'Unit'] + (['Rate'] if rate_col else []) \
        + ['Amount (Rs.)']
    fixed = {'Sr. No.': 0.07, 'Photo': 0.15, 'Qty': 0.09, 'Unit': 0.09, 'Rate': 0.11, 'Amount (Rs.)': 0.15}
    widths = [fixed.get(h, 0) for h in heads]
    widths[1] = 1 - sum(widths)                # the description takes what's left
    cw = [page_width * f for f in widths]
    data = [heads]
    last = len(heads) - 1
    cmds = [('BACKGROUND', (0, 0), (-1, 0), TABLE_HEADER_BG), ('TEXTCOLOR', (0, 0), (-1, 0), TABLE_HEADER_FG),
            ('FONTNAME', (0, 0), (-1, 0), _F.b), ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('ALIGN', (0, 0), (0, -1), 'CENTER'), ('ALIGN', (2, 0), (last - 1, -1), 'CENTER'),
            ('ALIGN', (last, 0), (last, -1), 'RIGHT'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'), ('PADDING', (0, 0), (-1, -1), 5),
            ('GRID', (0, 0), (-1, -1), 0.5, grid)]
    for sec in sections:
        k = len(data)
        head = escape(sec['name'])
        if sec['description']:
            head += f'<br/><font size="7" color="#455a64">{escape(sec["description"]).replace(chr(10), "<br/>")}</font>'
        # the section's total on its heading, in the Amount column (as on a firm's own BOQ sheet)
        data.append([sec['letter'], Paragraph(head, title)] + [''] * (last - 2) + [_money(sec['total']) if sec['total'] else ''])
        cmds += [('BACKGROUND', (0, k), (-1, k), BRAND_LIGHT), ('SPAN', (1, k), (-2, k)),
                 ('FONTNAME', (0, k), (0, k), _F.b), ('FONTNAME', (-1, k), (-1, k), _F.b),
                 ('TEXTCOLOR', (0, k), (-1, k), BRAND_DARK)]
        if sec['lines']:
            cmds.append(('NOSPLIT', (0, k), (-1, k + 1)))      # a section heading stays with its first line
        for ln in sec['lines']:
            text = f'<b>{escape(ln["title"])}</b>'
            if ln['description']:
                text += '<br/><font color="#455a64">' + escape(ln['description']).replace('\n', '<br/>') + '</font>'
            amount = 'Price to follow' if ln.get('tbc') else _money(ln['amount']) if ln['amount'] else '—'
            if not rate_col and not ln['qty'] and ln['rate']:          # a rate-only line still says its rate
                amount = f"Rate {_money(ln['rate'], ',.0f')}"
            data.append([str(ln['no']), Paragraph(text, small)]
                        + ([item_images.pdf_image(photos.get(ln.get('image_id')), 2.6, 2.6) or ''] if photos else [])
                        + [f'{ln["qty"]:,.2f}'.rstrip('0').rstrip('.') if ln['qty'] else '—', ln['unit']]
                        + ([_money(ln['rate'], ',.0f') if ln['rate'] else ''] if rate_col else []) + [amount])
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

    styles = _styles()
    elements = []

    # --- Custom Styles ---
    title_style = ParagraphStyle(
        'Title', parent=styles['Title'],
        fontSize=22, fontName=_F.b,
        textColor=BRAND_DARK, alignment=TA_CENTER, spaceAfter=2
    )
    subtitle_style = ParagraphStyle(
        'Subtitle', parent=styles['Normal'],
        fontSize=11, fontName=_F.r,
        textColor=colors.HexColor('#546e7a'), alignment=TA_CENTER, spaceAfter=4
    )
    section_style = ParagraphStyle(
        'Section', parent=styles['Normal'],
        fontSize=10, fontName=_F.b,
        textColor=BRAND_DARK
    )
    normal_style = ParagraphStyle(
        'NormalCustom', parent=styles['Normal'],
        fontSize=9, fontName=_F.r
    )
    right_style = ParagraphStyle(
        'Right', parent=styles['Normal'],
        fontSize=9, alignment=TA_RIGHT
    )
    total_style = ParagraphStyle(
        'Total', parent=styles['Normal'],
        fontSize=13, fontName=_F.b,
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
        ('FONTNAME', (0, 0), (0, 0), _F.b),
        ('FONTNAME', (1, 0), (1, 0), _F.r),
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
        ('FONTNAME', (0, 0), (-1, -1), _F.r),
        ('FONTNAME', (0, 0), (0, -1), _F.b),
        ('FONTNAME', (2, 0), (2, -1), _F.b),
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
                          ('FONTNAME', (0, -1), (-1, -1), _F.b), ('ALIGN', (1, 1), (3, -2), 'CENTER'),
                          ('ALIGN', (4, 1), (4, -1), 'RIGHT'), ('ALIGN', (3, 2), (3, -2), 'RIGHT')]
            if rates_only:
                total_cmds += [('FONTNAME', (0, -1), (-1, -1), _F.i), ('TEXTCOLOR', (0, -1), (-1, -1), colors.HexColor('#546e7a'))]
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
            total_cmds = [('FONTNAME', (3, -1), (-1, -1), _F.b), ('ALIGN', (1, 1), (-1, -1), 'CENTER'),
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
            ('FONTNAME', (0, 1), (-1, 1), _F.b),
            ('ALIGN', (1, 1), (-1, 1), 'CENTER'),
            # Data rows
            ('FONTNAME', (0, 2), (-1, -2), _F.r),
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
        ('FONTNAME', (0, 0), (-1, 0), _F.b),
        ('FONTSIZE', (0, 0), (-1, 0), 9),
        ('FONTNAME', (0, 1), (-1, -2), _F.r),
        ('FONTSIZE', (0, 1), (-1, -1), 9),
        ('ROWBACKGROUNDS', (0, 1), (-1, -2), [colors.white, BRAND_LIGHT]),
        ('BACKGROUND', (0, -1), (-1, -1), BRAND_LIGHT),
        ('FONTNAME', (0, -1), (-1, -1), _F.b),
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
            ('FONTNAME', (0, 0), (-1, 0), _F.b),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('ALIGN', (2, 0), (-1, 0), 'RIGHT'),
            ('PADDING', (0, 0), (-1, 0), 7),
        ]

    if project.gst_amount:                     # GST on quotations
        from . import quote_gst
        total_rows.append(['', '', 'Total', f'Rs. {_money(final_total)}'])
        total_rows.append(['', '', f'GST @ {quote_gst.rate():g}%', f'Rs. {_money(project.gst_amount)}'])
        total_style_cmds += [('ALIGN', (2, len(total_rows) - 2), (-1, len(total_rows) - 1), 'RIGHT'),
                             ('FONTSIZE', (0, len(total_rows) - 2), (-1, len(total_rows) - 1), 10)]
    fi = len(total_rows)
    total_rows.append(['', '' if by_sections else units.area(combo_area_total),
                       'GRAND TOTAL (incl. GST)' if project.gst_amount else 'FINAL TOTAL',
                       f'Rs. {_money(project.total_payable)}'])
    total_style_cmds += [
        ('BACKGROUND', (0, fi), (-1, fi), TOTAL_ROW_BG),
        ('TEXTCOLOR', (0, fi), (-1, fi), TABLE_HEADER_FG),
        ('FONTNAME', (0, fi), (-1, fi), _F.b),
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
        balance = max(project.total_payable - total_paid, 0)
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
                ('FONTNAME', (0, 0), (-1, -1), _F.r),
                ('FONTNAME', (0, 0), (0, -1), _F.b),
                ('FONTNAME', (2, 0), (2, -1), _F.b),
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


def _summary_from_snapshot(snap, page_width, palette):
    """A saved revision's cost summary (one amount per material & work, fittings, other work), then the totals."""
    (BRAND_DARK, BRAND_ACCENT, BRAND_LIGHT, TABLE_HEADER_BG, ROOM_HEADER_BG,
     TABLE_HEADER_FG, TOTAL_ROW_BG, ON_BRAND) = palette
    rows = [['Material & Work Type', 'Amount (Rs.)']]
    rows += [[s['label'], _money(s['amount'])] for s in snap.get('summary') or [] if s.get('amount')]
    if snap.get('fittings_total'):
        rows.append([snap.get('fittings_label') or FIXED_ITEMS_LABEL, _money(snap['fittings_total'])])
    if snap.get('boq_total'):
        rows.append([snap.get('boq_label') or BOQ_ITEMS_LABEL, _money(snap['boq_total'])])
    t = Table(rows, colWidths=[page_width * 0.6, page_width * 0.4])
    t.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, 0), TABLE_HEADER_BG), ('TEXTCOLOR', (0, 0), (-1, 0), TABLE_HEADER_FG),
                           ('FONTNAME', (0, 0), (-1, 0), _F.b), ('FONTSIZE', (0, 0), (-1, -1), 10),
                           ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, BRAND_LIGHT]),
                           ('ALIGN', (1, 0), (1, -1), 'RIGHT'), ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e0e0e0')),
                           ('PADDING', (0, 0), (-1, -1), 8)]))
    return [t] + _totals_elements(snap, page_width, palette)


def generate_customer_pdf(project, payment_settings=None, total_paid=0.0, revision=None):
    """
    The Initial Quotation (customer copy). Room by room (default, Settings → Quotation PDFs): each room with what it's
    made of, its items with sizes and No's, and one amount; fittings as a Hardware row per room. Or by material:
    amount per material. Then the sections (specifications, terms, notes) and payment details.
    revision: a saved revision (QuoteRevision): the quotation exactly as it was then (its own items, rates, totals,
    customer details and date), in the business's layout.
    """
    import json as _json
    rsnap = _json.loads(revision.snapshot) if revision is not None else None
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

    styles = _styles()
    elements = []
    page_width = A4[0] - 3 * cm

    # --- Styles (same as main PDF) ---
    title_style = ParagraphStyle(
        'Title2', parent=styles['Title'],
        fontSize=22, fontName=_F.b,
        textColor=BRAND_DARK, alignment=TA_CENTER, spaceAfter=2
    )
    subtitle_style = ParagraphStyle(
        'Subtitle2', parent=styles['Normal'],
        fontSize=11, fontName=_F.r,
        textColor=colors.HexColor('#546e7a'), alignment=TA_CENTER, spaceAfter=4
    )
    section_style = ParagraphStyle(
        'Section2', parent=styles['Normal'],
        fontSize=10, fontName=_F.b,
        textColor=BRAND_DARK
    )
    normal_style = ParagraphStyle(
        'NormalCustom2', parent=styles['Normal'],
        fontSize=9, fontName=_F.r
    )

    ref = _quote_ref(project) if rsnap is None else (
        f'Rev {revision.number}\n'                          # an earlier version: always say which
        + f'Date: {(revision.created_at + timedelta(hours=5, minutes=30)).strftime("%d %B %Y")}')
    cust = rsnap['customer'] if rsnap else {'name': project.customer_name, 'mobile': project.mobile,
                                            'email': project.email or '', 'address': project.address or ''}
    from . import presentation
    cover = presentation.enabled()             # title page, About us, …, Next steps (console: per business)
    palette = (BRAND_DARK, BRAND_ACCENT, BRAND_LIGHT, TABLE_HEADER_BG, ROOM_HEADER_BG, TABLE_HEADER_FG, TOTAL_ROW_BG, ON_BRAND)
    if cover:
        elements += _title_page(project, cust, ref, page_width, palette, styles)
        elements += _about_page(page_width, palette, styles)
    else:
        # ------- HEADER -------
        elements += _header_elements(title_style, subtitle_style, BRAND_ACCENT)

    # QUOTATION LABEL
    quot_header = Table(
        [['CUSTOMER QUOTATION', ref]],
        colWidths=['65%', '35%']
    )
    quot_header.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, 0), BRAND_DARK),
        ('BACKGROUND', (1, 0), (1, 0), BRAND_LIGHT),
        ('TEXTCOLOR', (0, 0), (0, 0), ON_BRAND),
        ('TEXTCOLOR', (1, 0), (1, 0), BRAND_DARK),
        ('FONTNAME', (0, 0), (0, 0), _F.b),
        ('FONTNAME', (1, 0), (1, 0), _F.r),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('ALIGN', (0, 0), (0, 0), 'CENTER'),
        ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('PADDING', (0, 0), (-1, -1), 8),
    ]))
    elements.append(quot_header)
    elements.append(Spacer(1, 12))

    # ------- CUSTOMER DETAILS (on the title page instead, with presentation pages) -------
    mark = len(elements)
    elements.append(Paragraph("Customer Details", section_style))
    elements.append(Spacer(1, 4))
    cust_data = [
        ['Customer Name', cust['name'], 'Mobile', cust['mobile']],
        ['Email', cust['email'] or '—', 'Prepared By', project.creator.display_name],
    ]
    if cust['address']:
        cust_data.append(['Address', Paragraph(escape(cust['address']), normal_style), '', ''])
    cust_table = Table(cust_data, colWidths=['18%', '32%', '18%', '32%'])
    span_cmds = []
    if cust['address']:
        last = len(cust_data) - 1
        span_cmds = [('SPAN', (1, last), (3, last))]
    cust_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), GREY_BG),
        ('BACKGROUND', (2, 0), (2, -1), GREY_BG),
        ('FONTNAME', (0, 0), (-1, -1), _F.r),
        ('FONTNAME', (0, 0), (0, -1), _F.b),
        ('FONTNAME', (2, 0), (2, -1), _F.b),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#bdbdbd')),
        ('PADDING', (0, 0), (-1, -1), 7),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TEXTCOLOR', (0, 0), (0, -1), BRAND_DARK),
        ('TEXTCOLOR', (2, 0), (2, -1), BRAND_DARK),
    ] + span_cmds))
    elements.append(cust_table)
    elements.append(Spacer(1, 18))
    if cover:
        del elements[mark:]

    from . import layout, plywood
    _rooms2 = project.rooms_with_items()
    if layout.initial_layout() == layout.LAYOUT_BOQ:
        # ------- BOQ: sections A, B, C… with every line's description, quantity, unit, rate and amount -------
        elements.append(HRFlowable(width='100%', thickness=1, color=colors.HexColor('#bdbdbd'), spaceAfter=8))
        elements.append(Paragraph("Bill of Quantities", section_style))
        elements.append(Spacer(1, 8))
        elements += _boq_elements(project, page_width, (BRAND_DARK, BRAND_ACCENT, BRAND_LIGHT, TABLE_HEADER_BG,
                                                        ROOM_HEADER_BG, TABLE_HEADER_FG, TOTAL_ROW_BG, ON_BRAND), styles,
                                  snap=rsnap)
        elements.append(Spacer(1, 20))
    elif layout.initial_layout() == layout.LAYOUT_ROOMS:
        # ------- ROOM BY ROOM: items with sizes and No's, one amount per room, a Hardware row per room -------
        elements.append(HRFlowable(width='100%', thickness=1, color=colors.HexColor('#bdbdbd'), spaceAfter=8))
        elements.append(Paragraph("Quotation", section_style))
        elements.append(Spacer(1, 8))
        elements += _room_rows_elements(project, page_width, (BRAND_DARK, BRAND_ACCENT, BRAND_LIGHT, TABLE_HEADER_BG,
                                                              ROOM_HEADER_BG, TABLE_HEADER_FG, TOTAL_ROW_BG, ON_BRAND), styles,
                                        snap=rsnap)
        elements.append(Spacer(1, 20))
    elif rsnap is not None:
        # ------- COST SUMMARY of a saved revision (its own amounts) -------
        elements.append(HRFlowable(width='100%', thickness=1, color=colors.HexColor('#bdbdbd'), spaceAfter=8))
        elements.append(Paragraph("Cost Summary", section_style))
        elements.append(Spacer(1, 8))
        elements += _summary_from_snapshot(rsnap, page_width, (BRAND_DARK, BRAND_ACCENT, BRAND_LIGHT, TABLE_HEADER_BG,
                                                               ROOM_HEADER_BG, TABLE_HEADER_FG, TOTAL_ROW_BG, ON_BRAND))
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
            ('FONTNAME', (0, 0), (-1, 0), _F.b),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('FONTNAME', (0, 1), (-1, -2), _F.r),
            ('FONTSIZE', (0, 1), (-1, -1), 10),
            ('ROWBACKGROUNDS', (0, 1), (-1, -2), [colors.white, BRAND_LIGHT]),
            ('BACKGROUND', (0, -1), (-1, -1), BRAND_LIGHT),
            ('FONTNAME', (0, -1), (-1, -1), _F.b),
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
                ('FONTNAME', (0, 0), (-1, 0), _F.b),
                ('FONTSIZE', (0, 0), (-1, 0), 10),
                ('ALIGN', (1, 0), (-1, 0), 'RIGHT'),
                ('PADDING', (0, 0), (-1, 0), 8),
            ]

        if project.gst_amount:                 # GST on quotations
            from . import quote_gst
            total_rows.append(['Total', f'Rs. {_money(final_total)}'])
            total_rows.append([f'GST @ {quote_gst.rate():g}%', f'Rs. {_money(project.gst_amount)}'])
            total_style_cmds += [('ALIGN', (1, len(total_rows) - 2), (-1, len(total_rows) - 1), 'RIGHT'),
                                 ('FONTSIZE', (0, len(total_rows) - 2), (-1, len(total_rows) - 1), 10)]
        fi = len(total_rows)
        total_rows.append([f'GRAND TOTAL incl. GST  ({units.area(total_area_all)})' if project.gst_amount
                           else f'FINAL TOTAL  ({units.area(total_area_all)})', f'Rs. {_money(project.total_payable)}'])
        ft_cw = cost_cw
        total_style_cmds += [
            ('BACKGROUND', (0, fi), (-1, fi), TOTAL_ROW_BG),
            ('TEXTCOLOR', (0, fi), (-1, fi), TABLE_HEADER_FG),
            ('FONTNAME', (0, fi), (-1, fi), _F.b),
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
    if not cover:                              # (with presentation pages, the thank-you is on the last page)
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
        balance = max(project.total_payable - total_paid, 0)
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
                ('FONTNAME', (0, 0), (-1, -1), _F.r),
                ('FONTNAME', (0, 0), (0, -1), _F.b),
                ('FONTNAME', (2, 0), (2, -1), _F.b),
                ('FONTSIZE', (0, 0), (-1, -1), 9),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#bdbdbd')),
                ('PADDING', (0, 0), (-1, -1), 7),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('TEXTCOLOR', (0, 0), (0, -1), BRAND_DARK),
                ('TEXTCOLOR', (2, 0), (2, -1), BRAND_DARK),
            ] + span_cmds_pay))
            elements.append(pay_table)

    if cover:
        elements += _closing_page(page_width, palette, styles)
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
    styles = _styles()
    page_width = A4[0] - 3 * cm
    small = ParagraphStyle('InvSmall', parent=styles['Normal'], fontSize=8.5, leading=11)
    small_b = ParagraphStyle('InvSmallB', parent=small, fontName=_F.b, textColor=BRAND_DARK)
    title_style = ParagraphStyle('InvTitle', parent=styles['Title'], fontSize=20, fontName=_F.b,
                                 textColor=BRAND_DARK, alignment=TA_CENTER, spaceAfter=2)
    subtitle_style = ParagraphStyle('InvSub', parent=styles['Normal'], fontSize=10,
                                    textColor=colors.HexColor('#546e7a'), alignment=TA_CENTER, spaceAfter=3)
    seller, buyer = data['seller'], data['buyer']
    elements = []

    # Seller (as it was when the invoice was issued)
    parts = [p for p in (seller['address'].replace('\n', ', '), seller['phone'] and f"Ph: {seller['phone']}",
                         seller['email']) if p]
    gstin = seller['gstin'] and (f"GSTIN: {seller['gstin']}"
                                 + (f"  |  State: {seller['state']} ({seller['state_code']})" if seller['state'] else ''))
    elements += _letterhead(seller['name'], ['  |  '.join(parts), gstin], title_style, subtitle_style, BRAND_ACCENT)

    issued = _date.fromisoformat(data['issued_on'])
    head = Table([[data['title'] + ('  (CANCELLED)' if invoice.status == 'cancelled' else ''),
                   f'Invoice No: {invoice.number}\nDate: {issued.strftime("%d %B %Y")}']],
                 colWidths=[page_width * 0.6, page_width * 0.4])
    head.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, 0), BRAND_DARK), ('BACKGROUND', (1, 0), (1, 0), BRAND_LIGHT),
        ('TEXTCOLOR', (0, 0), (0, 0), ON_BRAND), ('TEXTCOLOR', (1, 0), (1, 0), BRAND_DARK),
        ('FONTNAME', (0, 0), (0, 0), _F.b), ('FONTSIZE', (0, 0), (-1, -1), 10),
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
    supply = [Paragraph('<b>Details</b>', small_b)]
    if (data.get('revision') or 0) > 1:
        supply.append(Paragraph(escape(f"As per quotation Rev {data['revision']}"), small))
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
                            ('FONTNAME', (0, r), (-1, r), _F.b), ('TEXTCOLOR', (0, r), (-1, r), BRAND_DARK),
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
                                ('TEXTCOLOR', (0, r), (-1, r), TABLE_HEADER_FG), ('FONTNAME', (0, r), (-1, r), _F.b),
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
        ('FONTNAME', (0, 0), (-1, 0), _F.b), ('FONTSIZE', (0, 0), (-1, -1), 8.5),
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
        ('FONTNAME', (0, ti), (-1, ti), _F.b), ('FONTSIZE', (0, ti), (-1, ti), 11),
    ]))
    elements += [totals, Spacer(1, 6)]
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


# ── Presentation pages (app/presentation.py): title page, About us, Next steps ──

def _title_page(project, cust, ref, page_width, palette, styles):
    """Page 1: the firm (logo, name, tagline), then "Quotation for" the client, the date (and revision)."""
    (BRAND_DARK, BRAND_ACCENT, BRAND_LIGHT, TABLE_HEADER_BG, ROOM_HEADER_BG,
     TABLE_HEADER_FG, TOTAL_ROW_BG, ON_BRAND) = palette
    brand = get_brand()
    center = lambda name, size, color=BRAND_DARK, bold=False, space=6, leading=None: ParagraphStyle(
        name, parent=styles['Normal'], fontSize=size, leading=leading or size * 1.25, textColor=color, alignment=TA_CENTER,
        fontName=_F.b if bold else _F.r, spaceAfter=space)
    out = [Spacer(1, 2.2 * cm)]
    logo = _logo_flowable(brand, max_height=3.2 * cm, max_width=8 * cm)
    if logo:
        logo.hAlign = 'CENTER'
        out += [logo, Spacer(1, 14)]
    out.append(Paragraph(escape(brand['name']), center('CvName', 28, bold=True, space=6)))
    if brand.get('tagline'):
        out.append(Paragraph(escape(brand['tagline']), center('CvTag', 12, colors.HexColor('#546e7a'))))
    out += [Spacer(1, 10), HRFlowable(width='40%', thickness=2, color=BRAND_ACCENT, hAlign='CENTER'), Spacer(1, 2.4 * cm),
            Paragraph('QUOTATION', center('CvQ', 13, BRAND_ACCENT, bold=True, space=10)),
            Paragraph('Prepared for', center('CvFor', 10, colors.HexColor('#546e7a'), space=4)),
            Paragraph(escape(cust['name'] or ''), center('CvCust', 22, bold=True, space=6))]
    for line in [cust.get('address') or '', cust.get('mobile') or '', cust.get('email') or '']:
        if line:
            out.append(Paragraph(escape(line).replace('\n', '<br/>'), center('CvCl', 10, colors.HexColor('#37474f'), space=2)))
    cells = [line.replace('Date:', '').strip() for line in ref.split('\n') if line.strip()]
    cells.append('Prepared by ' + project.creator.display_name)
    info = Table([cells], colWidths=[page_width / len(cells)] * len(cells))
    info.setStyle(TableStyle([('FONTSIZE', (0, 0), (-1, -1), 9), ('TEXTCOLOR', (0, 0), (-1, -1), BRAND_DARK),
                              ('ALIGN', (0, 0), (-1, -1), 'CENTER'), ('LINEABOVE', (0, 0), (-1, 0), 0.5, colors.HexColor('#bdbdbd')),
                              ('LINEBELOW', (0, 0), (-1, 0), 0.5, colors.HexColor('#bdbdbd')), ('PADDING', (0, 0), (-1, -1), 8)]))
    out += [Spacer(1, 1.6 * cm), info, Spacer(1, 2.2 * cm)]
    contact = '  |  '.join(x for x in [(brand['address'] or '').replace('\n', ', '), brand['phone'] and f"Ph: {brand['phone']}",
                                        brand['email'], brand['gstin'] and f"GSTIN: {brand['gstin']}"] if x)
    if contact:
        out.append(Paragraph(escape(contact), center('CvContact', 8.5, colors.HexColor('#546e7a'))))
    out.append(PageBreak())
    return out


def _rich_flowables(html, dark, styles):
    """Text from the rich text editor (app/richtext.py) as PDF paragraphs: headings, alignment, colours, lists."""
    from . import richtext
    align = {'left': TA_LEFT, 'center': TA_CENTER, 'right': TA_RIGHT, 'justify': TA_JUSTIFY}
    body = ParagraphStyle('RtB', parent=styles['Normal'], fontSize=10.5, leading=16, textColor=colors.HexColor('#263238'),
                          spaceAfter=8)
    heads = {'h1': (17, 8), 'h2': (14, 6), 'h3': (12, 4)}
    out, counters = [], {}
    for b in richtext.blocks(html):
        al = align.get(b['align'], TA_LEFT)
        if b['kind'] in heads:
            size, after = heads[b['kind']]
            st = ParagraphStyle(f'Rt{b["kind"]}', parent=body, fontName=_F.b, fontSize=size, leading=size * 1.3,
                                textColor=dark, spaceBefore=6, spaceAfter=after, alignment=al)
            out.append(Paragraph(b['markup'] or '&nbsp;', st))
            counters.clear()
        elif b['kind'] == 'li':
            level = b['indent']
            if b['list'] == 'ordered':
                for deeper in [k for k in counters if k > level]:
                    counters.pop(deeper)
                counters[level] = counters.get(level, 0) + 1
                mark = f'{counters[level]}.'
            else:
                mark = '•'
            st = ParagraphStyle('RtLi', parent=body, leftIndent=18 + 16 * level, bulletIndent=4 + 16 * level,
                                spaceAfter=4, alignment=al)
            out.append(Paragraph(b['markup'] or '&nbsp;', st, bulletText=mark))
        else:
            counters.clear()
            if not b['markup'] or b['markup'] == '<br/>':
                out.append(Spacer(1, 8))
                continue
            out.append(Paragraph(b['markup'], ParagraphStyle('RtP', parent=body, alignment=al)))
    return out


def _about_page(page_width, palette, styles):
    """Page 2: the firm's own "About us" (left out when they haven't written one)."""
    from . import presentation
    content = presentation.content()
    paras = content['about']
    if not paras and not content['about_html']:
        return []
    dark = palette[0]
    brand = get_brand()
    head = ParagraphStyle('AbH', parent=styles['Normal'], fontSize=20, leading=26, textColor=dark, fontName=_F.b,
                          spaceAfter=6)
    body = ParagraphStyle('AbB', parent=styles['Normal'], fontSize=10.5, leading=16, textColor=colors.HexColor('#263238'),
                          spaceAfter=10)
    bullet = ParagraphStyle('AbL', parent=body, leftIndent=14, firstLineIndent=-10, spaceAfter=4)
    out = [Spacer(1, 1 * cm), Paragraph(f'About {escape(brand["name"])}', head),
           HRFlowable(width='20%', thickness=2, color=palette[1], hAlign='LEFT', spaceAfter=14)]
    if content['about_html']:
        out += _rich_flowables(content['about_html'], dark, styles)
        paras = []
    for p in paras:
        lines = p.split('\n')
        if all(l.strip()[:1] in ('-', '•', '*') for l in lines if l.strip()):
            out += [Paragraph('•&nbsp;&nbsp;' + escape(l.strip().lstrip('-•* ')), bullet) for l in lines if l.strip()]
            out.append(Spacer(1, 6))
        else:
            out.append(Paragraph(escape(p).replace('\n', '<br/>'), body))
    out.append(PageBreak())
    return out


def _closing_page(page_width, palette, styles):
    """Last page: the next steps (numbered) and the thank-you note, with the firm's contact details."""
    from . import presentation
    (BRAND_DARK, BRAND_ACCENT, BRAND_LIGHT, TABLE_HEADER_BG, ROOM_HEADER_BG,
     TABLE_HEADER_FG, TOTAL_ROW_BG, ON_BRAND) = palette
    brand = get_brand()
    head = ParagraphStyle('NxH', parent=styles['Normal'], fontSize=20, leading=26, textColor=BRAND_DARK,
                          fontName=_F.b, spaceAfter=6)
    body = ParagraphStyle('NxB', parent=styles['Normal'], fontSize=10.5, leading=15, textColor=colors.HexColor('#263238'))
    num = ParagraphStyle('NxN', parent=body, fontName=_F.b, textColor=ON_BRAND, alignment=TA_CENTER)
    content = presentation.content()
    if content['steps_html']:                     # formatted in the editor: as they wrote it
        t = _rich_flowables(content['steps_html'], BRAND_DARK, styles)
    else:
        steps = content['steps']
        rows = [[Paragraph(str(i), num), Paragraph(escape(step), body)] for i, step in enumerate(steps, 1)]
        t = Table(rows, colWidths=[1 * cm, page_width - 1.3 * cm])
        t.setStyle(TableStyle([('BACKGROUND', (0, 0), (0, -1), BRAND_DARK), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                               ('TOPPADDING', (0, 0), (-1, -1), 8), ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
                               ('LEFTPADDING', (1, 0), (1, -1), 12), ('LINEBELOW', (1, 0), (1, -2), 0.5, colors.HexColor('#e0e0e0'))]))
        t = [t]
    thanks = ParagraphStyle('NxT', parent=styles['Normal'], fontSize=15, leading=21, textColor=BRAND_DARK, alignment=TA_CENTER)
    small = ParagraphStyle('NxS', parent=styles['Normal'], fontSize=9, leading=13, textColor=colors.HexColor('#546e7a'),
                           alignment=TA_CENTER)
    contact = '  |  '.join(x for x in [brand['phone'] and f"Ph: {brand['phone']}", brand['email']] if x)
    return [PageBreak(), Spacer(1, 1 * cm), Paragraph('Next steps', head),
            HRFlowable(width='20%', thickness=2, color=BRAND_ACCENT, hAlign='LEFT', spaceAfter=16), *t,
            Spacer(1, 2.4 * cm), HRFlowable(width='40%', thickness=1, color=BRAND_ACCENT, hAlign='CENTER', spaceAfter=18),
            Paragraph(_thank_you_text(), thanks), Spacer(1, 8),
            Paragraph('We look forward to working with you.' if 'look forward' not in _thank_you_text() else '', small),
            Spacer(1, 6), Paragraph(escape(contact), small) if contact else Spacer(1, 1)]
