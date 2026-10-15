"""Reel 'Stop chasing payments': call log → Balances due → one-tap WhatsApp reminder → paid (9:16 only).

    python tools/ad_video/reel_payments.py          → ad-videos/reel-payments-9x16.mp4
    python tools/ad_video/reel_payments.py stills   → ad-videos/reel-payments-frames.png

Screens are drawn in the app's style, with the fictional business Nest & Grain Interiors and demo customers.
Numbers match the demo data: Arjun Placeholder, total ₹1,08,500, paid ₹30,000, due ₹78,500.
"""
import math
import os
import subprocess
import sys

import imageio_ffmpeg
from PIL import Image, ImageDraw

from carousel_lost_jobs import rich_pill, rich_text
from music import make_music
from reel_tape_to_invoice import (CAPTION_Y, CHIP_Y, LOGO, PHONE_TOP, PHONE_W, WA_BAR, WA_BG, WA_OUT, _ticks, back_out,
                                  caption, chip, ease, heading, phase, put_phone)
from static_ads import INK, MUTED, OUT, PAPER, TAPE, background, font

W, H, FPS = 1080, 1920, 30
BG = background(W, H)
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
NAVY, RED, GREEN, GREY = (26, 35, 126), (220, 53, 69), (25, 135, 84), (108, 117, 125)
SW, SH = 750, 1450

DUE = [  # (customer, quotation, stage, stage colours, total, paid, balance, reminded)
    ('Priya Example', '#1', 'Confirmed', ((30, 64, 175), (219, 234, 254)), '₹1,72,710', '₹50,000', '₹1,22,710', 'not reminded yet'),
    ('Arjun Placeholder', '#4', 'On hold', ((51, 65, 85), (226, 232, 240)), '₹1,08,500', '₹30,000', '₹78,500', 'not reminded yet'),
    ('Rahul Sample', '#2 · INV/2026-27/001', 'Ongoing', ((91, 33, 182), (237, 233, 254)), '₹1,75,500', '₹1,15,000', '₹60,500',
     'last reminded 10 Oct'),
]


def _rich_w(text, size, weight='heavy'):
    from carousel_lost_jobs import rich_width
    return rich_width(text, size, weight)


def app_bar(d, title):
    d.rectangle([0, 0, SW, 110], fill=NAVY)
    d.text((34, 55), 'Nest & Grain Interiors', font=font(30, 'bold'), fill='white', anchor='lm')
    for i in range(3):
        d.rounded_rectangle([660, 38 + i * 14, 712, 44 + i * 14], radius=3, fill='white')
    d.text((34, 160), title, font=font(42, 'bold'), fill=NAVY, anchor='lm')


def call_log(t):
    """Phone call log: the same customers called again and again, no answer."""
    s = Image.new('RGB', (SW, SH), (250, 250, 250))
    d = ImageDraw.Draw(s)
    d.text((40, 70), 'Recents', font=font(52, 'bold'), fill=(20, 20, 20))
    calls = [('Arjun Placeholder', 'Outgoing · no answer', 'Today'), ('Priya Example', 'Outgoing · busy', 'Today'),
             ('Arjun Placeholder', 'Outgoing · no answer', 'Yesterday'), ('Rahul Sample', 'Outgoing · 0:12', 'Yesterday'),
             ('Arjun Placeholder', 'Outgoing · no answer', 'Mon'), ('Priya Example', 'Outgoing · no answer', 'Mon'),
             ('Arjun Placeholder', 'Outgoing · no answer', 'Sat')]
    y = 170
    shown = int(min(len(calls), max(0, (t - 0.2) / 0.22)))
    for name, kind, when in calls[:shown]:
        d.ellipse([36, y + 14, 126, y + 104], fill=(225, 228, 232))
        d.text((81, y + 59), name[0], font=font(40, 'bold'), fill=(90, 96, 104), anchor='mm')
        d.text((150, y + 26), name, font=font(40, 'demi'), fill=RED if 'no answer' in kind else (20, 20, 20))
        d.text((150, y + 76), kind, font=font(30, 'regular'), fill=GREY)
        d.text((714, y + 58), when, font=font(30, 'regular'), fill=GREY, anchor='rm')
        d.line([(150, y + 128), (SW, y + 128)], fill=(230, 230, 230), width=2)
        y += 140
    return s


def balances_screen(t):
    s = Image.new('RGB', (SW, SH), (245, 246, 250))
    d = ImageDraw.Draw(s)
    app_bar(d, 'Balances due')
    total = '₹2,61,710'                    # = 1,22,710 + 78,500 + 60,500 (the three cards below)
    rich_text(d, (34, 236), total, 46, 'heavy', RED, 'lm')
    d.text((34 + 24 + _rich_w(total, 46), 238), 'to collect', font=font(32, 'demi'), fill=GREY, anchor='lm')
    y = 300
    for i, (name, ref, stage, (sfg, sbg), tot, paid, bal, rem) in enumerate(DUE):
        k = ease((t - 0.3 - i * 0.18) / 0.3)
        if k <= 0:
            continue
        x = int(40 * (1 - k))
        highlight = name.startswith('Arjun') and t > 1.4
        d.rounded_rectangle([20 + x, y, SW - 20 + x, y + 300], radius=20, fill='white',
                            outline=TAPE if highlight else (230, 232, 236), width=6 if highlight else 2)
        d.text((44 + x, y + 46), name, font=font(40, 'bold'), fill=NAVY, anchor='lm')
        rich_text(d, (SW - 44 + x, y + 46), bal, 40, 'heavy', RED, 'rm')
        sw_ = font(26, 'bold').getlength(stage) + 34
        d.rounded_rectangle([44 + x, y + 92, 44 + x + sw_, y + 134], radius=21, fill=sbg)
        d.text((44 + x + sw_ / 2, y + 113), stage, font=font(26, 'bold'), fill=sfg, anchor='mm')
        rich_text(d, (44 + x, y + 182), f'Paid {paid} of {tot}', 30, 'regular', GREY, 'lm')
        d.text((44 + x, y + 250), rem, font=font(26, 'regular'), fill=GREY, anchor='lm')
        btn = [SW - 250 + x, y + 222, SW - 44 + x, y + 278]
        pressed = highlight and t > 2.2
        d.rounded_rectangle(btn, radius=12, fill=(20, 108, 67) if pressed else GREEN)
        d.text(((btn[0] + btn[2]) / 2, (btn[1] + btn[3]) / 2), 'Remind', font=font(30, 'bold'), fill='white', anchor='mm')
        if highlight and 1.9 < t < 2.6:                      # finger tap on Remind
            r = int(34 + 24 * ((t - 1.9) / 0.7))
            cx, cy = (btn[0] + btn[2]) / 2, (btn[1] + btn[3]) / 2
            d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=TAPE, width=5)
        y += 330
    return s


REMINDER = ['Hello Arjun Placeholder,', '', 'This is a friendly reminder from', 'Nest & Grain Interiors about the',
            'payment for Quotation #4.', '', 'Total: Rs.1,08,500.00', 'Received so far: Rs.30,000.00',
            'Amount due: Rs.78,500.00', '', 'Pay online: rzp.io/l/nestgrain-4', 'UPI: nestandgrain@upi', '',
            'Please ignore this message if you', 'have already paid. Thank you!']


def reminder_chat(t):
    s = Image.new('RGB', (SW, SH), WA_BG)
    d = ImageDraw.Draw(s)
    d.rectangle([0, 0, SW, 150], fill=WA_BAR)
    d.ellipse([86, 40, 156, 110], fill=(200, 214, 208))
    d.text((121, 75), 'A', font=font(38, 'bold'), fill=WA_BAR, anchor='mm')
    d.text((180, 52), 'Arjun Placeholder', font=font(36, 'bold'), fill='white')
    d.text((180, 98), 'online', font=font(26, 'regular'), fill=(200, 230, 220))
    d.text((40, 75), '‹', font=font(60, 'bold'), fill='white', anchor='lm')
    if t > 0.4:
        lines = REMINDER[:int(min(len(REMINDER), (t - 0.4) / 0.06))]
        bx0, bx1, y = 90, 715, 210
        h = 40 + 40 * len(REMINDER) + 30
        d.rounded_rectangle([bx0, y, bx1, y + h], radius=22, fill=WA_OUT)
        yy = y + 26
        for i, line in enumerate(lines):
            bold = line.startswith('Amount due')
            link = line.startswith('Pay online')
            d.text((bx0 + 24, yy), line, font=font(29, 'bold' if bold else 'regular'),
                   fill=(3, 120, 190) if link else (30, 40, 36))
            yy += 40
        _ticks(d, bx1 - 30, y + h - 26, t > 2.4)
        d.text((bx1 - 70, y + h - 26), '10:14', font=font(22, 'regular'), fill=(110, 120, 115), anchor='rm')
    if t > 3.0:                                               # the customer answers
        k = ease((t - 3.0) / 0.3)
        y = 210 + 40 + 40 * len(REMINDER) + 30 + 30
        d.rounded_rectangle([40, y, 520, y + 100], radius=22, fill='white')
        d.text((66, y + 34), 'Sorry! Paying it today.', font=font(30, 'regular'),
               fill=(30, 40, 36))
        d.text((494, y + 76), '10:21', font=font(22, 'regular'), fill=(110, 120, 115), anchor='rm')
    d.rectangle([0, 1330, SW, SH], fill=(240, 240, 240))
    d.rounded_rectangle([30, 1350, 620, 1430], radius=40, fill='white')
    d.text((70, 1390), 'Message', font=font(30, 'regular'), fill=(150, 150, 150), anchor='lm')
    d.ellipse([640, 1350, 720, 1430], fill=(0, 168, 132))
    return s


def paid_screen(t):
    s = Image.new('RGB', (SW, SH), (245, 246, 250))
    d = ImageDraw.Draw(s)
    app_bar(d, 'Arjun Placeholder')
    paid_k = ease((t - 0.8) / 0.8)                            # the paid bar fills up
    d.rounded_rectangle([24, 220, SW - 24, 780], radius=18, fill='white', outline=(230, 232, 236), width=2)
    d.rectangle([24, 220, SW - 24, 290], fill=NAVY)
    d.text((48, 255), 'Payment Status', font=font(30, 'bold'), fill='white', anchor='lm')
    paid = 30000 + 78500 * paid_k
    bal = 108500 - paid
    for i, (label, val, col) in enumerate((('Total', 108500, (20, 20, 20)), ('Paid', paid, GREEN),
                                           ('Balance', bal, RED if bal > 1 else GREEN))):
        cx = 24 + (SW - 48) * (i + 0.5) / 3
        d.text((cx, 340), label, font=font(30, 'regular'), fill=GREY, anchor='mm')
        rich_text(d, (cx, 396), _inr(val), 40, 'bold', col, 'mm')
    d.rounded_rectangle([48, 450, SW - 48, 470], radius=10, fill=(233, 236, 239))
    d.rounded_rectangle([48, 450, 48 + (SW - 96) * paid / 108500, 470], radius=10, fill=GREEN)
    if paid_k >= 1:
        d.rounded_rectangle([48, 500, SW - 48, 570], radius=12, fill=(209, 231, 221))
        d.text((SW / 2, 535), 'Fully paid — Thank you!', font=font(34, 'bold'), fill=(15, 81, 50), anchor='mm')
    rows = [('15 Oct 2026', '₹78,500', 'Razorpay Auto'), ('20 Sep 2026', '₹30,000', 'demo-admin')]
    y = 600
    for i, (when, amt, who) in enumerate(rows):
        if i == 0 and paid_k <= 0:
            continue
        d.text((48, y), when, font=font(30, 'regular'), fill=GREY, anchor='lm')
        rich_text(d, (290, y), amt, 32, 'bold', GREEN, 'lm')
        d.rounded_rectangle([470, y - 24, 702, y + 24], radius=12, fill=GREEN if i == 0 else GREY)
        d.text((586, y), who, font=font(24, 'bold'), fill='white', anchor='mm')
        y += 70
    return s


def _inr(v):
    v = int(round(v))
    s = str(v)
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:]); head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ','.join(parts) + ',' + tail
    return '₹' + s


# ── scenes ──

def scene_hook(t):
    img = BG.copy()
    heading(img, 'SOUND FAMILIAR?', 'Chasing payments?', 'Calling the same customers, again and again.', t)
    put_phone(img, call_log(t), t, 'up')
    chip(img, '₹2.6 lakh stuck with customers', t, 2.2, bg=(220, 53, 69), fg='white')
    return img


def scene_balances(t):
    img = BG.copy()
    heading(img, 'STEP 1', 'See who owes what.', 'Every balance due, biggest first.', t)
    put_phone(img, balances_screen(t), t, 'right')
    caption(img, 'Tap Remind.', t, 1.9)
    return img


def scene_remind(t):
    img = BG.copy()
    heading(img, 'STEP 2', 'One polite reminder.', 'Amount due, UPI and a payment link.', t)
    put_phone(img, reminder_chat(t), t, 'up')
    chip(img, 'Sent on WhatsApp  ✓✓', t, 2.4, bg=(37, 211, 102), fg=(8, 40, 20))
    caption(img, 'No awkward calls.', t, 3.0)
    return img


def scene_paid(t):
    img = BG.copy()
    heading(img, 'STEP 3', 'Paid. Recorded.', 'Online payments update the balance by themselves.', t)
    put_phone(img, paid_screen(t), t, 'right')
    chip(img, '₹78,500 received  ✓', t, 1.7)
    return img


def scene_end(t):
    img = BG.copy()
    d = ImageDraw.Draw(img)
    k = back_out(t / 0.5)
    size = max(10, int(220 * min(k, 1.05)))
    img.alpha_composite(LOGO.resize((size, size)), ((W - size) // 2, 520 - size // 2))
    a = phase(t, 0.3, 0.7)
    col = lambda c: tuple(int(v * a + 14 * (1 - a)) for v in c)
    d.text((W / 2, 780), 'Stop chasing.', font=font(96), fill=col(PAPER), anchor='mm')
    d.text((W / 2, 900), 'Start collecting.', font=font(96), fill=col(TAPE), anchor='mm')
    if t > 0.9:
        b = phase(t, 0.9, 1.3)
        d.text((W / 2, 1030), 'Quotes, invoices and payments in one app.', font=font(40, 'demi'),
               fill=tuple(int(v * b + 14 * (1 - b)) for v in MUTED), anchor='mm')
    if t > 1.5:
        kk = back_out((t - 1.5) / 0.4)
        rich_pill(img, 'Start your free 7-day trial', W / 2, 1230, max(20, int(50 * min(kk, 1.05))))
    if t > 1.9:
        d.text((W / 2, 1370), 'No payment to start  ·  quote-room.co.in', font=font(34, 'demi'), fill=MUTED, anchor='mm')
    return img


SCENES = [(scene_hook, 4.0), (scene_balances, 4.2), (scene_remind, 4.6), (scene_paid, 4.0), (scene_end, 4.4)]
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
    music = make_music(TOTAL + 0.5, os.path.join(OUT, 'music-payments.wav'))
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
        times = [STARTS[0] + 3.0, STARTS[1] + 2.4, STARTS[2] + 3.6, STARTS[3] + 2.6, STARTS[4] + 2.4]
        sheet = Image.new('RGB', (370 * len(times), 640), 'white')
        for i, T in enumerate(times):
            sheet.paste(frame_at(T).resize((360, 640)), (i * 370, 0))
        sheet.save(os.path.join(OUT, 'reel-payments-frames.png'))
        print('stills done')
    else:
        render(os.path.join(OUT, 'reel-payments-9x16.mp4'))
