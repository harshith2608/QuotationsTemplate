"""The fictional firm's "old quotation" for the import video (tools/tutorials/import_walkthrough.py): a 3 BHK quote
made in Excel and saved as PDF, the way most firms send them (grid lines, a yellow header row). Every name, number
and address is made up.

    python tools/tutorials/import_sample_pdf.py <out.pdf>
"""
import sys

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

FIRM = 'NEST & GRAIN INTERIORS'
FIRM_LINE = '14, 2nd Cross, Sample Layout, Bengaluru 560001  |  +91 90000 11122  |  hello@nestandgrain.example'
CUSTOMER = ['Mr. Arjun Mehta (sample)', 'Villa 12, Palm Meadows, Whitefield', '+91 90000 22233']
# section, [(item, description, unit, qty, rate)]
SECTIONS = [
    ('LIVING & DINING', [
        ('TV Unit with Back Panel', 'Laminate finish, profile handles', 'Sq.ft', 42, 1450),
        ('Shoe Rack', 'Laminate, 2 shutters', 'Sq.ft', 12, 1350),
        ('Crockery Unit', 'Glass shutters with profile light', 'Sq.ft', 24, 1650)]),
    ('KITCHEN', [
        ('Kitchen Base Units', 'BWP ply, acrylic shutters', 'Sq.ft', 33, 1800),
        ('Kitchen Wall Units', 'Acrylic shutters, lift-up', 'Sq.ft', 24, 1700),
        ('Tandem Drawers', 'Soft-close, with inner drawer', 'Nos', 4, 4500),
        ('Quartz Countertop', '20 mm, with backsplash', 'R.ft', 11, 2200)]),
    ('MASTER BEDROOM', [
        ('Wardrobe with Loft', 'Laminate, soft-close hinges', 'Sq.ft', 70, 1500),
        ('Bed with Storage', 'Hydraulic lift, laminate', 'Nos', 1, 42000),
        ('Dresser with Mirror', 'Mirror with storage below', 'Sq.ft', 9, 1600)]),
    ('SERVICES', [
        ('False Ceiling', 'Gypsum with cove lighting', 'Sq.ft', 650, 120),
        ('Painting', 'Putty, primer and 2 coats emulsion', 'Sq.ft', 1850, 22),
        ('Electrical Wiring', 'New points, wire and switches', 'Point', 45, 650)]),
]
DESIGN_FEE_PCT = 5
DISCOUNT = 10000
GST = 18
PAYMENT = ['10% on booking', '50% on design sign-off', '35% before installation', '5% on handover']
TERMS = ['Prices valid for 30 days from the date of this quotation.',
         'Appliances, sanitaryware and electrical fixtures are not included.',
         'Any work beyond this quotation will be charged separately.',
         'Installation: 45 working days from design sign-off.']


def money(v):
    """Indian grouping: 1,45,000."""
    s = f'{int(round(v))}'
    head, tail = s[:-3], s[-3:]
    while len(head) > 2:
        tail = head[-2:] + ',' + tail
        head = head[:-2]
    return (head + ',' + tail) if head else tail


def totals():
    sub = sum(q * r for _, rows in SECTIONS for _, _, _, q, r in rows)
    fee = round(sub * DESIGN_FEE_PCT / 100)
    taxable = sub + fee - DISCOUNT
    gst = round(taxable * GST / 100)
    return sub, fee, taxable, gst, taxable + gst


def build(path):
    doc = SimpleDocTemplate(path, pagesize=A4, leftMargin=1.4 * cm, rightMargin=1.4 * cm, topMargin=1.2 * cm,
                            bottomMargin=1.2 * cm, title='Quotation')
    st = lambda size, bold=False, align=0: ParagraphStyle('s', fontName='Helvetica-Bold' if bold else 'Helvetica',
                                                          fontSize=size, leading=size + 3, alignment=align)
    grid = colors.HexColor('#9e9e9e')
    yellow = colors.HexColor('#ffe699')
    el = [Paragraph(FIRM, st(17, True, 1)), Paragraph(FIRM_LINE, st(8, False, 1)), Spacer(1, 8),
          Table([[Paragraph('<b>QUOTATION</b>', st(12, True, 1))]], colWidths=[doc.width],
                style=[('BACKGROUND', (0, 0), (-1, -1), yellow), ('BOX', (0, 0), (-1, -1), 0.6, grid)]),
          Spacer(1, 6)]
    info = Table([[Paragraph('<b>To:</b><br/>' + '<br/>'.join(CUSTOMER), st(9)),
                   Paragraph('<b>Quote No:</b> NG/26-27/118<br/><b>Date:</b> 12-10-2026<br/><b>Project:</b> 3 BHK interiors',
                             st(9))]], colWidths=[doc.width * 0.6, doc.width * 0.4],
                 style=[('BOX', (0, 0), (-1, -1), 0.6, grid), ('INNERGRID', (0, 0), (-1, -1), 0.6, grid),
                        ('VALIGN', (0, 0), (-1, -1), 'TOP')])
    el += [info, Spacer(1, 8)]
    head = ['Sr', 'Item', 'Description', 'Unit', 'Qty', 'Rate', 'Amount']
    rows, styles = [head], [('BACKGROUND', (0, 0), (-1, 0), yellow), ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold')]
    for si, (sec, lines) in enumerate(SECTIONS, 1):
        rows.append([chr(64 + si), sec, '', '', '', '', ''])
        styles += [('SPAN', (1, len(rows) - 1), (-1, len(rows) - 1)), ('FONTNAME', (0, len(rows) - 1), (-1, len(rows) - 1), 'Helvetica-Bold'),
                   ('BACKGROUND', (0, len(rows) - 1), (-1, len(rows) - 1), colors.HexColor('#f2f2f2'))]
        for li, (item, desc, unit, q, r) in enumerate(lines, 1):
            rows.append([f'{si}.{li}', item, desc, unit, f'{q:g}', money(r), money(q * r)])
    sub, fee, taxable, gst, grand = totals()
    for label, value, bold in ((f'Sub Total', sub, True), (f'Design fee @ {DESIGN_FEE_PCT}%', fee, False),
                               ('Less: Discount', -DISCOUNT, False), ('Taxable Amount', taxable, True),
                               (f'GST @ {GST}%', gst, False), ('GRAND TOTAL', grand, True)):
        rows.append(['', label, '', '', '', '', ('- ' if value < 0 else '') + money(abs(value))])
        styles += [('SPAN', (1, len(rows) - 1), (5, len(rows) - 1))]
        if bold:
            styles.append(('FONTNAME', (0, len(rows) - 1), (-1, len(rows) - 1), 'Helvetica-Bold'))
    styles.append(('BACKGROUND', (0, len(rows) - 1), (-1, len(rows) - 1), yellow))
    w = doc.width
    t = Table(rows, colWidths=[w * 0.06, w * 0.25, w * 0.31, w * 0.07, w * 0.07, w * 0.10, w * 0.14], repeatRows=1)
    t.setStyle(TableStyle([('GRID', (0, 0), (-1, -1), 0.5, grid), ('FONTSIZE', (0, 0), (-1, -1), 8),
                           ('ALIGN', (3, 0), (-1, -1), 'RIGHT'), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                           ('TOPPADDING', (0, 0), (-1, -1), 3), ('BOTTOMPADDING', (0, 0), (-1, -1), 3)] + styles))
    el += [t, Spacer(1, 10), Paragraph('<b>Payment terms</b>', st(9)),
           Paragraph('<br/>'.join(PAYMENT), st(8.5)), Spacer(1, 6), Paragraph('<b>Terms &amp; conditions</b>', st(9)),
           Paragraph('<br/>'.join(f'{n}. {x}' for n, x in enumerate(TERMS, 1)), st(8.5)), Spacer(1, 14),
           Paragraph('For NEST &amp; GRAIN INTERIORS<br/><br/>Authorised signatory', st(9, False, 2))]
    doc.build(el)
    return grand


if __name__ == '__main__':
    print('grand total', money(build(sys.argv[1])))
