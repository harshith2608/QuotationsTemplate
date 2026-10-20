"""Feed carousel 'Excel vs QuoteRoom' (10 slides, 1080x1350), built on the 10-slide carousel framework:
1 hook · 2–3 an example (the same quote both ways) · 4–5 diagrams (where the time goes, what happens after you send it)
· 6–9 practical comparisons and a summary table · 10 a simple call to action.

    python tools/ad_video/carousel_excel_vs.py      → ad-videos/carousel-excel-vs-1.png … -10.png
"""
import os

from PIL import Image, ImageDraw

from carousel_lost_jobs import rich_pill, rich_text, wrap
from reel_excel_vs import GRID, RED, XL_GREEN, draw_sheet, timer
from static_ads import ADS, INK, MUTED, OUT, PAPER, PINE, TAPE, background, brand, card, check, font, phone, pill

W, H = 1080, 1350
TOTAL = 10
GREEN = (46, 160, 90)
S_ADD = Image.open(f'{ADS}/02-add-item-measure.jpg').convert('RGB')
S_PAY = Image.open(f'{ADS}/04-room-totals-payments.jpg').convert('RGB')
S_ACCEPT = Image.open(f'{ADS}/07-approval-accepted.jpg').convert('RGB')
CUSTOMER_PDF = Image.open(f'{ADS}/05-customer-quotation-pdf.png').convert('RGB')


# ── building blocks ──

def frame(n):
    img = background(W, H).convert('RGBA')
    brand(img, 60, 50, 40)
    label = f'{n}/{TOTAL}'
    w = int(font(28, 'bold').getlength(label) + 44)
    chip = Image.new('RGBA', (w, 54), (0, 0, 0, 0))
    ImageDraw.Draw(chip).rounded_rectangle([0, 0, w - 1, 53], radius=27, fill=(255, 255, 255, 40))
    img.alpha_composite(chip, (W - 60 - w, 51))                      # blended, so the text on top shows
    ImageDraw.Draw(img).text((W - 60 - w / 2, 78), label, font=font(28, 'bold'), fill=PAPER, anchor='mm')
    return img


def swipe(img):
    rich_text(ImageDraw.Draw(img), (W - 60, H - 40), 'Swipe  →', 32, 'bold', TAPE, 'rs')


def title(img, y, white, yellow=None, size=74, second_line_yellow=True):
    """A two-tone headline (white words, then yellow words), wrapped. Returns the y below it."""
    d = ImageDraw.Draw(img)
    words = [(w, PAPER) for w in white.split()] + [(w, TAPE) for w in (yellow or '').split()]
    f = font(size)
    x, line_h = 60, int(size * 1.12)
    for word, colour in words:
        ww = f.getlength(word + ' ')
        if x + f.getlength(word) > W - 60:
            x, y = 60, y + line_h
        d.text((x, y), word, font=f, fill=colour)
        x += ww
    return y + line_h


def para(img, y, text, size=34, colour=MUTED, width=W - 120, x=60, weight='demi', gap=1.32):
    d = ImageDraw.Draw(img)
    for line in wrap(text, size, weight, width):
        d.text((x, y), line, font=font(size, weight), fill=colour)
        y += int(size * gap)
    return y


def cross(d, x, y, r, colour=RED):
    d.ellipse([x - r, y - r, x + r, y + r], fill=colour)
    k = r * 0.42
    d.line([(x - k, y - k), (x + k, y + k)], fill='white', width=max(3, int(r * 0.24)))
    d.line([(x - k, y + k), (x + k, y - k)], fill='white', width=max(3, int(r * 0.24)))


def sheet_image(t):
    """The spreadsheet from the Excel reel, at moment t, cut out on its own."""
    tmp = Image.new('RGBA', (1080, 1200), (0, 0, 0, 0))
    draw_sheet(tmp, t)
    return tmp.crop((34, 548, 1046, 1062))


def tag(img, x, y, text, bg, fg='white', size=26):
    rich_pill(img, text, x, y, size, fg=fg, bg=bg)


def versus_card(img, top, height, good, heading, lines, visual=None):
    """One side of a head-to-head: red 'In Excel' or yellow 'In QuoteRoom', with points and an optional visual."""
    d = ImageDraw.Draw(img)
    fill = (64, 26, 26, 235) if not good else (245, 246, 242, 245)
    layer = Image.new('RGBA', (W - 120, height), (0, 0, 0, 0))
    ImageDraw.Draw(layer).rounded_rectangle([0, 0, W - 121, height - 1], radius=28, fill=fill)
    img.alpha_composite(layer, (60, top))
    text_colour = PAPER if not good else INK
    head_colour = (255, 140, 140) if not good else PINE
    (check if good else cross)(d, 60 + 52, top + 56, 24)
    d.text((60 + 92, top + 56), heading, font=font(34, 'heavy'), fill=head_colour, anchor='lm')
    text_w = (W - 120 - 120) if visual is None else (W - 120 - 120 - 300)
    y = top + 104
    for line in lines:
        rich_text(d, (60 + 52, y + 4), '•', 30, 'heavy', head_colour, 'lt')
        for l in wrap(line, 31, 'demi', text_w - 30):
            d.text((60 + 92, y), l, font=font(31, 'demi'), fill=text_colour)
            y += 41
        y += 12
    if visual is not None:
        visual(img, W - 60 - 40 - 280, top + 30, 280, height - 60)


def phone_at(screen, crop=None):
    def draw(img, x, y, w, h):
        scr = screen.crop(crop) if crop else screen
        width = min(w, int(h * scr.width / scr.height / 0.93))
        ph, pad = phone(scr, width)
        img.alpha_composite(ph, (x + (w - width) // 2 - pad, y + (h - ph.height + 2 * pad) // 2 - pad))
    return draw


def card_at(src, crop=None, border=TAPE):
    def draw(img, x, y, w, h):
        s = src.crop(crop) if crop else src
        width = min(w, int(h * s.width / s.height))
        c, pad = card(s, width, r=16, border=border)
        img.alpha_composite(c, (x + (w - width) // 2 - pad, y + (h - int(s.height * width / s.width)) // 2 - pad))
    return draw


# ── slides ──

def stat(img, x, y, w, h, label, value, sub, bg, fg, sub_fg):
    layer = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(layer).rounded_rectangle([0, 0, w - 1, h - 1], radius=28, fill=bg)
    img.alpha_composite(layer, (x, y))
    d = ImageDraw.Draw(img)
    d.text((x + 36, y + 30), label, font=font(30, 'bold'), fill=sub_fg)
    d.text((x + 36, y + 70), value, font=font(92), fill=fg)
    d.text((x + 36, y + h - 58), sub, font=font(28, 'demi'), fill=sub_fg)


def s1_hook():
    img = frame(1)
    y = title(img, 170, 'Still making quotations in', 'Excel?', size=84)
    y = para(img, y + 6, 'Same kitchen. Same customer. Two very different evenings.', size=34)
    sheet = sheet_image(8.5)                                           # the #VALUE! moment
    k = (W - 100) / sheet.width
    sheet = sheet.resize((int(sheet.width * k), int(sheet.height * k)), Image.LANCZOS)
    top = y + 30
    img.alpha_composite(sheet, (50, top))
    sy = top + sheet.height + 32
    half = (W - 120 - 30) // 2
    stat(img, 60, sy, half, 270, 'EXCEL', '40 min', 'and a #VALUE! error', (120, 30, 30, 255), (255, 170, 170),
         (255, 210, 210))
    stat(img, 60 + half + 30, sy, half, 270, 'QUOTEROOM', '3 min', 'sent on WhatsApp', TAPE + (255,), INK, (60, 50, 10))
    swipe(img)
    return img


def s2_excel():
    img = frame(2)
    tag(img, 175, 180, 'THE EXCEL WAY', XL_GREEN, size=28)
    y = title(img, 230, 'Type. Fix. Format.', 'Repeat.', size=72)
    y = para(img, y + 6, 'Every size typed by hand. Every formula checked. Then make it look decent enough to send.',
             size=34)
    sheet = sheet_image(14)                                            # totals done (no unit-specific callout)
    k = (W - 100) / sheet.width
    sheet = sheet.resize((int(sheet.width * k), int(sheet.height * k)), Image.LANCZOS)
    img.alpha_composite(sheet, (50, y + 40))
    rich_pill(img, 'Every formula checked by hand', W / 2, y + 40 + sheet.height - 30, 28, fg='white', bg=RED)
    d = ImageDraw.Draw(img)
    y2 = y + 40 + sheet.height + 50
    timer(img, W - 60, y2 + 10, 40, RED)
    d.text((60, y2 + 10), 'Quotation_FINAL_v3 (2).xlsx', font=font(30, 'demi'), fill=MUTED, anchor='lm')
    para(img, y2 + 70, 'And it still isn\'t on WhatsApp yet.', size=34, colour=PAPER, weight='bold')
    swipe(img)
    return img


def s3_quoteroom():
    img = frame(3)
    tag(img, 205, 180, 'THE QUOTEROOM WAY', TAPE, fg=INK, size=28)
    y = title(img, 230, 'Measure. Tap.', 'Send.', size=72)
    y = para(img, y + 6, 'Type each size in your own unit: feet & inches, mm or cm. QuoteRoom works out the area, applies '
                         'your rates and makes the PDF in your brand.', size=34)
    top = y + 40
    ph, pad = phone(S_ADD, 380)
    img.alpha_composite(ph, (60 - pad + 10, top - pad))
    d = ImageDraw.Draw(img)
    steps = ['Rooms & items added', 'Area & totals worked out', 'Branded PDF ready', 'Sent on WhatsApp']
    sy = top + 40
    for s in steps:
        check(d, 520, sy + 22, 22)
        d.text((560, sy + 22), s, font=font(34, 'demi'), fill=PAPER, anchor='lm')
        sy += 84
    timer(img, W - 60, sy + 40, 3, TAPE)
    rich_pill(img, 'Done in 3 min  ✓', 700, sy + 140, 34, fg='white', bg=GREEN)
    swipe(img)
    return img


def s4_time_chart():
    img = frame(4)
    y = title(img, 180, 'Where the', '40 minutes go', size=72)
    y = para(img, y + 6, 'One typical quotation, step by step.', size=34)
    d = ImageDraw.Draw(img)
    steps = [('Typing every size', 12, (231, 111, 81)), ('Formulas & fixing errors', 10, (214, 48, 49)),
             ('Formatting to look decent', 10, (176, 58, 46)), ('Saving the PDF & sending', 8, (130, 50, 40))]
    left, right = 60, W - 60
    scale = (right - left) / 40
    top = y + 60
    d.text((left, top), 'Excel', font=font(38, 'heavy'), fill=PAPER)
    d.text((right, top + 4), '40 min', font=font(38, 'heavy'), fill=(255, 140, 140), anchor='ra')
    bar_top = top + 64
    x = left
    for name, mins, colour in steps:
        w = mins * scale
        d.rounded_rectangle([x + 2, bar_top, x + w - 2, bar_top + 90], radius=14, fill=colour)
        d.text((x + w / 2, bar_top + 45), f'{mins}', font=font(40, 'heavy'), fill='white', anchor='mm')
        x += w
    ly = bar_top + 130
    for name, mins, colour in steps:
        d.rounded_rectangle([left, ly + 6, left + 30, ly + 36], radius=8, fill=colour)
        d.text((left + 48, ly + 21), f'{name}', font=font(32, 'demi'), fill=PAPER, anchor='lm')
        d.text((right, ly + 21), f'{mins} min', font=font(32, 'demi'), fill=MUTED, anchor='rm')
        ly += 56
    qtop = ly + 50
    d.text((left, qtop), 'QuoteRoom', font=font(38, 'heavy'), fill=PAPER)
    d.text((right, qtop + 4), '3 min', font=font(38, 'heavy'), fill=TAPE, anchor='ra')
    d.rounded_rectangle([left + 2, qtop + 64, left + 3 * scale, qtop + 154], radius=14, fill=TAPE)
    d.text((left + 3 * scale + 24, qtop + 109), 'sizes in, everything else is done for you', font=font(30, 'demi'),
           fill=MUTED, anchor='lm')
    rich_pill(img, '37 minutes saved on every quote', W / 2, qtop + 250, 38, fg=INK, bg=TAPE)
    swipe(img)
    return img


def s5_after_send():
    img = frame(5)
    y = title(img, 180, 'After you send it:', 'what happens next?', size=66)
    d = ImageDraw.Draw(img)

    def flow(top, label, label_bg, label_fg, boxes, box_fill, text_fill, end_text, end_bg, end_fg):
        rich_pill(img, label, 60 + 100, top, 28, fg=label_fg, bg=label_bg)
        by = top + 50
        bw, gap, bh = 290, 45, 200
        for i, text in enumerate(boxes):
            bx = 60 + i * (bw + gap)
            d.rounded_rectangle([bx, by, bx + bw, by + bh], radius=24, fill=box_fill)
            lines = wrap(text, 34, 'bold', bw - 40)
            yy = by + bh / 2 - 23 * (len(lines) - 1)
            for line in lines:
                d.text((bx + bw / 2, yy), line, font=font(34, 'bold'), fill=text_fill, anchor='mm')
                yy += 46
            if i < len(boxes) - 1:
                rich_text(d, (bx + bw + gap / 2, by + bh / 2), '→', 40, 'bold', MUTED, 'mm')
        rich_pill(img, end_text, W / 2, by + bh + 80, 36, fg=end_fg, bg=end_bg)

    flow(y + 90, 'EXCEL', XL_GREEN, 'white',
         ['PDF on WhatsApp', '"Did you see it?"', 'Calls & follow-ups'], (70, 32, 32), PAPER,
         'Days later: "I\'ll let you know"', RED, 'white')
    flow(y + 550, 'QUOTEROOM', TAPE, INK,
         ['Link on WhatsApp', 'Customer taps Accept', 'You get notified'], (245, 246, 242), INK,
         'Same day: job Confirmed  ✓', GREEN, 'white')
    swipe(img)
    return img


def versus_slide(n, topic_white, topic_yellow, sub, bad, good, good_visual=None, bad_visual=None):
    img = frame(n)
    y = title(img, 180, topic_white, topic_yellow, size=68)
    y = para(img, y + 4, sub, size=32)
    top = y + 40
    room = H - 120 - top
    h_bad = int(room * 0.40)
    versus_card(img, top, h_bad, False, 'In Excel', bad, bad_visual)
    versus_card(img, top + h_bad + 30, room - h_bad - 30, True, 'In QuoteRoom', good, good_visual)
    swipe(img)
    return img


def s6_sqft():
    return versus_slide(6, 'Sizes and', 'area maths', 'Where most wrong prices start.',
                        ['Sizes and formulas typed by hand: one slip, wrong area, wrong price',
                         'One broken formula and the total is off'],
                        ['Type sizes in your unit (ft & in, mm, cm or inches): the area is worked out for you',
                         'Your rates applied automatically, every time',
                         'Room totals and the grand total update as you type'],
                        good_visual=phone_at(S_ADD))


def s7_versions():
    return versus_slide(7, 'When the customer', 'changes their mind', '"Drop the loft." … "Actually, keep it."',
                        ['Quotation_FINAL_v3 (2).xlsx: which one did they see?',
                         'Old prices lost when you overwrite'],
                        ['Every version kept automatically: Rev 1, Rev 2…',
                         'See exactly what changed between versions',
                         'Restore an older version in one tap'])


def s8_paid():
    return versus_slide(8, 'Getting the yes', 'and getting paid', 'The part Excel doesn\'t do at all.',
                        ['Chase the answer on calls',
                         'Payments written in a notebook, invoices made separately'],
                        ['Customer accepts online: no app, no login',
                         'Payment reminders on WhatsApp with your UPI',
                         'GST invoice in one tap, balances always up to date'],
                        good_visual=phone_at(S_ACCEPT))


def s9_table():
    img = frame(9)
    y = title(img, 180, 'Side by side', None, size=72)
    d = ImageDraw.Draw(img)
    rows = ['Sizes in your own unit', 'Area & totals worked out', 'PDF in your brand',
            'Customer accepts online', 'Every version kept', 'Payments & GST invoice', 'On every phone in your team',
            'Profit on every job']
    excel_has = {'PDF in your brand': 'manual'}
    top = y + 40
    left, c1, c2 = 60, W - 60 - 390, W - 60 - 190
    d.text((c1 + 75, top + 30), 'Excel', font=font(34, 'heavy'), fill=PAPER, anchor='mm')
    d.rounded_rectangle([c2 - 20, top, c2 + 190, top + 60], radius=30, fill=TAPE)
    d.text((c2 + 85, top + 30), 'QuoteRoom', font=font(30, 'heavy'), fill=INK, anchor='mm')
    ry = top + 90
    for i, row in enumerate(rows):
        if i % 2 == 0:
            band = Image.new('RGBA', (W - 120, 96), (255, 255, 255, 18))
            img.alpha_composite(band, (left, ry))
        d.text((left + 24, ry + 48), row, font=font(32, 'demi'), fill=PAPER, anchor='lm')
        if row in excel_has:
            d.text((c1 + 75, ry + 48), 'by hand', font=font(26, 'demi'), fill=MUTED, anchor='mm')
        else:
            cross(d, c1 + 75, ry + 48, 22)
        check(d, c2 + 85, ry + 48, 24)
        ry += 96
    swipe(img)
    return img


def s10_cta():
    img = frame(10)
    d = ImageDraw.Draw(img)
    logo = Image.open(f'{ADS}/quoteroom-logo-512.png').convert('RGBA').resize((200, 200), Image.LANCZOS)
    img.alpha_composite(logo, ((W - 200) // 2, 250))
    y = 520
    for line, colour in (('Stop fixing formulas.', PAPER), ('Start sending quotes.', TAPE)):
        d.text((W / 2, y), line, font=font(76), fill=colour, anchor='mm')
        y += 96
    for line in wrap('Make your next quotation in QuoteRoom, on your phone, in your own brand.', 36, 'demi', W - 200):
        d.text((W / 2, y + 30), line, font=font(36, 'demi'), fill=MUTED, anchor='mm')
        y += 48
    pill(img, 'Start your free 7-day trial', W / 2, y + 150, 44)
    d.text((W / 2, y + 250), 'Link in bio  ·  quote-room.co.in', font=font(32, 'demi'), fill=PAPER, anchor='mm')
    d.text((W / 2, y + 300), 'No payment to start. One price for your whole team.', font=font(28, 'demi'), fill=MUTED,
           anchor='mm')
    d.text((W / 2, H - 70), 'Save this post for your next quote  🔖'.replace('  🔖', ''), font=font(28, 'bold'),
           fill=TAPE, anchor='mm')
    return img


SLIDES = [s1_hook, s2_excel, s3_quoteroom, s4_time_chart, s5_after_send, s6_sqft, s7_versions, s8_paid, s9_table,
          s10_cta]

if __name__ == '__main__':
    os.makedirs(OUT, exist_ok=True)
    for i, make in enumerate(SLIDES, 1):
        path = os.path.join(OUT, f'carousel-excel-vs-{i}.png')
        make().convert('RGB').save(path, optimize=True)
        print('wrote', path)
