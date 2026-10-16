"""Instagram profile posts (4:5, 1080x1350), in the static-ad style.

    python tools/ad_video/profile_posts.py      → ad-videos/post-one-price.png, post-before-after.png,
                                                   carousel-customer-sees-1…6.png
"""
import os

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from carousel_lost_jobs import rich_pill, rich_text, rich_width, wrap
from static_ads import (ADS, DOC, INK, MUTED, OUT, PAPER, PINE, TAPE, background, brand, card, check, font, footer,
                        phone, shadowed, text_lines)

W, H = 1080, 1350
CUSTOMER_PDF = Image.open(f'{ADS}/05-customer-quotation-pdf.png').convert('RGB')
FULL_PDF = Image.open(f'{ADS}/06-full-quotation-pdf.png').convert('RGB')
INVOICE_PDF = Image.open(f'{ADS}/08-gst-invoice-pdf.png').convert('RGB')
S_APPROVAL = Image.open(f'{ADS}/07-approval-accepted.jpg').convert('RGB')
HAND = '/System/Library/Fonts/Supplemental/Bradley Hand Bold.ttf'


def base(counter=None):
    img = background(W, H)
    brand(img, 60, 50, 44)
    if counter:
        ImageDraw.Draw(img).text((W - 60, 80), counter, font=font(30, 'demi'), fill=MUTED, anchor='rm')
    return img


def headline(d, y, parts_lines, size=84):
    return text_lines(d, 60, y, parts_lines, size, gap=1.08)


# ── 1. One price for your whole team ────────────────────────────────────────

def one_price():
    img = base()
    d = ImageDraw.Draw(img)
    y = headline(d, 180, [[('One price.', PAPER)], [('Your ', PAPER), ('whole team.', TAPE)]], 90)
    y = text_lines(d, 60, y + 6, [[('What a quotation system usually costs:', MUTED)]], 34, 'demi')
    rows = [
        ('Custom quotation website', '₹30,000–40,000', 'up front, plus hosting and fixes', 0.92, (120, 140, 132)),
        ('Per-user software', '₹6,000–11,000', 'per person, per year, plus GST', 0.62, (120, 140, 132)),
        ('QuoteRoom', '₹8,999 a year', 'whole team · your own brand · no extra fees', 0.30, TAPE),
    ]
    y += 34
    for name, price, note, frac, colour in rows:
        is_us = name == 'QuoteRoom'
        d.text((60, y), name, font=font(36, 'bold'), fill=PAPER)
        y += 50
        bar_w = int((W - 120) * frac)
        d.rounded_rectangle([60, y, 60 + bar_w, y + 66], radius=16, fill=colour)
        pw = rich_width(price, 36, 'heavy')
        if pw + 48 < bar_w:
            rich_text(d, (84, y + 33), price, 36, 'heavy', INK if is_us else PAPER, 'lm')
        else:                                   # short bar: the price sits just after it
            rich_text(d, (60 + bar_w + 20, y + 33), price, 36, 'heavy', TAPE if is_us else PAPER, 'lm')
        y += 80
        d.text((60, y), note, font=font(29, 'demi'), fill=TAPE if is_us else MUTED)
        y += 64
    check(d, 84, y + 20, 21)
    d.text((122, y), 'Unlimited staff logins and quotations', font=font(31, 'demi'), fill=PAPER)
    footer(img, W, H - 150, 44, 28)
    return img.convert('RGB')


# ── 2. Before / after ───────────────────────────────────────────────────────

def paper_quote(w, h):
    """A handwritten-looking quote on lined notebook paper (illustration)."""
    p = Image.new('RGB', (w, h), (250, 247, 236))
    d = ImageDraw.Draw(p)
    for yy in range(70, h, 46):
        d.line([(0, yy), (w, yy)], fill=(196, 214, 232), width=2)
    d.line([(64, 0), (64, h)], fill=(232, 160, 160), width=3)
    hand = ImageFont.truetype(HAND, 30)
    lines = ['Mr. Sharma - quote', 'Kitchen 10x2.9 ?', 'wardrobe 8 x 7  = 56', '56 x 850 = 47,600',
             'loft  8x2 = 16 x 850', '  = 13,500 ?? ', 'magic corner 18k', 'total approx 1,75,000',
             '(GST extra?)']
    yy = 34
    for i, t in enumerate(lines):
        d.text((84, yy), t, font=hand, fill=(40, 60, 120) if i % 3 else (30, 40, 90))
        yy += 46
    d.line([(84, 34 + 46 * 5 + 22), (300, 34 + 46 * 5 + 22)], fill=(170, 40, 40), width=3)   # a crossed-out mistake
    return p.convert('RGBA').rotate(2.2, expand=True, resample=Image.BICUBIC, fillcolor=(0, 0, 0, 0))


def before_after():
    img = base()
    d = ImageDraw.Draw(img)
    y = headline(d, 180, [[('Same job. Same price.', PAPER)], [('Very different ', PAPER), ('impression.', TAPE)]], 66)
    top = y + 40
    col_w = (W - 120 - 40) // 2
    # before
    pq = paper_quote(col_w, 560)
    pc, pad = shadowed(pq, 6)
    img.alpha_composite(pc, (60 - pad, top + 60 - pad))
    # after: the branded customer quotation
    doc = CUSTOMER_PDF.crop((90, 110, CUSTOMER_PDF.width - 90, 1480))
    dc, dpad = card(doc, col_w, r=10)
    img.alpha_composite(dc, (60 + col_w + 40 - dpad, top + 60 - dpad))
    for x, label, colour in ((60, 'BEFORE', (200, 210, 205)), (60 + col_w + 40, 'AFTER', TAPE)):
        rich_pill(img, label, x + col_w / 2, top + 10, 26, fg=INK, bg=colour)
    cap_y = top + 60 + 610
    for x, text in ((60, 'Rough sums, crossed-out mistakes, "GST extra?"'),
                    (60 + col_w + 40, 'Your logo, every material, the exact total')):
        yy = cap_y
        for line in wrap(text, 30, 'demi', col_w):
            d.text((x, yy), line, font=font(30, 'demi'), fill=MUTED if x == 60 else PAPER)
            yy += 40
    footer(img, W, H - 150, 44, 28)
    return img.convert('RGB')


# ── 3. Carousel: what your customer receives ────────────────────────────────

def doc_slide(n, total, step, title, sub, source, crop, kind='card'):
    img = base(f'{n}/{total}')
    d = ImageDraw.Draw(img)
    rich_pill(img, step, 60 + (rich_width(step, 26, 'bold') + 26 * 1.8) / 2, 205, 26)
    y = 265
    for line in wrap(title, 62, 'heavy', W - 120):
        d.text((60, y), line, font=font(62), fill=PAPER)
        y += 70
    for line in wrap(sub, 34, 'demi', W - 120):
        d.text((60, y + 6), line, font=font(34, 'demi'), fill=MUTED)
        y += 44
    top, bottom = y + 40, H - 110
    src = source.crop(crop) if crop else source
    if kind == 'phone':
        width = int((bottom - top) * src.width / src.height / 0.93)
        ph, pad = phone(src, width)
        img.alpha_composite(ph, ((W - (ph.width - 2 * pad)) // 2 - pad, top - pad))
    else:
        h = bottom - top
        width = min(W - 160, int(h * src.width / src.height))
        c, pad = card(src, width, r=12)
        img.alpha_composite(c, ((W - width) // 2 - pad, top - pad))
    if n < total:
        rich_text(d, (W - 60, H - 34), 'Swipe  →', 32, 'bold', TAPE, 'rs')
    return img.convert('RGB')


def customer_sees():
    total = 6
    slides = []
    img = base(f'1/{total}')
    d = ImageDraw.Draw(img)
    d.text((60, 190), 'For interior designers & modular furniture firms', font=font(30, 'demi'), fill=TAPE)
    y = headline(d, 250, [[('What your', PAPER)], [('customer', TAPE)], [('receives.', PAPER)]], 104)
    text_lines(d, 60, y + 10, [[('From the first quote to the', MUTED)], [('final invoice, in your brand.', MUTED)]], 44, 'demi', 1.25)
    c, pad = card(CUSTOMER_PDF.crop((90, 110, CUSTOMER_PDF.width - 90, 1400)), 420, r=12)
    img.alpha_composite(c.rotate(-4, expand=True, resample=Image.BICUBIC), (W - 60 - 470, 640))
    label = 'Swipe to see all 4  →'
    rich_pill(img, label, 60 + (rich_width(label, 32, 'bold') + 32 * 1.8) / 2, H - 150, 32)
    slides.append(img.convert('RGB'))
    slides.append(doc_slide(2, total, 'STEP 1 · FIRST QUOTE', 'The Initial Quotation.',
                            'Amounts by material, no measurements. A clean first quote that is hard to shop around.',
                            CUSTOMER_PDF, (90, 110, CUSTOMER_PDF.width - 90, 1700)))
    slides.append(doc_slide(3, total, 'STEP 2 · THE DETAIL', 'The Full Quotation.',
                            'Every room, every item, every size, when the customer is ready to decide.',
                            DOC, (0, 0, DOC.width, int(DOC.width * 1.05))))
    slides.append(doc_slide(4, total, 'STEP 3 · YES!', 'They accept online.',
                            'A link in your colours: they view it, download the PDF and tap Accept.',
                            S_APPROVAL, (0, 0, 750, 1080), kind='phone'))
    slides.append(doc_slide(5, total, 'STEP 4 · GET PAID', 'A GST invoice in one step.',
                            'CGST + SGST or IGST worked out, numbered by financial year. Or a plain invoice without GST.',
                            INVOICE_PDF, (90, 90, INVOICE_PDF.width - 90, 1550)))
    img = base(f'{total}/{total}')
    d = ImageDraw.Draw(img)
    y = headline(d, 200, [[('Look like the', PAPER)], [('biggest firm', TAPE)], [('in your city.', PAPER)]], 96)
    items = ['Your logo and colours on everything', 'Your own web address', 'WhatsApp and email in one tap',
             'One price for your whole team']
    y += 40
    for t in items:
        check(d, 84, y + 26, 24)
        d.text((130, y + 4), t, font=font(40, 'demi'), fill=PAPER)
        y += 80
    footer(img, W, H - 190, 44, 28)
    slides.append(img.convert('RGB'))
    return slides


# ── 4. Checklist: does your quotation have all 6? ──────────────────────────

CHECKLIST = ['Your logo and company details', 'Room-by-room items and sizes', 'Your rates for every material',
             'UPI and bank details to pay you', 'A GST invoice once confirmed', 'A link to accept it online']


def checklist():
    img = base()
    d = ImageDraw.Draw(img)
    y = headline(d, 170, [[('Does your quotation', PAPER)], [('have all ', PAPER), ('6?', TAPE)]], 80)
    d.text((60, y + 4), 'Check yours against this list.', font=font(34, 'demi'), fill=MUTED)
    y += 76
    for i, item in enumerate(CHECKLIST, 1):
        d.rounded_rectangle([60, y, W - 60, y + 92], radius=20, fill=(27, 62, 51), outline=(70, 104, 92), width=2)
        d.rounded_rectangle([88, y + 22, 136, y + 70], radius=10, outline=TAPE, width=4)      # an empty box to tick
        d.text((166, y + 46), item, font=font(36, 'demi'), fill=PAPER, anchor='lm')
        d.text((W - 92, y + 46), str(i), font=font(32, 'bold'), fill=(120, 150, 138), anchor='rm')
        y += 106
    d.text((W / 2, y + 30), 'QuoteRoom gives you all 6, on every quote.', font=font(38, 'bold'), fill=TAPE, anchor='mm')
    footer(img, W, H - 115, 40, 26)
    return img.convert('RGB')


if __name__ == '__main__':
    os.makedirs(OUT, exist_ok=True)
    checklist().save(os.path.join(OUT, 'post-checklist.png'))
    one_price().save(os.path.join(OUT, 'post-one-price.png'))
    before_after().save(os.path.join(OUT, 'post-before-after.png'))
    for i, s in enumerate(customer_sees(), 1):
        s.save(os.path.join(OUT, f'carousel-customer-sees-{i}.png'))
    print('done')
