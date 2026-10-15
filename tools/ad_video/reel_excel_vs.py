"""Reel 'Excel vs QuoteRoom': the same quote two ways (stacked split screen), then 'Same job. 37 minutes back.'

    python tools/ad_video/reel_excel_vs.py          → ad-videos/reel-excel-vs-9x16.mp4 and -4x5.mp4
    python tools/ad_video/reel_excel_vs.py stills   → ad-videos/reel-excel-vs-frames.png
"""
import math
import os
import subprocess
import sys

import imageio_ffmpeg
from PIL import Image, ImageDraw

from carousel_lost_jobs import rich_pill, rich_text
from music import make_music
from reel_tape_to_invoice import LOGO, back_out, chat_screen, ease, phase, to_4x5
from static_ads import ADS, INK, MUTED, OUT, PAPER, TAPE, background, brand, font, phone

W, H, FPS = 1080, 1920, 30
BG = background(W, H)
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
S_PAY = Image.open(f'{ADS}/04-room-totals-payments.jpg').convert('RGB')
RED, XL_GREEN, GRID = (214, 48, 49), (33, 115, 70), (210, 214, 212)

EXCEL_TOP, EXCEL_BOTTOM = 470, 1150
QR_TOP, QR_BOTTOM = 1185, 1880
RACE_START, QR_DONE, EXCEL_END, END_CARD = 2.0, 5.6, 13.6, 14.6
TOTAL = 21.0


def minutes_excel(t):
    """Same pace as QuoteRoom until QuoteRoom is done at 3 min; then the Excel clock fast-forwards to 40 min."""
    if t <= QR_DONE:
        return minutes_qr(t)
    return 3 + 37 * min(1.0, (t - QR_DONE) / (EXCEL_END - QR_DONE))


def minutes_qr(t):
    return 3 * max(0.0, min(1.0, (t - RACE_START) / (QR_DONE - RACE_START)))


def clock(d, cx, cy, r, minutes, colour):
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=colour, width=5)
    ang = minutes / 60 * 2 * math.pi - math.pi / 2
    d.line([(cx, cy), (cx + r * 0.75 * math.cos(ang), cy + r * 0.75 * math.sin(ang))], fill=colour, width=5)
    d.line([(cx, cy), (cx, cy - r * 0.5)], fill=colour, width=5)


def timer(img, x_right, y, minutes, colour, done=False):
    d = ImageDraw.Draw(img)
    label = f'{int(minutes)} min'
    f = font(46, 'heavy')
    w = f.getlength(label)
    d.text((x_right, y), label, font=f, fill=colour, anchor='rm')
    clock(d, x_right - w - 40, y, 22, minutes, colour)


# ── top: the spreadsheet ──

COLS = [('', 70), ('Item', 230), ('Length', 150), ('Width', 130), ('Sqft', 150), ('Rate', 130), ('Amount', 140)]


def sheet_rows(t):
    """What each row shows at time t (typed in slowly, with the usual mistakes)."""
    def typed(text, start, cps=9):
        n = int(max(0, (t - start) * cps))
        return text[:n]
    rows = [['1', 'Item', 'Length', 'Width', 'Sqft', 'Rate', 'Amount']]
    rows.append(['2', typed('Wardrobe', 2.3), typed('8', 3.2), typed('7', 3.4), '56' if t > 3.9 else typed('=B2*C2', 3.5),
                 typed('850', 4.1), '47,600' if t > 4.9 else typed('=D2*E2', 4.4)])
    rows.append(['3', typed('Loft', 5.1), typed('8', 5.6), typed('2', 5.8), '16' if t > 6.1 else '', typed('850', 6.1),
                 '13,600' if t > 6.6 else ''])
    length4 = typed('8\'6"', 6.9) if t < 9.4 else typed('8.6', 9.4)
    sqft4 = '' if t < 7.6 else ('#VALUE!' if t < 9.4 else ('51.6' if t > 9.9 else ''))
    amount4 = '' if t < 8.1 else ('#VALUE!' if t < 9.4 else ('61,920' if t > 10.2 else ''))
    rows.append(['4', typed('TV Unit', 6.7), length4, typed('6', 7.3), sqft4, typed('1200', 7.7), amount4])
    rows.append(['5', 'Total' if t > 11 else '', '', '', '', '', '1,23,120' if t > 11.6 else typed('=SUM(G2:G4)', 11.0)])
    return rows


def draw_sheet(img, t):
    d = ImageDraw.Draw(img)
    x0, y0 = 40, EXCEL_TOP + 150                      # below the EXCEL label and its clock
    sheet_w = sum(w for _, w in COLS)
    d.rounded_rectangle([x0 - 6, y0 - 70, x0 + sheet_w + 6, y0 + 40 + 5 * 78 + 8], radius=18, fill=(248, 249, 248))
    d.rectangle([x0, y0 - 64, x0 + sheet_w, y0 - 14], fill=XL_GREEN)
    d.text((x0 + 18, y0 - 39), 'Quotation_FINAL_v3 (2).xlsx', font=font(26, 'demi'), fill='white', anchor='lm')
    letters = ['', 'A', 'B', 'C', 'D', 'E', 'F']
    x = x0
    for (name, w), letter in zip(COLS, letters):
        d.rectangle([x, y0, x + w, y0 + 40], fill=(232, 235, 233), outline=GRID)
        d.text((x + w / 2, y0 + 20), letter, font=font(22, 'demi'), fill=(90, 100, 96), anchor='mm')
        x += w
    row_h = 78
    for r, row in enumerate(sheet_rows(t)):
        y = y0 + 40 + r * row_h
        x = x0
        for c, ((name, w), val) in enumerate(zip(COLS, row)):
            fill = (232, 235, 233) if c == 0 else ('white' if r else (244, 246, 245))
            bad = val == '#VALUE!'
            if bad:
                fill = (253, 226, 226)
            d.rectangle([x, y, x + w, y + row_h], fill=fill, outline=GRID)
            if val:
                weight = 'bold' if r == 0 or c == 0 or (r == 4 and c == 1) else 'medium'
                colour = RED if bad else ((90, 100, 96) if c == 0 else INK)
                anchor = 'mm' if c == 0 else ('rm' if c >= 2 and r else 'lm')
                tx = x + w / 2 if c == 0 else (x + w - 12 if anchor == 'rm' else x + 12)
                d.text((tx, y + row_h / 2), val, font=font(26 if len(val) < 10 else 22, weight), fill=colour, anchor=anchor)
            x += w
    # mistakes, called out
    if 7.8 < t < 9.4:
        rich_pill(img, '#VALUE!  ?!', 760, y0 + 40 + 3 * row_h - 50, 30, fg='white', bg=RED)
    if 10.0 < t < 13.6:
        rich_pill(img, '8.6 is not 8 ft 6 in (that\'s 8.5)', 560, y0 + 40 + 4 * row_h + 52, 26, fg='white', bg=RED)


def draw_excel_panel(img, t):
    d = ImageDraw.Draw(img)
    rich_pill(img, 'EXCEL', 140, EXCEL_TOP + 30, 28, fg='white', bg=XL_GREEN)
    over = t > EXCEL_END
    timer(img, W - 60, EXCEL_TOP + 30, minutes_excel(t), RED if minutes_excel(t) > 20 else PAPER)
    if QR_DONE < t <= EXCEL_END:                       # be honest that this clock is sped up
        ImageDraw.Draw(img).text((W - 330, EXCEL_TOP + 30), 'FAST-FORWARD', font=font(24, 'bold'), fill=MUTED, anchor='rm')
    draw_sheet(img, t)
    if over:
        layer = Image.new('RGBA', (W, EXCEL_BOTTOM - EXCEL_TOP - 70), (14, 34, 28, 150))
        img.alpha_composite(layer, (0, EXCEL_TOP + 70))                  # the clock stays visible
        rich_pill(img, 'Still not sent…', W / 2, (EXCEL_TOP + 70 + EXCEL_BOTTOM) / 2, 44, fg='white', bg=RED)


# ── bottom: QuoteRoom ──

STEPS = [(2.6, 'Rooms & items added'), (3.4, 'Sqft & totals worked out'), (4.3, 'Branded PDF ready'), (5.2, 'Sent on WhatsApp')]


def draw_qr_panel(img, t):
    d = ImageDraw.Draw(img)
    d.line([(40, QR_TOP - 18), (W - 40, QR_TOP - 18)], fill=(60, 90, 80), width=2)
    rich_pill(img, 'QUOTEROOM', 175, QR_TOP + 30, 28)
    done = t >= QR_DONE
    timer(img, W - 60, QR_TOP + 30, minutes_qr(t), TAPE if done else PAPER)
    screen = S_PAY.crop((0, 0, 750, 1450)) if t < 4.6 else chat_screen(3.0 + (t - 4.6))
    ph, pad = phone(screen, 330)
    img.alpha_composite(ph, (W - 60 - 330 - pad, QR_TOP + 80 - pad))
    y = QR_TOP + 130
    for at, text in STEPS:
        if t >= at:
            k = min(1.0, back_out((t - at) / 0.3))
            r = int(24 * k)
            d.ellipse([84 - r, y + 22 - r, 84 + r, y + 22 + r], fill=TAPE)
            if k > 0.8:
                d.line([(73, y + 22), (81, y + 31), (96, y + 13)], fill=INK, width=5)
            d.text((124, y + 2), text, font=font(36, 'demi'), fill=PAPER)
        y += 76
    if done:
        rich_pill(img, 'Done in 3 min  ✓', 320, y + 40, 38, fg=(8, 40, 20), bg=(37, 211, 102))
    if t > 9.0:
        k = min(1.0, back_out((t - 9.0) / 0.35))
        rich_pill(img, 'Customer accepted  ✓', 320, y + 150, int(32 * k) or 1, fg=(30, 64, 175), bg=(219, 234, 254))


# ── scenes ──

def hook(img, t):
    d = ImageDraw.Draw(img)
    brand(img, 60, 110, 46)
    a = phase(t, 0.0, 0.4)
    col = lambda c: tuple(int(v * a + 14 * (1 - a)) for v in c)
    d.text((60, 240), 'Same quote.', font=font(88), fill=col(PAPER))
    d.text((60, 345), 'Two ways.', font=font(88), fill=col(TAPE))


def race_frame(t):
    img = BG.copy()
    hook(img, t)
    if t > 0.6:
        draw_excel_panel(img, t)
        draw_qr_panel(img, t)
    return img


def end_frame(t):
    img = BG.copy()
    d = ImageDraw.Draw(img)
    k = back_out(t / 0.5)
    size = max(10, int(220 * min(k, 1.05)))
    img.alpha_composite(LOGO.resize((size, size)), ((W - size) // 2, 520 - size // 2))
    a = phase(t, 0.3, 0.7)
    col = lambda c: tuple(int(v * a + 14 * (1 - a)) for v in c)
    d.text((W / 2, 780), 'Same job.', font=font(96), fill=col(PAPER), anchor='mm')
    d.text((W / 2, 900), '37 minutes back.', font=font(96), fill=col(TAPE), anchor='mm')
    if t > 0.9:
        b = phase(t, 0.9, 1.3)
        d.text((W / 2, 1030), 'On every quote. Every day.', font=font(42, 'demi'),
               fill=tuple(int(v * b + 14 * (1 - b)) for v in MUTED), anchor='mm')
    if t > 1.5:
        kk = back_out((t - 1.5) / 0.4)
        rich_pill(img, 'Start your free 7-day trial', W / 2, 1230, max(20, int(50 * min(kk, 1.05))))
    if t > 1.9:
        d.text((W / 2, 1370), 'No payment to start  ·  quote-room.co.in', font=font(34, 'demi'), fill=MUTED, anchor='mm')
    return img


def frame_at(T):
    if T < END_CARD - 0.3:
        return race_frame(T).convert('RGB')
    if T < END_CARD:
        a = (T - (END_CARD - 0.3)) / 0.3
        return Image.blend(race_frame(T).convert('RGB'), end_frame(0).convert('RGB'), a)
    return end_frame(T - END_CARD).convert('RGB')


def render(path, fmt):
    size = (1080, 1920) if fmt == '9x16' else (1080, 1350)
    music = make_music(TOTAL + 0.5, os.path.join(OUT, 'music-excel.wav'))
    cmd = [FFMPEG, '-y', '-loglevel', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{size[0]}x{size[1]}',
           '-r', str(FPS), '-i', '-', '-i', music,
           '-filter_complex', '[1:a]volume=0.9,loudnorm=I=-16:TP=-1.5,aresample=48000[a]',
           '-map', '0:v', '-map', '[a]', '-c:v', 'libx264', '-preset', 'medium', '-crf', '17', '-pix_fmt', 'yuv420p',
           '-c:a', 'aac', '-b:a', '160k', '-shortest', '-movflags', '+faststart', path]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for k in range(int(math.ceil(TOTAL * FPS))):
        img = frame_at(k / FPS)
        proc.stdin.write((img if fmt == '9x16' else to_4x5(img)).tobytes())
    proc.stdin.close()
    proc.wait()
    print('wrote', path)


if __name__ == '__main__':
    os.makedirs(OUT, exist_ok=True)
    if len(sys.argv) > 1 and sys.argv[1] == 'stills':
        times = [3.0, 6.0, 8.6, 11.8, 14.2, 17.5]
        sheet = Image.new('RGB', (370 * len(times), 640), 'white')
        for i, T in enumerate(times):
            sheet.paste(frame_at(T).resize((360, 640)), (i * 370, 0))
        sheet.save(os.path.join(OUT, 'reel-excel-vs-frames.png'))
        print('stills done')
    else:
        for fmt in ('9x16', '4x5'):
            render(os.path.join(OUT, f'reel-excel-vs-{fmt}.mp4'), fmt)
