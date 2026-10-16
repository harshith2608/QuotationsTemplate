"""QuoteRoom static ad images (feed 4:5 and stories 9:16), built from static/ads/ screenshots.

    python tools/ad_video/static_ads.py      → ad-videos/static-*.png
"""
import os
import sys

from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
ADS = os.path.join(ROOT, 'static', 'ads')
OUT = os.path.join(ROOT, 'ad-videos')
PDF2 = sys.argv[1] if __name__ == '__main__' and len(sys.argv) > 1 else None   # optional: page 2 of the full quotation

PINE = (31, 77, 63)
PINE_DARK = (14, 34, 28)
TAPE = (242, 183, 5)
PAPER = (245, 246, 242)
MUTED = (190, 210, 201)
INK = (22, 35, 31)
AV = '/System/Library/Fonts/Avenir Next.ttc'


def font(size, weight='heavy'):
    return ImageFont.truetype(AV, size, index={'bold': 0, 'demi': 2, 'medium': 5, 'regular': 7, 'heavy': 8}[weight])


def background(w, h):
    bg = Image.new('RGB', (w, h), PINE_DARK)
    glow = Image.new('L', (w, h), 0)
    ImageDraw.Draw(glow).ellipse([-w * 0.4, -h * 0.25, w * 1.1, h * 0.55], fill=120)
    glow = glow.filter(ImageFilter.GaussianBlur(min(w, h) * 0.22))
    return Image.composite(Image.new('RGB', (w, h), PINE), bg, glow).convert('RGBA')


def rounded_mask(size, r):
    m = Image.new('L', size, 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, size[0] - 1, size[1] - 1], radius=r, fill=255)
    return m


def shadowed(img, r, blur=26, alpha=150, pad=50):
    out = Image.new('RGBA', (img.width + 2 * pad, img.height + 2 * pad), (0, 0, 0, 0))
    sh = Image.new('L', out.size, 0)
    ImageDraw.Draw(sh).rounded_rectangle([pad, pad + 14, pad + img.width, pad + img.height + 14], radius=r, fill=alpha)
    out.paste(Image.new('RGBA', out.size, (0, 0, 0, 255)), (0, 0), sh.filter(ImageFilter.GaussianBlur(blur)))
    out.paste(img, (pad, pad), rounded_mask(img.size, r))
    return out, pad


def phone(screen, width):
    """Phone mockup of `screen` (a 750x1624 screenshot) at the given outer width."""
    bezel = int(width * 0.03)
    sw = width - 2 * bezel
    sh = int(sw * screen.height / screen.width)
    body = Image.new('RGBA', (width, sh + 2 * bezel), (0, 0, 0, 0))
    d = ImageDraw.Draw(body)
    d.rounded_rectangle([0, 0, width - 1, sh + 2 * bezel - 1], radius=int(width * 0.12), fill=(12, 20, 17, 255))
    d.rounded_rectangle([2, 2, width - 3, sh + 2 * bezel - 3], radius=int(width * 0.12), outline=(70, 92, 84, 255), width=3)
    scr = screen.resize((sw, sh), Image.LANCZOS)
    body.paste(scr, (bezel, bezel), rounded_mask((sw, sh), int(width * 0.09)))
    return shadowed(body, int(width * 0.12), blur=30, alpha=170, pad=60)


def card(img, width, r=22, border=None):
    k = width / img.width
    im = img.resize((width, int(img.height * k)), Image.LANCZOS).convert('RGBA')
    if border:
        ImageDraw.Draw(im).rounded_rectangle([1, 1, im.width - 2, im.height - 2], radius=r, outline=border, width=4)
    return shadowed(im, r)


def text_lines(d, x, y, lines, size, weight='heavy', gap=1.1, align='left', width=None):
    f = font(size, weight)
    for parts in lines:
        total = sum(f.getlength(t) for t, _ in parts)
        xx = x + ((width - total) / 2 if align == 'center' else 0)
        for t, col in parts:
            d.text((xx, y), t, font=f, fill=col)
            xx += f.getlength(t)
        y += int(size * gap)
    return y


def pill(base, text, cx, cy, size, fg=INK, bg=TAPE):
    f = font(size, 'bold')
    w, h = int(f.getlength(text) + size * 1.8), int(size * 2.1)
    layer = Image.new('RGBA', (w + 60, h + 60), (0, 0, 0, 0))
    sh = Image.new('L', layer.size, 0)
    ImageDraw.Draw(sh).rounded_rectangle([30, 40, 30 + w, 40 + h], radius=h // 2, fill=120)
    layer.paste(Image.new('RGBA', layer.size, (0, 0, 0, 255)), (0, 0), sh.filter(ImageFilter.GaussianBlur(12)))
    d = ImageDraw.Draw(layer)
    d.rounded_rectangle([30, 30, 30 + w, 30 + h], radius=h // 2, fill=bg)
    d.text((30 + w / 2, 30 + h / 2), text, font=f, fill=fg, anchor='mm')
    base.alpha_composite(layer, (int(cx - layer.width / 2), int(cy - layer.height / 2)))


def check(d, x, y, r):
    d.ellipse([x - r, y - r, x + r, y + r], fill=TAPE)
    d.line([(x - r * 0.45, y + r * 0.02), (x - r * 0.1, y + r * 0.38), (x + r * 0.5, y - r * 0.35)], fill=INK,
           width=max(3, int(r * 0.24)), joint='curve')


def brand(base, x, y, size=52):
    logo = Image.open(f'{ADS}/quoteroom-logo-512.png').convert('RGBA').resize((int(size * 1.35),) * 2, Image.LANCZOS)
    base.alpha_composite(logo, (x, y))
    ImageDraw.Draw(base).text((x + int(size * 1.6), y + int(size * 0.68)), 'QuoteRoom', font=font(size, 'bold'),
                              fill=PAPER, anchor='lm')


def features(base, y, items, size, w):
    """One row when it fits, otherwise one item per line. Returns the y below the block."""
    d = ImageDraw.Draw(base)
    f = font(size, 'demi')
    widths = [f.getlength(t) + size * 1.6 for t in items]
    if sum(widths) + 40 * (len(items) - 1) <= w - 120:
        gapw = (w - 120 - sum(widths)) / (len(items) - 1)
        x = 60
        for t, iw in zip(items, widths):
            check(d, x + size * 0.5, y + size * 0.62, size * 0.5)
            d.text((x + size * 1.25, y), t, font=f, fill=PAPER)
            x += iw + gapw
        return y + int(size * 1.4)
    for t in items:
        check(d, 60 + size * 0.5, y + size * 0.62, size * 0.5)
        d.text((60 + size * 1.25, y), t, font=f, fill=PAPER)
        y += int(size * 1.45)
    return y


def footer(base, w, y, cta_size, note_size):
    pill(base, 'Start your free 7-day trial', w / 2, y, cta_size)
    d = ImageDraw.Draw(base)
    d.text((w / 2, y + cta_size * 1.85), 'No payment to start  ·  quote-room.co.in', font=font(note_size, 'demi'),
           fill=MUTED, anchor='mm')


# ── assets ──
S_ADD = Image.open(f'{ADS}/02-add-item-measure.jpg').convert('RGB')
S_PAY = Image.open(f'{ADS}/04-room-totals-payments.jpg').convert('RGB')
P1 = Image.open(f'{ADS}/06-full-quotation-pdf.png').convert('RGB')
ROOM_TABLE = S_PAY.crop((40, 290, 712, 1020))          # Kitchen: items, sqft, materials, fittings, room total
PAY_CARD = S_PAY.crop((32, 1098, 718, 1372))           # Payment status: total / paid / balance


def quotation_doc():
    """Full quotation: header + room-by-room tables (page 1) + final-total strip (top of page 2)."""
    top = P1.crop((90, 110, P1.width - 90, 1665))
    parts = [top]
    if PDF2 and os.path.exists(PDF2):
        p2 = Image.open(PDF2).convert('RGB')
        parts.append(p2.crop((90, 120, p2.width - 90, 372)))
    h = sum(p.height for p in parts) + 30
    doc = Image.new('RGB', (top.width + 60, h + 60), (255, 255, 255))
    y = 40
    for p in parts:
        doc.paste(p, (30, y)); y += p.height + 10
    return doc


DOC = quotation_doc()


def ad_measure(w, h):
    """'Still making interior quotations manually?' with the measuring screen + totals."""
    tall = h > 1500
    img = background(w, h)
    d = ImageDraw.Draw(img)
    brand(img, 60, 50 if not tall else 120, 50)
    y = text_lines(d, 60, 150 if not tall else 250,
                   [[('Still making interior', PAPER)], [('quotations ', PAPER), ('manually?', TAPE)]], 82 if not tall else 84)
    y = text_lines(d, 60, y + 14, [[('Measure on site. QuoteRoom does the math.', PAPER)],
                                    [('Send a detailed quotation in minutes.', MUTED)]], 38 if not tall else 42, 'demi', 1.3)
    top = y + 26
    vis_h = (1095 if not tall else 1300) - top
    ph, pad = phone(S_ADD, int(vis_h * 0.47))
    img.alpha_composite(ph, (60 - pad + 4, top - pad + 6))
    right_x = 60 + int(vis_h * 0.47) + 36
    gap = 26
    # both cards share one width, chosen so the pair fits the visual area's height and the column's width
    ratio = ROOM_TABLE.height / ROOM_TABLE.width + PAY_CARD.height / PAY_CARD.width
    rw = int(min(w - right_x - 60, (vis_h - 20 - gap) / ratio))
    rx = right_x + (w - right_x - 60 - rw) // 2
    rc, rpad = card(ROOM_TABLE, rw, border=TAPE)
    img.alpha_composite(rc, (rx - rpad, top + 10 - rpad))
    pc, ppad = card(PAY_CARD, rw)
    img.alpha_composite(pc, (rx - ppad, top + 10 + (rc.height - 2 * rpad) + gap - ppad))
    chip_y = top + int(vis_h * 0.80)
    pill(img, "8'6\" × 6' = 51 sqft", 60 + int(vis_h * 0.47) / 2, chip_y, 30 if not tall else 34)
    fy = (1135 if not tall else 1345)
    features(img, fy, ['Room-wise costing', 'Detailed PDF quotes', 'Payment tracking'], 30 if not tall else 34, w)
    footer(img, w, (1250 if not tall else 1590), 40 if not tall else 46, 26 if not tall else 30)   # 9:16: above the Stories CTA bar
    return img.convert('RGB')


def callout(base, text, box_xy, target_xy, size):
    d = ImageDraw.Draw(base)
    f = font(size, 'bold')
    lines = text.split('\n')
    tw = max(f.getlength(l) for l in lines)
    bw, bh = int(tw + size * 1.6), int(size * 1.25 * len(lines) + size * 1.0)
    x, y = box_xy
    d.line([(x + (0 if target_xy[0] < x else bw), y + bh / 2), target_xy], fill=TAPE, width=4)
    d.ellipse([target_xy[0] - 9, target_xy[1] - 9, target_xy[0] + 9, target_xy[1] + 9], fill=TAPE)
    d.rounded_rectangle([x, y, x + bw, y + bh], radius=int(size * 0.9), fill=TAPE)
    yy = y + size * 0.5
    for l in lines:
        d.text((x + bw / 2, yy), l, font=f, fill=INK, anchor='mt')
        yy += size * 1.25


def ad_customer(w, h):
    """'This is what your customer receives.' with the full quotation and callouts."""
    tall = h > 1500
    img = background(w, h)
    d = ImageDraw.Draw(img)
    brand(img, 60, 50 if not tall else 120, 50)
    y = text_lines(d, 60, 150 if not tall else 250,
                   [[('This is what your', PAPER)], [('customer ', TAPE), ('receives.', PAPER)]], 82 if not tall else 84)
    y = text_lines(d, 60, y + 14, [[('Every room, every measurement and the final', PAPER)],
                                    [('total, in one branded quotation.', PAPER)]], 36 if not tall else 40, 'demi', 1.3)
    top = y + 34
    avail = (1160 if not tall else 1480) - top
    dw = min(int(w * (0.57 if tall else 0.66)), int(avail * DOC.width / DOC.height))
    dc, pad = card(DOC, dw, r=14)
    dx, dy = 60, top + (max(0, (avail - int(DOC.height * dw / DOC.width)) // 2) if tall else 0)
    img.alpha_composite(dc, (dx - pad, dy - pad))
    k = dw / DOC.width
    dh = int(DOC.height * k)
    cs = 28 if not tall else 32
    bx = dx + dw + 30
    # pointers end at the document's right edge so they never cover the text
    edge = dx + dw + 4
    callout(img, 'Your business\nname & details', (bx, dy + int(dh * 0.01)), (edge, dy + int(dh * 0.045)), cs)
    callout(img, 'Every size &\nsqft, worked out', (bx, dy + int(dh * 0.40)), (edge, dy + int(dh * 0.43)), cs)
    callout(img, 'Final total,\ncalculated for you', (bx, dy + dh - int(cs * 4.6)), (edge, dy + dh - int(dh * 0.04)), cs)
    footer(img, w, (1250 if not tall else 1590), 40 if not tall else 46, 26 if not tall else 30)   # 9:16: above the Stories CTA bar
    return img.convert('RGB')


if __name__ == '__main__':
    os.makedirs(OUT, exist_ok=True)
    for name, fn in (('measure', ad_measure), ('customer', ad_customer)):
        for fmt, size in (('4x5', (1080, 1350)), ('9x16', (1080, 1920))):
            path = os.path.join(OUT, f'static-{name}-{fmt}.png')
            fn(*size).save(path)
            print('wrote', path)
