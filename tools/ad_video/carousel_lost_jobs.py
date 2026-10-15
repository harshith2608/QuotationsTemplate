"""Carousel ad '5 reasons interior jobs are lost' (7 slides, 1080x1350), in the static-ad style.

    python tools/ad_video/carousel_lost_jobs.py      → ad-videos/carousel-lost-jobs-1.png … -7.png
"""
import os

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from static_ads import (ADS, DOC, INK, MUTED, OUT, PAPER, PINE, ROOM_TABLE, S_ADD, TAPE, background, brand, card,
                        check, font, footer, phone, pill, text_lines)  # noqa: F401

W, H = 1080, 1350
TOTAL = 7
S_APPROVAL = Image.open(f'{ADS}/07-approval-accepted.jpg').convert('RGB')
CUSTOMER_PDF = Image.open(f'{ADS}/05-customer-quotation-pdf.png').convert('RGB')


# Avenir has no ₹ or →: draw those from fonts that do
FALLBACK = {'₹': '/System/Library/Fonts/SFNS.ttf', '→': '/System/Library/Fonts/Supplemental/Arial Unicode.ttf'}
SPECIAL = set(FALLBACK)


def _runs(text, size, weight):
    out, cur, special = [], '', None
    for ch in text:
        sp = ch if ch in SPECIAL else False
        if special is not None and sp != special:
            out.append((cur, special)); cur = ''
        cur += ch; special = sp
    if cur:
        out.append((cur, special))
    return [(t, ImageFont.truetype(FALLBACK[sp], size) if sp else font(size, weight)) for t, sp in out]


def rich_width(text, size, weight='heavy'):
    return sum(f.getlength(t) for t, f in _runs(text, size, weight))


def rich_text(d, xy, text, size, weight, fill, anchor='lt'):
    """Draw text in Avenir, with ₹ and → from a font that has them. anchor: l/m/r + t/m/s."""
    x, y = xy
    w = rich_width(text, size, weight)
    x -= {'l': 0, 'm': w / 2, 'r': w}[anchor[0]]
    for t, f in _runs(text, size, weight):
        d.text((x, y), t, font=f, fill=fill, anchor='l' + anchor[1])
        x += f.getlength(t)


def rich_pill(base, text, cx, cy, size, fg=INK, bg=TAPE):
    w, h = int(rich_width(text, size, 'bold') + size * 1.8), int(size * 2.1)
    layer = Image.new('RGBA', (w + 60, h + 60), (0, 0, 0, 0))
    sh = Image.new('L', layer.size, 0)
    ImageDraw.Draw(sh).rounded_rectangle([30, 40, 30 + w, 40 + h], radius=h // 2, fill=120)
    layer.paste(Image.new('RGBA', layer.size, (0, 0, 0, 255)), (0, 0), sh.filter(ImageFilter.GaussianBlur(12)))
    d = ImageDraw.Draw(layer)
    d.rounded_rectangle([30, 30, 30 + w, 30 + h], radius=h // 2, fill=bg)
    rich_text(d, (30 + w / 2, 30 + h / 2), text, size, 'bold', fg, 'mm')
    base.alpha_composite(layer, (int(cx - layer.width / 2), int(cy - layer.height / 2)))


def wrap(text, size, weight, width):
    """Split text into lines that fit `width` pixels."""
    f = font(size, weight)
    lines, line = [], ''
    for word in text.split():
        trial = f'{line} {word}'.strip()
        if f.getlength(trial) <= width:
            line = trial
        else:
            lines.append(line)
            line = word
    lines.append(line)
    return lines


def frame(n):
    """Background, logo and the slide counter."""
    img = background(W, H)
    brand(img, 60, 50, 44)
    ImageDraw.Draw(img).text((W - 60, 80), f'{n}/{TOTAL}', font=font(30, 'demi'), fill=MUTED, anchor='rm')
    return img


def swipe(img):
    d = ImageDraw.Draw(img)
    rich_text(d, (W - 60, H - 34), 'Swipe  →', 32, 'bold', TAPE, 'rs')


def reason_slide(n, number, problem, cost, fix, visual):
    """One reason: the problem, what it costs, the fix, and a screen from the app."""
    img = frame(n)
    d = ImageDraw.Draw(img)
    pill(img, f'REASON {number}', 60 + 115, 205, 26)
    y = 265
    for line in wrap(problem, 62, 'heavy', W - 120):
        d.text((60, y), line, font=font(62), fill=PAPER)
        y += 70
    y += 6
    for line in wrap(cost, 34, 'demi', W - 120):
        d.text((60, y), line, font=font(34, 'demi'), fill=MUTED)
        y += 44
    # the fix, in a light band at the bottom
    band_top = H - 262
    band = Image.new('RGBA', (W - 120, 180), (0, 0, 0, 0))
    ImageDraw.Draw(band).rounded_rectangle([0, 0, W - 121, 179], radius=26, fill=(245, 246, 242, 245))
    img.alpha_composite(band, (60, band_top))
    check(d, 60 + 50, band_top + 52, 22)
    d.text((60 + 88, band_top + 34), 'The fix', font=font(28, 'bold'), fill=PINE)
    fy = band_top + 76
    for line in wrap(fix, 34, 'demi', W - 120 - 120):
        d.text((60 + 88, fy), line, font=font(34, 'demi'), fill=INK)
        fy += 44
    # the visual fills the space between the text and the fix band
    top, bottom = y + 24, band_top - 24
    visual(img, top, bottom)
    swipe(img)
    return img.convert('RGB')


def put_phone(screen, crop_bottom=None):
    def draw(img, top, bottom):
        scr = screen.crop((0, 0, screen.width, crop_bottom)) if crop_bottom else screen
        h = bottom - top
        width = int(h * scr.width / scr.height / 0.93)
        ph, pad = phone(scr, width)
        img.alpha_composite(ph, ((W - (ph.width - 2 * pad)) // 2 - pad, top - pad))
    return draw


def put_card(source, crop=None, border=TAPE, r=18):
    def draw(img, top, bottom):
        src = source.crop(crop) if crop else source
        h = bottom - top
        width = min(W - 160, int(h * src.width / src.height))
        c, pad = card(src, width, r=r, border=border)
        img.alpha_composite(c, ((W - width) // 2 - pad, top + (h - int(src.height * width / src.width)) // 2 - pad))
    return draw


def cover():
    img = frame(1)
    d = ImageDraw.Draw(img)
    d.text((60, 190), 'For interior designers & modular furniture firms', font=font(30, 'demi'), fill=TAPE)
    y = text_lines(d, 60, 250, [[('5 reasons', TAPE)], [('interior jobs', PAPER)], [('are lost', PAPER)]], 104, gap=1.08)
    text_lines(d, 60, y + 10, [[('…and how to stop', MUTED)], [('losing yours.', MUTED)]], 46, 'demi', 1.25)
    ph, pad = phone(S_ADD.crop((0, 0, 750, 1450)), 380)
    img.alpha_composite(ph, (W - 60 - 380 - pad, 560 - pad))
    label = 'Swipe to see all 5  →'
    rich_pill(img, label, 60 + (rich_width(label, 32, 'bold') + 32 * 1.8) / 2, H - 150, 32)   # left edge on the text column
    return img.convert('RGB')


def closing():
    img = frame(TOTAL)
    d = ImageDraw.Draw(img)
    y = text_lines(d, 60, 200, [[('QuoteRoom ', TAPE), ('fixes', PAPER)], [('all 5.', PAPER)]], 96, gap=1.08)
    items = ['Quote on site, before you leave', 'Sqft, price and total calculated for you', 'Branded PDF with your logo',
             'Customers accept online + WhatsApp reminders', 'Initial quote by material, full detail later']
    y += 30
    for i, t in enumerate(items, 1):
        check(d, 60 + 24, y + 26, 24)
        d.text((60 + 70, y + 4), t, font=font(38, 'demi'), fill=PAPER)
        y += 74
    y += 30
    d.rounded_rectangle([60, y, W - 60, y + 150], radius=26, outline=TAPE, width=3)
    d.text((W / 2, y + 52), 'One price for your whole team', font=font(40, 'bold'), fill=PAPER, anchor='mm')
    rich_text(d, (W / 2, y + 108), '₹8,999 a year  ·  about ₹750 a month  ·  no per-user fees', 30, 'demi', MUTED, 'mm')
    footer(img, W, H - 170, 44, 28)
    return img.convert('RGB')


SLIDES = [
    cover,
    lambda: reason_slide(2, 1, 'The quote arrived 2 days late.', 'By then, the customer already has three other quotes.',
                         'Measure on site and send the quotation before you leave.',
                         put_phone(S_ADD, crop_bottom=1300)),
    lambda: reason_slide(3, 2, 'A mistake in the sqft or the total.', 'One wrong number and they stop trusting the rest.',
                         'Type the size in feet and inches. QuoteRoom calculates the sqft, price and total for you.', put_card(ROOM_TABLE)),
    lambda: reason_slide(4, 3, 'The quote looked unprofessional.', 'A plain text message or a messy sheet looks small-time.',
                         'A branded PDF with your logo, every room and every size.',
                         put_card(DOC, crop=(0, 0, DOC.width, int(DOC.width * 0.82)), border=None, r=12)),
    lambda: reason_slide(5, 4, 'Nobody followed up.', '"I\'ll let you know" quietly becomes someone else\'s job.',
                         'Send a link they accept online. Remind on WhatsApp in one tap.',
                         put_phone(S_APPROVAL, crop_bottom=1100)),
    lambda: reason_slide(6, 5, 'The price confused the customer.', 'Too much detail too early, or too little to trust it.',
                         'Initial quote by material first. Full room-by-room detail when they\'re ready.',
                         put_card(CUSTOMER_PDF, crop=(90, 110, CUSTOMER_PDF.width - 90, 1500), border=None, r=12)),
    closing,
]


if __name__ == '__main__':
    os.makedirs(OUT, exist_ok=True)
    for i, make in enumerate(SLIDES, 1):
        path = os.path.join(OUT, f'carousel-lost-jobs-{i}.png')
        make().save(path)
        print('wrote', path)
