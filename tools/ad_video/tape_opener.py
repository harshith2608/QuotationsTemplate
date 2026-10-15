"""Reel opener: an animated tape measure sizes a wardrobe (8 ft 6 in × 6 ft), then the app shows the same item.

    python tools/ad_video/tape_opener.py   → ad-videos/preview-tape-opener.mp4 (+ preview-tape-opener-frames.png)
"""
import math
import os

import imageio_ffmpeg
import numpy as np
from PIL import Image, ImageDraw

from carousel_lost_jobs import rich_pill
from static_ads import INK, MUTED, OUT, PAPER, S_ADD, TAPE, background, brand, font, phone

W, H, FPS = 1080, 1920, 30
PX_PER_FT = 89.4
WARD_W_FT, WARD_H_FT = 8.5, 6.0
X0, Y1 = 160, 1180                                   # wardrobe left edge, bottom edge
X1 = X0 + WARD_W_FT * PX_PER_FT
Y0 = Y1 - WARD_H_FT * PX_PER_FT
BG = background(W, H)
PHONE, PHONE_PAD = phone(S_ADD.crop((0, 0, 750, 1450)), 540)


def ease(t):
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


def phase(t, start, end):
    return ease((t - start) / (end - start))


def ft_in(feet):
    whole = int(feet + 1e-6)
    inches = int(round((feet - whole) * 12))
    if inches == 12:
        whole, inches = whole + 1, 0
    return f'{whole} ft {inches} in'


def wardrobe(d, alpha):
    col = tuple(int(c * alpha + 14 * (1 - alpha)) for c in PAPER)
    d.rounded_rectangle([X0, Y0, X1, Y1], radius=10, outline=col, width=6)
    mid = (X0 + X1) / 2
    d.line([(mid, Y0), (mid, Y1)], fill=col, width=5)
    for hx in (mid - 30, mid + 30):
        d.rounded_rectangle([hx - 5, Y0 + 230, hx + 5, Y0 + 310], radius=5, fill=col)
    d.line([(X0, Y0 + 90), (X1, Y0 + 90)], fill=col, width=4)          # loft line


def tape(img, start, length_px, horizontal, label):
    """Tape case at `start`, blade of length_px (along +x, or up along -y), with inch ticks and the reading."""
    d = ImageDraw.Draw(img)
    sx, sy = start
    if horizontal:
        d.rectangle([sx, sy - 17, sx + length_px, sy + 17], fill=TAPE)
        n = int(length_px / (PX_PER_FT / 12))
        for i in range(n + 1):
            x = sx + i * PX_PER_FT / 12
            big = i % 12 == 0
            d.line([(x, sy - 17), (x, sy - 17 + (22 if big else 11))], fill=INK, width=3 if big else 2)
            if big and i:
                d.text((x, sy + 4), str(i // 12), font=font(16, 'bold'), fill=INK, anchor='mt')
        d.rectangle([sx + length_px - 4, sy - 24, sx + length_px + 6, sy + 24], fill=(90, 70, 10))   # metal hook
        case = [sx - 120, sy - 62, sx, sy + 62]
        tip = (sx + length_px, sy - 70)
    else:
        d.rectangle([sx - 17, sy - length_px, sx + 17, sy], fill=TAPE)
        n = int(length_px / (PX_PER_FT / 12))
        for i in range(n + 1):
            y = sy - i * PX_PER_FT / 12
            big = i % 12 == 0
            d.line([(sx + 17, y), (sx + 17 - (22 if big else 11), y)], fill=INK, width=3 if big else 2)
            if big and i:
                d.text((sx - 4, y), str(i // 12), font=font(16, 'bold'), fill=INK, anchor='rm')
        d.rectangle([sx - 24, sy - length_px - 6, sx + 24, sy - length_px + 4], fill=(90, 70, 10))
        case = [sx - 62, sy, sx + 62, sy + 124]
        tip = (sx - 44, sy - length_px / 2)          # beside the middle of the blade, clear of the top tape
    d.rounded_rectangle(case, radius=26, fill=TAPE, outline=(150, 112, 0), width=4)
    cx, cy = (case[0] + case[2]) / 2, (case[1] + case[3]) / 2
    d.ellipse([cx - 34, cy - 34, cx + 34, cy + 34], fill=(40, 52, 47))
    d.ellipse([cx - 12, cy - 12, cx + 12, cy + 12], fill=TAPE)
    if label:
        f = font(58, 'heavy')
        anchor = 'mb' if horizontal else 'rm'
        x0, y0, x1, y1 = d.textbbox(tip, label, font=f, anchor=anchor)
        d.rounded_rectangle([x0 - 16, y0 - 10, x1 + 16, y1 + 10], radius=16, fill=(14, 34, 28, 235))
        d.text(tip, label, font=f, fill=TAPE, anchor=anchor)


def frame(t):
    img = BG.copy()
    d = ImageDraw.Draw(img)
    brand(img, 60, 110, 46)
    d.text((60, 230), 'STEP 1', font=font(34, 'bold'), fill=TAPE)
    d.text((60, 280), 'Measure on site.', font=font(84), fill=PAPER)
    d.text((60, 390), 'In feet and inches, like you always do.', font=font(40, 'demi'), fill=MUTED)

    out = phase(t, 4.6, 5.4)                       # drawing makes way for the phone
    if out < 1:
        layer = Image.new('RGBA', (W, H), (0, 0, 0, 0))
        ld = ImageDraw.Draw(layer)
        wardrobe(ld, phase(t, 0.0, 0.5))
        w_len = phase(t, 0.5, 2.3) * WARD_W_FT
        if t > 0.5:
            tape(layer, (X0, Y0 - 70), w_len * PX_PER_FT, True, ft_in(w_len))
        h_len = phase(t, 2.4, 3.8) * WARD_H_FT
        if t > 2.4:
            tape(layer, (X1 + 70, Y1), h_len * PX_PER_FT, False, ft_in(h_len))
        if out > 0:
            layer.putalpha(layer.getchannel('A').point(lambda a: int(a * (1 - out))))
        img.alpha_composite(layer)
    pop = phase(t, 3.9, 4.3)
    if pop > 0:
        chip_y = (Y1 + 190) + (1590 - (Y1 + 190)) * out
        size = int(40 + 6 * math.sin(min(pop, 1) * math.pi))
        rich_pill(img, "8 ft 6 in × 6 ft = 51 sqft", W / 2, chip_y, size)
    if out > 0:
        py = int(H + 40 - (H + 40 - 470) * out)
        img.alpha_composite(PHONE, ((W - (PHONE.width - 2 * PHONE_PAD)) // 2 - PHONE_PAD, py - PHONE_PAD))
        if t > 5.2:
            rich_pill(img, "8 ft 6 in × 6 ft = 51 sqft", W / 2, 1590, 40)
            d = ImageDraw.Draw(img)
            a = phase(t, 5.5, 5.9)
            col = tuple(int(c * a + 14 * (1 - a)) for c in PAPER)
            d.text((W / 2, 1712), 'Type the size. The sqft is worked out.', font=font(40, 'demi'), fill=col, anchor='mm')
    return img.convert('RGB')


if __name__ == '__main__':
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, 'preview-tape-opener.mp4')
    duration = 6.6
    writer = imageio_ffmpeg.write_frames(path, (W, H), fps=FPS, codec='libx264', pix_fmt_out='yuv420p',
                                         output_params=['-crf', '20', '-movflags', '+faststart'], macro_block_size=1)
    writer.send(None)
    stills = []
    for i in range(int(duration * FPS)):
        t = i / FPS
        f = frame(t)
        writer.send(np.asarray(f).tobytes())
        if i in (int(1.4 * FPS), int(3.2 * FPS), int(4.3 * FPS), int(6.3 * FPS)):
            stills.append(f.resize((360, 640)))
    writer.close()
    sheet = Image.new('RGB', (370 * len(stills), 640), 'white')
    for i, s in enumerate(stills):
        sheet.paste(s, (i * 370, 0))
    sheet.save(os.path.join(OUT, 'preview-tape-opener-frames.png'))
    print('wrote', path)
