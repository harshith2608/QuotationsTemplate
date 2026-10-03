import os
from io import BytesIO
from xml.sax.saxutils import escape
from flask import current_app
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                 TableStyle, HRFlowable, Image)
from reportlab.lib.utils import ImageReader
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from .models import AppSetting
from .catalog import WOOD_TYPES, WORK_TYPES, DEFAULT_WORK
from .branding import get_brand, STATIC_BRAND, tint


DEFAULT_TERMS = (
    "1. This is a preliminary estimate. Final price may vary based on site conditions and material selection.\n"
    "2. This quotation is valid for 30 days from the date of issue.\n"
    "3. A 50% advance payment is required to commence work.\n"
    "4. Delivery and installation timelines will be communicated separately.\n"
    "5. Any changes to design or material after order confirmation may attract additional charges."
)


def _get_terms_lines():
    """Return T&C as a list of non-empty lines, falling back to defaults."""
    raw = AppSetting.get('terms_conditions', '').strip()
    lines = [l.strip() for l in (raw or DEFAULT_TERMS).splitlines() if l.strip()]
    return lines


def ft_in(decimal_ft):
    """Convert decimal feet to 'X ft Y in' string."""
    try:
        decimal_ft = float(decimal_ft or 0)
    except (ValueError, TypeError):
        return '—'
    feet = int(decimal_ft)
    inches = round((decimal_ft - feet) * 12)
    if inches == 12:
        feet += 1
        inches = 0
    if inches == 0:
        return f"{feet} ft"
    return f"{feet} ft {inches} in"

# Brand colors (from BRAND_PRIMARY / BRAND_ACCENT env vars)
_PRIMARY = STATIC_BRAND['primary']
BRAND_DARK = colors.HexColor(_PRIMARY)
BRAND_ACCENT = colors.HexColor(STATIC_BRAND['accent'])
BRAND_LIGHT = colors.HexColor(tint(_PRIMARY, 0.9))
GREY_BG = colors.HexColor('#f5f5f5')
TABLE_HEADER_BG = colors.HexColor(tint(_PRIMARY, 0.85))
ROOM_HEADER_BG  = colors.HexColor(tint(_PRIMARY, 0.75))
TABLE_HEADER_FG = BRAND_DARK
TOTAL_ROW_BG    = ROOM_HEADER_BG


def _logo_flowable(brand, max_height=1.6 * cm, max_width=6 * cm):
    """Return a reportlab Image for LOGO_FILE (PNG/JPG under static/), or None."""
    if not brand.get('logo_file'):
        return None
    path = os.path.join(current_app.static_folder, brand['logo_file'])
    try:
        w, h = ImageReader(path).getSize()
    except Exception:
        current_app.logger.warning(f'LOGO_FILE could not be loaded for PDF: {path}')
        return None
    scale = min(max_height / h, max_width / w)
    return Image(path, width=w * scale, height=h * scale)


def _header_elements(title_style, subtitle_style):
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
    elements.append(HRFlowable(width='100%', thickness=2, color=BRAND_ACCENT, spaceAfter=8))
    return elements


def _thank_you_text():
    return (f"Thank you for choosing <b>{escape(get_brand()['name'])}</b>. "
            "We look forward to transforming your space!")


def _signatory():
    brand = get_brand()
    return escape(brand['signatory_name']), escape(brand['signatory_title'])


def generate_pdf(project, payment_settings=None, total_paid=0.0):
    """
    Generate a professional PDF quotation and return a BytesIO buffer.
    payment_settings: dict with keys upi_id, bank_name, account_name,
                      account_number, ifsc_code  (optional)
    total_paid: float – amount already received (optional)
    """
    """Generate a professional PDF quotation and return a BytesIO buffer."""
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
    elements += _header_elements(title_style, subtitle_style)

    # QUOTATION LABEL
    quot_header = Table(
        [['INTERIOR DESIGN QUOTATION',
          f'Quotation #: {project.id}\nDate: {project.created_at.strftime("%d %B %Y")}']],
        colWidths=['65%', '35%']
    )
    quot_header.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, 0), BRAND_DARK),
        ('BACKGROUND', (1, 0), (1, 0), BRAND_LIGHT),
        ('TEXTCOLOR', (0, 0), (0, 0), colors.white),
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

    item_col_widths = ['22%', '11%', '11%', '24%', '14%', '18%']
    page_width = A4[0] - 3 * cm
    col_widths = [page_width * float(p.strip('%')) / 100 for p in item_col_widths]

    from .models import ItemRate as _ItemRate
    _item_rates_map = {f'{r.wood_type}|{r.work_type}': r.rate_per_sqft for r in _ItemRate.query.all()}

    for room in project.rooms.all():
        # Room header row
        room_header = Table(
            [[f'  {room.name.upper()}']],
            colWidths=[page_width]
        )
        room_header.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), ROOM_HEADER_BG),
            ('TEXTCOLOR', (0, 0), (-1, -1), TABLE_HEADER_FG),
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('PADDING', (0, 0), (-1, -1), 6),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ]))
        elements.append(room_header)

        # Items table
        item_rows = [['Item Name', 'Length', 'Width', 'Material & Work', 'Area (sqft)', 'Subtotal (Rs.)']]
        room_total_area = 0.0
        room_total_cost = 0.0
        for item in room.items.all():
            work_type  = getattr(item, 'work_type', DEFAULT_WORK)
            rate       = _item_rates_map.get(f'{item.wood_type}|{work_type}', 0.0)
            subtotal   = item.area * rate
            room_total_area += item.area
            room_total_cost += subtotal
            item_rows.append([
                item.name,
                ft_in(item.length),
                ft_in(item.width),
                f'{item.wood_type} – {work_type}',
                f'{item.area:.2f}',
                f'{subtotal:,.2f}'
            ])
        # Room total row
        item_rows.append(['', '', '', 'Room Total:', f'{room_total_area:.2f} sqft', f'Rs. {room_total_cost:,.2f}'])

        item_table = Table(item_rows, colWidths=col_widths)
        item_table.setStyle(TableStyle([
            # Header row
            ('BACKGROUND', (0, 0), (-1, 0), TABLE_HEADER_BG),
            ('TEXTCOLOR', (0, 0), (-1, 0), TABLE_HEADER_FG),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 8),
            ('ALIGN', (1, 0), (-1, 0), 'CENTER'),
            # Data rows
            ('FONTNAME', (0, 1), (-1, -2), 'Helvetica'),
            ('FONTSIZE', (0, 1), (-1, -1), 8),
            ('ALIGN', (1, 1), (-1, -1), 'CENTER'),
            ('ALIGN', (0, 1), (0, -1), 'LEFT'),
            ('ALIGN', (5, 1), (5, -1), 'RIGHT'),
            # Alternating row colors
            ('ROWBACKGROUNDS', (0, 1), (-1, -2), [colors.white, colors.HexColor('#fafafa')]),
            # Total row
            ('BACKGROUND', (0, -1), (-1, -1), BRAND_LIGHT),
            ('FONTNAME', (3, -1), (-1, -1), 'Helvetica-Bold'),
            ('TEXTCOLOR', (3, -1), (-1, -1), BRAND_DARK),
            ('ALIGN', (3, -1), (4, -1), 'CENTER'),
            ('ALIGN', (5, -1), (5, -1), 'RIGHT'),
            # Grid
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e0e0e0')),
            ('LINEBELOW', (0, 0), (-1, 0), 1, BRAND_DARK),
            ('PADDING', (0, 0), (-1, -1), 5),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ]))
        elements.append(item_table)
        elements.append(Spacer(1, 8))

    # ------- COST SUMMARY -------
    elements.append(Spacer(1, 6))
    elements.append(HRFlowable(width='100%', thickness=1, color=colors.HexColor('#bdbdbd'), spaceAfter=8))
    elements.append(Paragraph("Cost Summary", section_style))
    elements.append(Spacer(1, 6))

    item_totals = project.get_item_totals()  # { 'wood|work': area }
    summary_cw = [page_width * p for p in [0.35, 0.22, 0.22, 0.21]]

    # Combined material + work cost table
    elements.append(Spacer(1, 3))
    combo_data = [['Material & Work Type', 'Total Area (sqft)', 'Rate (Rs./sqft)', 'Amount (Rs.)']]
    combo_total = 0.0
    combo_area_total = 0.0
    for wood in WOOD_TYPES:
        for work in WORK_TYPES:
            key = f'{wood}|{work}'
            area = item_totals.get(key, 0.0)
            if area > 0:
                rate = _item_rates_map.get(key, 0.0)
                subtotal = area * rate
                combo_total += subtotal
                combo_area_total += area
                combo_data.append([f'{wood} – {work}', f'{area:,.2f}', f'{rate:,.0f}', f'{subtotal:,.2f}'])
    combo_data.append(['', '', 'Subtotal', f'Rs. {combo_total:,.2f}'])

    combo_table = Table(combo_data, colWidths=summary_cw)
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
        ('TEXTCOLOR', (2, -1), (-1, -1), BRAND_DARK),
        ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
        ('ALIGN', (0, 0), (0, -1), 'LEFT'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e0e0e0')),
        ('PADDING', (0, 0), (-1, -1), 7),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    elements.append(combo_table)
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
        total_rows.append(['', '', disc_label, f'- Rs. {discount_amount:,.2f}'])
        total_style_cmds += [
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#fef2f2')),
            ('TEXTCOLOR', (2, 0), (-1, 0), colors.HexColor('#b91c1c')),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('ALIGN', (2, 0), (-1, 0), 'RIGHT'),
            ('PADDING', (0, 0), (-1, 0), 7),
        ]

    fi = len(total_rows)
    total_rows.append(['', f'{combo_area_total:,.2f} sqft', 'FINAL TOTAL', f'Rs. {final_total:,.2f}'])
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

    # ------- PLYWOOD THICKNESS -------
    _ply_raw = (project.plywood_thickness or '').strip()
    if _ply_raw:
        ply_items = [p.strip() for p in _ply_raw.split(',') if p.strip()]
        if ply_items:
            elements.append(HRFlowable(width='100%', thickness=1, color=colors.HexColor('#bdbdbd'), spaceAfter=8))
            ply_header_style = ParagraphStyle('PlyHeader', parent=styles['Normal'],
                                              fontSize=9, textColor=BRAND_DARK,
                                              fontName='Helvetica-Bold', spaceBefore=4, spaceAfter=4)
            ply_body_style = ParagraphStyle('PlyBody', parent=styles['Normal'],
                                            fontSize=8, textColor=colors.HexColor('#333333'),
                                            leading=13, spaceAfter=1)
            elements.append(Paragraph("Plywood Used:", ply_header_style))
            elements.append(Spacer(1, 4))
            for ply in ply_items:
                elements.append(Paragraph(f"• {ply}", ply_body_style))
            elements.append(Spacer(1, 14))

    # ------- MATERIAL SPECIFICATIONS -------
    _specs = AppSetting.get('material_specs', '')
    if _specs and _specs.strip():
        elements.append(HRFlowable(width='100%', thickness=1, color=colors.HexColor('#bdbdbd'), spaceAfter=8))
        spec_header_style = ParagraphStyle('SpecHeader', parent=styles['Normal'],
                                           fontSize=9, textColor=BRAND_DARK,
                                           fontName='Helvetica-Bold', spaceBefore=4, spaceAfter=4)
        spec_body_style = ParagraphStyle('SpecBody', parent=styles['Normal'],
                                         fontSize=8, textColor=colors.HexColor('#333333'),
                                         leading=13, spaceAfter=1)
        elements.append(Paragraph("Material Specifications:", spec_header_style))
        elements.append(Spacer(1, 4))
        for line in _specs.splitlines():
            line = line.strip()
            if line:
                # Replace bullet character ● with a PDF-safe bullet
                display = line.replace('●', '\u2022')
                elements.append(Paragraph(display, spec_body_style))
        elements.append(Spacer(1, 14))

    # ------- TERMS & CONDITIONS -------
    elements.append(HRFlowable(width='100%', thickness=1, color=colors.HexColor('#bdbdbd'), spaceAfter=8))
    tc_style = ParagraphStyle('TC', parent=styles['Normal'],
                              fontSize=7.5, textColor=colors.HexColor('#757575'))
    elements.append(Paragraph("<b>Terms &amp; Conditions:</b>", tc_style))
    for term in _get_terms_lines():
        elements.append(Paragraph(term, tc_style))
    elements.append(Spacer(1, 8))
    elements.append(Paragraph(
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
            pay_rows.append(['Amount Paid', f'Rs. {total_paid:,.2f}',
                             'Balance Due', f'Rs. {balance:,.2f}'])

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

    # ------- SIGNATURE SECTION -------
    elements.append(Spacer(1, 36))
    elements.append(HRFlowable(width='100%', thickness=0.5, color=colors.HexColor('#bdbdbd'), spaceAfter=24))
    _sig_name_style = ParagraphStyle('SigName', parent=styles['Normal'],
                                     fontSize=9, fontName='Helvetica-Bold', textColor=BRAND_DARK)
    _sig_role_style = ParagraphStyle('SigRole', parent=styles['Normal'],
                                     fontSize=8, textColor=colors.HexColor('#757575'))
    sig_col = page_width * 0.42
    sig_gap = page_width * 0.16
    _sig_name, _sig_title = _signatory()
    sig_table = Table(
        [
            ['', '', ''],
            [Paragraph(project.customer_name, _sig_name_style), '',
             Paragraph(_sig_name, _sig_name_style)],
            [Paragraph('Customer', _sig_role_style), '',
             Paragraph(_sig_title, _sig_role_style)],
        ],
        colWidths=[sig_col, sig_gap, sig_col]
    )
    sig_table.setStyle(TableStyle([
        ('TOPPADDING',    (0, 0), (-1, 0), 42),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 0),
        ('LINEABOVE', (0, 1), (0, 1), 0.8, BRAND_DARK),
        ('LINEABOVE', (2, 1), (2, 1), 0.8, BRAND_DARK),
        ('ALIGN', (0, 0), (0, -1), 'LEFT'),
        ('ALIGN', (2, 0), (2, -1), 'RIGHT'),
        ('TOPPADDING',    (0, 1), (-1, 1), 5),
        ('BOTTOMPADDING', (0, 1), (-1, 1), 2),
        ('TOPPADDING',    (0, 2), (-1, 2), 1),
        ('BOTTOMPADDING', (0, 2), (-1, 2), 0),
        ('LEFTPADDING',  (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
    ]))
    elements.append(sig_table)

    doc.build(elements)
    buffer.seek(0)
    return buffer


def generate_customer_pdf(project, payment_settings=None, total_paid=0.0):
    """
    Generate a customer-facing PDF: total costs only, no measurements.
    Shows material type → amount, final total, material specs, and T&C.
    """
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
    elements += _header_elements(title_style, subtitle_style)

    # QUOTATION LABEL
    quot_header = Table(
        [['CUSTOMER QUOTATION',
          f'Quotation #: {project.id}\nDate: {project.created_at.strftime("%d %B %Y")}']],
        colWidths=['65%', '35%']
    )
    quot_header.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, 0), BRAND_DARK),
        ('BACKGROUND', (1, 0), (1, 0), BRAND_LIGHT),
        ('TEXTCOLOR', (0, 0), (0, 0), colors.white),
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

    # ------- COST SUMMARY -------
    elements.append(HRFlowable(width='100%', thickness=1, color=colors.HexColor('#bdbdbd'), spaceAfter=8))
    elements.append(Paragraph("Cost Summary", section_style))
    elements.append(Spacer(1, 8))

    from .models import ItemRate as _ItemRate2
    _item_rates_map2 = {f'{r.wood_type}|{r.work_type}': r.rate_per_sqft for r in _ItemRate2.query.all()}

    item_totals2 = project.get_item_totals()  # { 'wood|work': area }

    # Cost summary — show material+work combo and amount only (no area, no rate)
    cost_cw   = [page_width * p for p in [0.60, 0.40]]
    cost_data = [['Material & Work Type', 'Amount (Rs.)']]
    mat_total = 0.0
    total_area_all = 0.0
    for wood in WOOD_TYPES:
        for work in WORK_TYPES:
            key = f'{wood}|{work}'
            area = item_totals2.get(key, 0.0)
            if area > 0:
                subtotal      = area * _item_rates_map2.get(key, 0.0)
                mat_total    += subtotal
                total_area_all += area
                cost_data.append([f'{wood} – {work}', f'{subtotal:,.2f}'])
    cost_data.append(['Total', f'Rs. {mat_total:,.2f}'])

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
        total_rows.append([disc_label, f'- Rs. {discount_amount:,.2f}'])
        total_style_cmds += [
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#fef2f2')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.HexColor('#b91c1c')),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('ALIGN', (1, 0), (-1, 0), 'RIGHT'),
            ('PADDING', (0, 0), (-1, 0), 8),
        ]

    fi = len(total_rows)
    total_rows.append([f'FINAL TOTAL  ({total_area_all:,.2f} sqft)', f'Rs. {final_total:,.2f}'])
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

    # ------- PLYWOOD THICKNESS -------
    _ply_raw2 = (project.plywood_thickness or '').strip()
    if _ply_raw2:
        ply_items2 = [p.strip() for p in _ply_raw2.split(',') if p.strip()]
        if ply_items2:
            elements.append(HRFlowable(width='100%', thickness=1, color=colors.HexColor('#bdbdbd'), spaceAfter=8))
            ply_header_style2 = ParagraphStyle('PlyHeader2', parent=styles['Normal'],
                                               fontSize=9, textColor=BRAND_DARK,
                                               fontName='Helvetica-Bold', spaceBefore=4, spaceAfter=4)
            ply_body_style2 = ParagraphStyle('PlyBody2', parent=styles['Normal'],
                                             fontSize=8, textColor=colors.HexColor('#333333'),
                                             leading=13, spaceAfter=1)
            elements.append(Paragraph("Plywood Used:", ply_header_style2))
            elements.append(Spacer(1, 4))
            for ply in ply_items2:
                elements.append(Paragraph(f"• {ply}", ply_body_style2))
            elements.append(Spacer(1, 14))

    # ------- MATERIAL SPECIFICATIONS -------
    _specs = AppSetting.get('material_specs', '')
    if _specs and _specs.strip():
        elements.append(HRFlowable(width='100%', thickness=1, color=colors.HexColor('#bdbdbd'), spaceAfter=8))
        spec_header_style = ParagraphStyle('SpecHeader2', parent=styles['Normal'],
                                           fontSize=9, textColor=BRAND_DARK,
                                           fontName='Helvetica-Bold', spaceBefore=4, spaceAfter=4)
        spec_body_style = ParagraphStyle('SpecBody2', parent=styles['Normal'],
                                         fontSize=8, textColor=colors.HexColor('#333333'),
                                         leading=13, spaceAfter=1)
        elements.append(Paragraph("Material Specifications:", spec_header_style))
        elements.append(Spacer(1, 4))
        for line in _specs.splitlines():
            line = line.strip()
            if line:
                elements.append(Paragraph(line.replace('●', '\u2022'), spec_body_style))
        elements.append(Spacer(1, 14))

    # ------- TERMS & CONDITIONS -------
    elements.append(HRFlowable(width='100%', thickness=1, color=colors.HexColor('#bdbdbd'), spaceAfter=8))
    tc_style = ParagraphStyle('TC2', parent=styles['Normal'],
                              fontSize=7.5, textColor=colors.HexColor('#757575'))
    elements.append(Paragraph("<b>Terms &amp; Conditions:</b>", tc_style))
    for term in _get_terms_lines():
        elements.append(Paragraph(term, tc_style))
    elements.append(Spacer(1, 8))
    elements.append(Paragraph(
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
            pay_rows.append(['Amount Paid', f'Rs. {total_paid:,.2f}', 'Balance Due', f'Rs. {balance:,.2f}'])
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

    # ------- SIGNATURE SECTION -------
    elements.append(Spacer(1, 36))
    elements.append(HRFlowable(width='100%', thickness=0.5, color=colors.HexColor('#bdbdbd'), spaceAfter=24))
    _sig_name_style2 = ParagraphStyle('SigName2', parent=styles['Normal'],
                                      fontSize=9, fontName='Helvetica-Bold', textColor=BRAND_DARK)
    _sig_role_style2 = ParagraphStyle('SigRole2', parent=styles['Normal'],
                                      fontSize=8, textColor=colors.HexColor('#757575'))
    sig_col2 = page_width * 0.42
    sig_gap2 = page_width * 0.16
    _sig_name2, _sig_title2 = _signatory()
    sig_table2 = Table(
        [
            ['', '', ''],
            [Paragraph(project.customer_name, _sig_name_style2), '',
             Paragraph(_sig_name2, _sig_name_style2)],
            [Paragraph('Customer', _sig_role_style2), '',
             Paragraph(_sig_title2, _sig_role_style2)],
        ],
        colWidths=[sig_col2, sig_gap2, sig_col2]
    )
    sig_table2.setStyle(TableStyle([
        ('TOPPADDING',    (0, 0), (-1, 0), 42),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 0),
        ('LINEABOVE', (0, 1), (0, 1), 0.8, BRAND_DARK),
        ('LINEABOVE', (2, 1), (2, 1), 0.8, BRAND_DARK),
        ('ALIGN', (0, 0), (0, -1), 'LEFT'),
        ('ALIGN', (2, 0), (2, -1), 'RIGHT'),
        ('TOPPADDING',    (0, 1), (-1, 1), 5),
        ('BOTTOMPADDING', (0, 1), (-1, 1), 2),
        ('TOPPADDING',    (0, 2), (-1, 2), 1),
        ('BOTTOMPADDING', (0, 2), (-1, 2), 0),
        ('LEFTPADDING',  (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
    ]))
    elements.append(sig_table2)

    doc.build(elements)
    buffer.seek(0)
    return buffer
