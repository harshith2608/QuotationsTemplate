"""Reel 'Do you know your profit?': quote total → enter costs once → profit on every quote → the year (9:16).

    python tools/ad_video/reel_profit.py          → ad-videos/reel-profit-9x16.mp4
    python tools/ad_video/reel_profit.py stills   → ad-videos/reel-profit-frames.png

Numbers are the demo data's (costs = 62% of selling rates), checked in CHECKS below:
Priya Example: price ₹1,72,710, cost ₹1,13,496, profit ₹59,214 (34.3%).
Year (4 won quotations): won ₹5,05,760; profit before GST ₹1,59,002; margin 33.2% (on ₹4,78,989 before GST).
"""
import math
import os
import subprocess
import sys

import imageio_ffmpeg
from PIL import Image, ImageDraw

from carousel_lost_jobs import rich_pill, rich_text, rich_width
from music import make_music
from reel_payments import GREEN, GREY, NAVY, RED, SH, SW, _inr, app_bar
from reel_tape_to_invoice import CAPTION_Y, CHIP_Y, LOGO, back_out, caption, chip, ease, heading, phase, put_phone
from static_ads import INK, MUTED, OUT, PAPER, TAPE, background, font

W, H, FPS = 1080, 1920, 30
BG = background(W, H)
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()

COSTS = [  # (item, you charge, your cost)
    ('Acrylic – Box Work', 1200, 744), ('Acrylic – Frame Work', 1200, 744), ('Laminates – Box Work', 850, 527),
    ('Veneer – Frame Work', 900, 558), ('Magic Corner (fitting)', 18000, 11500), ('Tandem Drawer (fitting)', 4500, 2900)]
PRICE, COST = 172710, 113496
PROFIT = PRICE - COST
YEAR_WON, YEAR_PROFIT, YEAR_REVENUE = 505760, 159001.81, 478988.81
CHECKS = [PROFIT == 59214, round(PROFIT / PRICE * 100, 1) == 34.3, 172710 + 175500 + 108500 + 49050 == YEAR_WON,
          round(YEAR_PROFIT / YEAR_REVENUE * 100, 1) == 33.2, all(round(c / p * 100) in (62, 64) for _, p, c in COSTS)]
assert all(CHECKS), CHECKS


def quote_card(t):
    """Big quotation total, then the question."""
    c = Image.new('RGBA', (860, 520), (0, 0, 0, 0))
    d = ImageDraw.Draw(c)
    d.rounded_rectangle([0, 0, 859, 519], radius=30, fill=(255, 255, 255, 250))
    d.rectangle([0, 0, 859, 90], fill=NAVY)
    d.rounded_rectangle([0, 0, 859, 60], radius=30, fill=NAVY)
    d.text((40, 46), 'Quotation #1 · Priya Example', font=font(34, 'bold'), fill='white', anchor='lm')
    d.text((40, 160), 'Kitchen + Master Bedroom', font=font(32, 'demi'), fill=GREY, anchor='lm')
    d.text((40, 250), 'FINAL TOTAL', font=font(32, 'bold'), fill=GREY, anchor='lm')
    k = ease((t - 0.3) / 1.0)
    rich_text(d, (40, 340), _inr(PRICE * k), 96, 'heavy', NAVY, 'lm')
    if t > 1.6:
        a = phase(t, 1.6, 2.0)
        d.text((40, 450), 'Profit on this job: ?', font=font(40, 'bold'),
               fill=tuple(int(v * a + 255 * (1 - a)) for v in RED), anchor='lm')
    return c


def costs_screen(t):
    s = Image.new('RGB', (SW, SH), (245, 246, 250))
    d = ImageDraw.Draw(s)
    app_bar(d, 'Costs & profit')
    d.text((34, 218), 'What each item costs you', font=font(28, 'demi'), fill=GREY, anchor='lm')
    y = 270
    d.text((40, y), 'Item', font=font(24, 'bold'), fill=GREY)
    d.text((470, y), 'Charge', font=font(24, 'bold'), fill=GREY, anchor='ra')
    d.text((610, y), 'Cost', font=font(24, 'bold'), fill=GREY, anchor='ra')
    d.text((716, y), 'Margin', font=font(24, 'bold'), fill=GREY, anchor='ra')
    y += 50
    for i, (name, price, cost) in enumerate(COSTS):
        d.rounded_rectangle([24, y, SW - 24, y + 120], radius=16, fill='white', outline=(230, 232, 236), width=2)
        d.text((40, y + 40), name.split(' (')[0], font=font(28, 'bold'), fill=NAVY, anchor='lm')
        d.text((40, y + 82), 'per unit' if '(fitting)' in name else 'per sqft', font=font(22, 'regular'), fill=GREY,
               anchor='lm')
        rich_text(d, (470, y + 60), _inr(price), 28, 'demi', INK, 'rm')
        typed = t > 0.6 + i * 0.35
        box = [490, y + 34, 616, y + 86]
        d.rounded_rectangle(box, radius=10, fill=(255, 251, 230) if typed else 'white', outline=TAPE if typed else GRID_C, width=3)
        if typed:
            rich_text(d, (606, y + 60), _inr(cost), 26, 'bold', INK, 'rm')
            d.text((716, y + 60), f'{round((price - cost) / price * 100)}%', font=font(28, 'bold'), fill=GREEN, anchor='rm')
        y += 136
    return s


GRID_C = (210, 214, 212)


def profit_screen(t):
    s = Image.new('RGB', (SW, SH), (245, 246, 250))
    d = ImageDraw.Draw(s)
    app_bar(d, 'Priya Example')
    d.rounded_rectangle([24, 220, SW - 24, 760], radius=18, fill='white', outline=(230, 232, 236), width=2)
    d.rectangle([24, 220, SW - 24, 296], fill=NAVY)
    d.text((48, 258), 'Estimated profit', font=font(32, 'bold'), fill='white', anchor='lm')
    d.text((SW - 48, 258), 'only admins see this', font=font(22, 'demi'), fill=(200, 210, 240), anchor='rm')
    k = ease((t - 0.5) / 1.2)
    rows = [('Price', PRICE, INK), ('Your cost', COST * k, INK), ('Profit', (PRICE - COST * k), GREEN)]
    y = 350
    for label, val, col in rows:
        d.text((60, y), label, font=font(34, 'demi'), fill=GREY, anchor='lm')
        rich_text(d, (SW - 60, y), _inr(val), 44 if label == 'Profit' else 38, 'heavy' if label == 'Profit' else 'bold',
                  col, 'rm')
        y += 92
    if k >= 1:
        d.rounded_rectangle([60, 620, SW - 60, 700], radius=14, fill=(209, 231, 221))
        d.text((SW / 2, 660), 'Margin 34.3%  (before GST)', font=font(32, 'bold'), fill=(15, 81, 50), anchor='mm')
    d.text((40, 820), 'Not shown to staff or customers.', font=font(28, 'demi'), fill=GREY, anchor='lm')
    d.text((40, 866), 'Never printed on PDFs.', font=font(28, 'demi'), fill=GREY, anchor='lm')
    return s


def year_screen(t):
    s = Image.new('RGB', (SW, SH), (245, 246, 250))
    d = ImageDraw.Draw(s)
    app_bar(d, 'Reports · 2026-27')
    cards = [('Won this year', _inr(YEAR_WON), '4 jobs', INK), ('Estimated profit', _inr(YEAR_PROFIT), 'before GST', GREEN),
             ('Margin', '33.2%', 'on the price before GST', GREEN)]
    y = 230
    for i, (label, val, sub, col) in enumerate(cards):
        k = ease((t - 0.3 - i * 0.3) / 0.35)
        if k <= 0:
            continue
        x = int(40 * (1 - k))
        d.rounded_rectangle([24 + x, y, SW - 24 + x, y + 190], radius=18, fill='white', outline=(230, 232, 236), width=2)
        d.text((48 + x, y + 44), label, font=font(30, 'demi'), fill=GREY, anchor='lm')
        rich_text(d, (48 + x, y + 112), val, 56, 'heavy', col, 'lm')
        d.text((48 + x, y + 162), sub, font=font(24, 'regular'), fill=GREY, anchor='lm')
        y += 215
    # month bars
    if t > 1.4:
        d.text((40, y + 20), 'Month by month', font=font(28, 'bold'), fill=NAVY, anchor='lm')
        bars = [0, 0, 0, 0, 0, 0.38, 1.0, 0, 0, 0, 0, 0]          # Sep and Oct have work (demo data)
        labels = 'AMJJASONDJFM'
        bx = 40
        for j, (b, lab) in enumerate(zip(bars, labels)):
            hgt = int(180 * b * ease((t - 1.4) / 0.6))
            d.rounded_rectangle([bx, y + 260 - hgt, bx + 40, y + 260], radius=6, fill=NAVY if b else (225, 228, 232))
            d.text((bx + 20, y + 290), lab, font=font(22, 'demi'), fill=GREY, anchor='mm')
            bx += 56
    return s


def scene_hook(t):
    img = BG.copy()
    heading(img, 'QUICK QUESTION', 'Do you know your profit?', 'Not the quote. What you actually make.', t)
    card = quote_card(t)
    y = 520 + int(700 * (1 - ease(t / 0.45)))
    img.alpha_composite(card, ((W - card.width) // 2, y))
    chip(img, 'Most owners only guess.', t, 2.4, bg=RED, fg='white')
    return img


def scene_costs(t):
    img = BG.copy()
    heading(img, 'STEP 1', 'Enter your costs once.', 'Materials, labour, fittings.', t)
    put_phone(img, costs_screen(t), t, 'right')
    caption(img, 'Only once. Change them anytime.', t, 2.6)
    return img


def scene_profit(t):
    img = BG.copy()
    heading(img, 'STEP 2', 'Every quote shows its profit.', 'Worked out the moment you save it.', t)
    put_phone(img, profit_screen(t), t, 'up')
    chip(img, '₹59,214 profit on this job', t, 1.9)
    return img


def scene_year(t):
    img = BG.copy()
    heading(img, 'STEP 3', 'See the whole year.', 'Won, collected and profit, every month.', t)
    put_phone(img, year_screen(t), t, 'right')
    chip(img, '₹1,59,002 profit this year', t, 2.2)
    return img


def scene_end(t):
    img = BG.copy()
    d = ImageDraw.Draw(img)
    k = back_out(t / 0.5)
    size = max(10, int(220 * min(k, 1.05)))
    img.alpha_composite(LOGO.resize((size, size)), ((W - size) // 2, 520 - size // 2))
    a = phase(t, 0.3, 0.7)
    col = lambda c: tuple(int(v * a + 14 * (1 - a)) for v in c)
    d.text((W / 2, 780), 'Know your margin.', font=font(92), fill=col(PAPER), anchor='mm')
    d.text((W / 2, 895), 'On every quote.', font=font(92), fill=col(TAPE), anchor='mm')
    if t > 0.9:
        b = phase(t, 0.9, 1.3)
        d.text((W / 2, 1025), 'Only you see it. Never your staff or customers.', font=font(38, 'demi'),
               fill=tuple(int(v * b + 14 * (1 - b)) for v in MUTED), anchor='mm')
    if t > 1.5:
        kk = back_out((t - 1.5) / 0.4)
        rich_pill(img, 'Start your free 7-day trial', W / 2, 1230, max(20, int(50 * min(kk, 1.05))))
    if t > 1.9:
        d.text((W / 2, 1370), 'No payment to start  ·  quote-room.co.in', font=font(34, 'demi'), fill=MUTED, anchor='mm')
    return img


SCENES = [(scene_hook, 4.2), (scene_costs, 4.8), (scene_profit, 4.4), (scene_year, 4.4), (scene_end, 4.4)]
XFADE = 0.25
STARTS, _acc = [], 0.0
for _, dur in SCENES:
    STARTS.append(_acc)
    _acc += dur
TOTAL = _acc


def frame_at(T):
    for i, ((fn, dur), start) in enumerate(zip(SCENES, STARTS)):
        if T < start + dur or i == len(SCENES) - 1:
            img = fn(T - start)
            if i + 1 < len(SCENES) and T > start + dur - XFADE:
                img = Image.blend(img.convert('RGB'), SCENES[i + 1][0](0.0).convert('RGB'),
                                  (T - (start + dur - XFADE)) / XFADE)
            return img.convert('RGB')


def render(path):
    music = make_music(TOTAL + 0.5, os.path.join(OUT, 'music-profit.wav'))
    cmd = [FFMPEG, '-y', '-loglevel', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{W}x{H}', '-r', str(FPS),
           '-i', '-', '-i', music, '-filter_complex', '[1:a]volume=0.9,loudnorm=I=-16:TP=-1.5,aresample=48000[a]',
           '-map', '0:v', '-map', '[a]', '-c:v', 'libx264', '-preset', 'medium', '-crf', '17', '-pix_fmt', 'yuv420p',
           '-c:a', 'aac', '-b:a', '160k', '-shortest', '-movflags', '+faststart', path]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for k in range(int(math.ceil(TOTAL * FPS))):
        proc.stdin.write(frame_at(k / FPS).tobytes())
    proc.stdin.close()
    proc.wait()
    print('wrote', path)


if __name__ == '__main__':
    os.makedirs(OUT, exist_ok=True)
    if len(sys.argv) > 1 and sys.argv[1] == 'stills':
        times = [STARTS[0] + 3.4, STARTS[1] + 3.6, STARTS[2] + 3.4, STARTS[3] + 3.4, STARTS[4] + 2.4]
        sheet = Image.new('RGB', (370 * len(times), 640), 'white')
        for i, T in enumerate(times):
            sheet.paste(frame_at(T).resize((360, 640)), (i * 370, 0))
        sheet.save(os.path.join(OUT, 'reel-profit-frames.png'))
        print('stills done')
    else:
        render(os.path.join(OUT, 'reel-profit-9x16.mp4'))
