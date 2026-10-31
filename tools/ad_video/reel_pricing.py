"""Reel 'Price your way' (by material or by item): every firm prices differently, most apps make you price their way →
QuoteRoom works your way, one choice in Settings → by material (type the size, pick the material, the area and price
work themselves out; fittings from your price list; the PDF room by room) → by item, one click (each line with its own
rate, unit and description; the PDF as a bill of quantities) → free trial. The app on a LAPTOP with a close-up below.

Screens recorded by tools/tutorials/pricing_reel_screens.py (fictional "Nest & Grain Interiors": Sneha Example by
material, Rohan Example by item).

    python tools/ad_video/reel_pricing.py <workdir>          → ad-videos/reel-pricing-9x16.mp4
    python tools/ad_video/reel_pricing.py <workdir> stills   → ad-videos/reel-pricing-frames.png
"""
import json
import os
import sys

from PIL import Image, ImageDraw

from carousel_lost_jobs import rich_pill, rich_text
from reel_revisions import GREEN, GREEN_INK, RED, chip
from reel_tape_to_invoice import LOGO, back_out, ease, phase
from reel_templates import BG, W, heading, make_frame_at, part, put_laptop, render, zoom
from static_ads import INK, MUTED, OUT, PAPER, TAPE, font

PDF_MAT = (300, 430, 1240, 770)          # the customer's PDF: the quotation table (screenshot pixels)
PDF_BOQ = [(300, 430, 1240, 700), (300, 640, 1240, 950)]     # …and the bill of quantities, in two halves


def load(workdir):
    d = os.path.join(workdir, 'pricing')
    S = {os.path.splitext(f)[0]: Image.open(os.path.join(d, f)).convert('RGB') for f in os.listdir(d) if f.endswith('.png')}
    S['m'] = json.load(open(os.path.join(d, 'marks.json')))
    return S


WAYS = [('By material', ['Wardrobe 7 ft × 8 ft', 'Laminate – Box Work', 'at your rate per sqft']),
        ('By item', ['Wardrobe 56 sqft × ₹1,950', 'Side table 2 Nos. × ₹15,000', '3D design ₹50,000 lump sum'])]


def hook(t):
    img = BG.copy()
    heading(img, 'Every firm prices differently.', 'Which way is yours?', t)
    for i, (head, lines) in enumerate(WAYS):
        st = 0.4 + i * 0.6
        if t < st:
            continue
        k = back_out((t - st) / 0.35)
        y = 560 + i * 400 + int(40 * (1 - min(k, 1)))
        layer = Image.new('RGBA', img.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        d.rounded_rectangle([80, y, W - 80, y + 340], radius=30, fill=(250, 250, 248, 245))
        d.text((130, y + 60), head, font=font(54), fill=INK, anchor='lm')
        for j, l in enumerate(lines):
            rich_text(d, (130, y + 140 + j * 64), '•  ' + l, 40, 'demi', (60, 72, 66), 'lm')       # ₹ needs rich_text
        img.alpha_composite(layer)
    if t > 1.9:
        k = back_out((t - 1.9) / 0.35)
        rich_pill(img, 'Most apps make you price their way', W / 2, 1450, max(12, int(44 * min(k, 1.05))),
                  fg='white', bg=RED)
    return img


def solution(t):
    img = BG.copy()
    d = ImageDraw.Draw(img)
    k = back_out(t / 0.5)
    size = max(10, int(220 * min(k, 1.05)))
    img.alpha_composite(LOGO.resize((size, size)), ((W - size) // 2, 560 - size // 2))
    a = phase(t, 0.25, 0.6)
    col = lambda c: tuple(int(v * a + 14 * (1 - a)) for v in c)
    d.text((W / 2, 800), 'QuoteRoom works', font=font(80), fill=col(PAPER), anchor='mm')
    d.text((W / 2, 900), 'your way.', font=font(80), fill=col(TAPE), anchor='mm')
    b = phase(t, 0.7, 1.0)
    colb = lambda c: tuple(int(v * b + 14 * (1 - b)) for v in c)
    for i, line in enumerate(['By material or by item.', 'Pick once in Settings. Change it any time.']):
        d.text((W / 2, 1040 + i * 66), line, font=font(40, 'demi'), fill=colb(MUTED), anchor='mm')
    return img


def scenes(S):
    m = S['m']

    def settings(t):
        img = BG.copy()
        heading(img, 'How do you price?', 'Choose once, in Settings', t)
        put_laptop(img, S['settings_material'])
        zoom(img, S['settings_material'], part(m['settings_material']['box'], 0, 0.28, 0.5, 1), t, start=0.3)
        chip(img, 'One choice for your whole team', t, 1.4)
        return img

    def material(t):
        img = BG.copy()
        heading(img, 'By material', 'Type the size, pick the material', t)
        put_laptop(img, S['mat_edit'])
        zoom(img, S['mat_edit'], part(m['mat_edit']['box'], 0, 0.15, 1, 0.95), t, start=0.3)
        chip(img, 'The area and the price work themselves out', t, 1.4)
        return img

    def fittings(t):
        img = BG.copy()
        heading(img, 'By material', 'Fittings & accessories too', t)
        put_laptop(img, S['mat_fittings'])
        zoom(img, S['mat_fittings'], part(m['mat_fittings']['box'], 0, 0.48, 1, 0.9), t, start=0.3)
        chip(img, 'Magic Corner, drawers… from your price list', t, 1.3)
        return img

    def mat_pdf(t):
        img = BG.copy()
        heading(img, 'By material', 'Your customer\'s PDF: room by room, with sizes', t)
        put_laptop(img, S['mat_pdf'])
        zoom(img, S['mat_pdf'], PDF_MAT, t, start=0.3)
        return img

    def switch(t):
        img = BG.copy()
        heading(img, 'Price by item? One click.', 'Choose By item, Save', t)
        if t < 1.0:
            put_laptop(img, S['settings_click'], m['settings_click']['tap'], t - 0.4 if t >= 0.4 else None)
            zoom(img, S['settings_click'], part(m['settings_click']['box'], 0.5, 0.28, 1, 1), t, start=0.2)
        elif t < 1.8:
            put_laptop(img, S['settings_save'], m['settings_save']['tap'], t - 1.2 if t >= 1.2 else None)
            zoom(img, S['settings_save'], part(m['settings_save']['box'], 0.5, 0.28, 1, 1), 1.0, start=0.0)
        else:
            put_laptop(img, S['settings_item'])
            zoom(img, S['settings_item'], part(m['settings_item']['box'], 0.5, 0.28, 1, 1), 1.0, start=0.0)
        chip(img, 'Quotations already made stay as they are', t, 2.0)
        return img

    def item(t):
        img = BG.copy()
        heading(img, 'By item', 'Each line with its own rate', t)
        put_laptop(img, S['item_edit'])
        zoom(img, S['item_edit'], part(m['item_edit']['box'], 0, 0.15, 1, 0.82), t, start=0.3)
        chip(img, 'Per sqft, running ft, number or lump sum', t, 1.4)
        return img

    def item_pdf(t):
        img = BG.copy()
        heading(img, 'By item', 'Your customer\'s PDF: a bill of quantities', t)
        put_laptop(img, S['item_pdf'])
        zoom(img, S['item_pdf'], PDF_BOQ[0], t, start=0.3) if t < 1.7 else zoom(img, S['item_pdf'], PDF_BOQ[1], t - 1.7, start=0.0)
        chip(img, 'Sr. No. · Description · Qty · Unit · Rate · Amount', t, 1.4, fg=GREEN_INK, bg=GREEN)
        return img

    def end(t):
        img = BG.copy()
        d = ImageDraw.Draw(img)
        k = back_out(t / 0.5)
        size = max(10, int(240 * min(k, 1.05)))
        img.alpha_composite(LOGO.resize((size, size)), ((W - size) // 2, 560 - size // 2))
        a = phase(t, 0.3, 0.7)
        col = lambda c: tuple(int(v * a + 14 * (1 - a)) for v in c)
        d.text((W / 2, 820), 'Your pricing.', font=font(80), fill=col(PAPER), anchor='mm')
        d.text((W / 2, 915), 'Your quotation.', font=font(80), fill=col(TAPE), anchor='mm')
        if t > 0.9:
            kk = back_out((t - 0.9) / 0.4)
            rich_pill(img, 'Start your free 7-day trial', W / 2, 1150, max(20, int(50 * min(kk, 1.05))))
        if t > 1.3:
            d.text((W / 2, 1290), 'No payment to start  ·  quote-room.co.in', font=font(34, 'demi'), fill=MUTED,
                   anchor='mm')
        return img

    scenes_ = [(hook, 3.6), (solution, 2.4), (settings, 3.2), (material, 3.4), (fittings, 2.9), (mat_pdf, 2.8),
               (switch, 3.4), (item, 3.4), (item_pdf, 3.8), (end, 3.4)]
    # everything (scenes and the animations inside them) at 1/PACE speed: time to read each screen
    return [((lambda fn: lambda t: fn(t / PACE))(fn), dur * PACE) for fn, dur in scenes_]


PACE = 1.4


if __name__ == '__main__':
    os.makedirs(OUT, exist_ok=True)
    S = load(sys.argv[1])
    sc = scenes(S)
    frame_at, total, starts = make_frame_at(sc)
    if len(sys.argv) > 2 and sys.argv[2] == 'stills':
        times = [s + d - 0.5 for s, (_, d) in zip(starts, sc)]
        sheet = Image.new('RGB', (370 * len(times), 640), 'white')
        for i, T in enumerate(times):
            sheet.paste(frame_at(T).resize((360, 640)), (i * 370, 0))
        sheet.save(os.path.join(OUT, 'reel-pricing-frames.png'))
        print('stills done', round(total, 1), 's')
    else:
        render(frame_at, total, os.path.join(OUT, 'reel-pricing-9x16.mp4'), '9x16')
