"""Reel 'From tape measure to GST invoice': measure → price → send → accept → invoice → free trial.

    python tools/ad_video/reel_tape_to_invoice.py          → ad-videos/reel-tape-to-invoice-9x16.mp4 and -4x5.mp4
    python tools/ad_video/reel_tape_to_invoice.py stills   → ad-videos/reel-tape-to-invoice-frames.png
"""
import math
import os
import subprocess
import sys

import imageio_ffmpeg
from PIL import Image, ImageDraw

import tape_opener as opener
from carousel_lost_jobs import rich_pill, rich_text
from music import make_music
from static_ads import ADS, INK, MUTED, OUT, PAPER, PINE, TAPE, background, brand, card, font, phone

W, H, FPS = 1080, 1920, 30
BG = background(W, H)
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
PHONE_W, PHONE_TOP, CHIP_Y, CAPTION_Y = 540, 470, 1590, 1712

S_PAY = Image.open(f'{ADS}/04-room-totals-payments.jpg').convert('RGB')
S_APPROVAL = Image.open(f'{ADS}/07-approval-accepted.jpg').convert('RGB')
INVOICE = Image.open(f'{ADS}/08-gst-invoice-pdf.png').convert('RGB')
LOGO = Image.open(f'{ADS}/quoteroom-logo-512.png').convert('RGBA')
WA_BAR, WA_BG, WA_OUT, WA_TICK = (7, 94, 84), (236, 229, 221), (217, 253, 211), (52, 183, 241)


def ease(t):
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


def back_out(t):
    t = max(0.0, min(1.0, t))
    c = 1.7
    return 1 + (c + 1) * (t - 1) ** 3 + c * (t - 1) ** 2


def phase(t, a, b):
    return ease((t - a) / (b - a))


def heading(img, step, title, sub, t):
    d = ImageDraw.Draw(img)
    brand(img, 60, 110, 46)
    a = phase(t, 0.0, 0.35)
    shift = int(30 * (1 - a))
    col = lambda c: tuple(int(v * a + 14 * (1 - a)) for v in c)
    d.text((60, 230 + shift), step, font=font(34, 'bold'), fill=col(TAPE))
    d.text((60, 280 + shift), title, font=font(_fit(title, 84, 'heavy')), fill=col(PAPER))
    d.text((60, 390 + shift), sub, font=font(_fit(sub, 40, 'demi'), 'demi'), fill=col(MUTED))


def _fit(text, size, weight):
    """Largest size ≤ size at which the text fits the frame width (60 px margins)."""
    while size > 20 and font(size, weight).getlength(text) > W - 120:
        size -= 2
    return size


def put_phone(img, screen, t, slide_from=None):
    ph, pad = phone(screen, PHONE_W)
    x = (W - (ph.width - 2 * pad)) // 2 - pad
    y = PHONE_TOP - pad
    if slide_from == 'right':
        x += int((W - x) * (1 - ease(t / 0.45)))
    elif slide_from == 'up':
        y += int(900 * (1 - ease(t / 0.45)))
    img.alpha_composite(ph, (x, y))
    return x + pad, y + pad, ph.width - 2 * pad, ph.height - 2 * pad


def caption(img, text, t, start):
    a = phase(t, start, start + 0.35)
    if a <= 0:
        return
    d = ImageDraw.Draw(img)
    d.text((W / 2, CAPTION_Y), text, font=font(40, 'demi'), fill=tuple(int(v * a + 14 * (1 - a)) for v in PAPER),
           anchor='mm')


def chip(img, text, t, start, y=CHIP_Y, fg=INK, bg=TAPE):
    if t < start:
        return
    k = back_out((t - start) / 0.35)
    rich_pill(img, text, W / 2, y + int(40 * (1 - min(k, 1))), max(20, int(40 * min(k, 1.05))), fg=fg, bg=bg)


# ── scenes ──

def scene_measure(t):
    return opener.frame(t).convert('RGBA')


def scene_price(t):
    img = BG.copy()
    heading(img, 'STEP 2', 'Price it.', 'Your rates apply. The totals add up.', t)
    put_phone(img, S_PAY.crop((0, 0, 750, 1450)), t, 'right')
    chip(img, 'Kitchen total  ₹99,000', t, 1.3)
    caption(img, 'Every room, every material, worked out.', t, 1.8)
    return img


def chat_screen(t):
    """A WhatsApp-style chat (drawn): the PDF goes out, then the approval link, then blue ticks."""
    s = Image.new('RGB', (750, 1450), WA_BG)
    d = ImageDraw.Draw(s)
    d.rectangle([0, 0, 750, 150], fill=WA_BAR)
    d.ellipse([86, 40, 156, 110], fill=(200, 214, 208))
    d.text((121, 75), 'P', font=font(38, 'bold'), fill=WA_BAR, anchor='mm')
    d.text((180, 52), 'Priya Example', font=font(36, 'bold'), fill='white')
    d.text((180, 98), 'online', font=font(26, 'regular'), fill=(200, 230, 220))
    d.text((40, 75), '‹', font=font(60, 'bold'), fill='white', anchor='lm')
    ticks_blue = t > 2.6
    y = 220
    if t > 0.5:                                        # PDF bubble
        bx0, bx1 = 170, 715
        d.rounded_rectangle([bx0, y, bx1, y + 190], radius=22, fill=WA_OUT)
        d.rounded_rectangle([bx0 + 16, y + 16, bx1 - 16, y + 120], radius=14, fill=(245, 252, 243))
        d.rounded_rectangle([bx0 + 34, y + 34, bx0 + 94, y + 102], radius=8, fill=(226, 74, 63))
        d.text((bx0 + 64, y + 68), 'PDF', font=font(22, 'bold'), fill='white', anchor='mm')
        d.text((bx0 + 116, y + 44), 'Quotation_Priya_1.pdf', font=font(28, 'bold'), fill=(30, 40, 36))
        d.text((bx0 + 116, y + 82), '3 pages · PDF', font=font(24, 'regular'), fill=(100, 112, 106))
        _ticks(d, bx1 - 30, y + 160, ticks_blue)
        d.text((bx1 - 70, y + 160), '11:02', font=font(22, 'regular'), fill=(110, 120, 115), anchor='rm')
        y += 220
    if t > 1.3:                                        # message with the approval link
        bx0, bx1 = 120, 715
        lines = ['Hello Priya, here is your quotation', 'from Nest & Grain Interiors.', '',
                 'Tap to view and accept it online:', 'nestandgrain.quote-room.co.in/q/…']
        h = 40 + 44 * len(lines) + 40
        d.rounded_rectangle([bx0, y, bx1, y + h], radius=22, fill=WA_OUT)
        yy = y + 30
        for i, line in enumerate(lines):
            d.text((bx0 + 28, yy), line, font=font(28, 'regular' if i < 4 else 'demi'),
                   fill=(30, 40, 36) if i < 4 else (3, 120, 190))
            yy += 44
        _ticks(d, bx1 - 30, y + h - 30, ticks_blue)
        d.text((bx1 - 70, y + h - 30), '11:02', font=font(22, 'regular'), fill=(110, 120, 115), anchor='rm')
    d.rectangle([0, 1330, 750, 1450], fill=(240, 240, 240))
    d.rounded_rectangle([30, 1350, 620, 1430], radius=40, fill='white')
    d.text((70, 1390), 'Message', font=font(30, 'regular'), fill=(150, 150, 150), anchor='lm')
    d.ellipse([640, 1350, 720, 1430], fill=(0, 168, 132))
    return s


def _ticks(d, x, y, blue):
    col = WA_TICK if blue else (140, 150, 146)
    for dx in (0, 12):
        d.line([(x - 22 + dx, y), (x - 14 + dx, y + 8), (x + dx, y - 8)], fill=col, width=3)


def scene_send(t):
    img = BG.copy()
    heading(img, 'STEP 3', 'Send it.', 'On WhatsApp, in one tap.', t)
    put_phone(img, chat_screen(t), t, 'up')
    chip(img, 'Sent  ✓✓', t, 2.6, bg=(37, 211, 102), fg=(8, 40, 20))
    caption(img, 'With a link to accept it online.', t, 2.9)
    return img


def scene_accept(t):
    img = BG.copy()
    heading(img, 'STEP 4', 'They accept.', 'Online. No app, no login.', t)
    sx, sy, sw, sh = put_phone(img, S_APPROVAL.crop((0, 0, 750, 1450)), t, 'right')
    if t > 1.0:                                        # notification drops in over the phone
        k = ease((t - 1.0) / 0.4)
        n = Image.new('RGBA', (sw + 80, 150), (0, 0, 0, 0))
        nd = ImageDraw.Draw(n)
        nd.rounded_rectangle([0, 0, sw + 79, 149], radius=30, fill=(255, 255, 255, 250), outline=(220, 225, 222), width=2)
        n.alpha_composite(LOGO.resize((70, 70)), (24, 40))
        nd.text((112, 34), 'QuoteRoom · now', font=font(24, 'demi'), fill=(110, 120, 115))
        nd.text((112, 66), 'Quotation #1 accepted', font=font(32, 'bold'), fill=INK)
        nd.text((112, 106), 'Priya Example accepted online', font=font(26, 'demi'), fill=(70, 82, 77))
        img.alpha_composite(n, (sx - 40, int(sy - 170 + 230 * k)))
    if t > 2.2:                                        # the job's stage moves on
        d = ImageDraw.Draw(img)
        rich_pill(img, 'Awaiting confirmation', 330, CHIP_Y, 30, fg=(146, 64, 14), bg=(254, 243, 199))
        if t > 2.6:
            rich_text(d, (595, CHIP_Y), '→', 48, 'bold', TAPE, 'mm')
            rich_pill(img, 'Confirmed  ✓', 775, CHIP_Y, max(12, int(30 * min(1.05, back_out((t - 2.6) / 0.35)))),
                      fg=(30, 64, 175), bg=(219, 234, 254))
    caption(img, 'You get notified. The job moves to Confirmed.', t, 2.9)
    return img


def scene_invoice(t):
    img = BG.copy()
    heading(img, 'STEP 5', 'Invoice & get paid.', 'GST worked out. Numbered for you.', t)
    doc = INVOICE.crop((90, 90, INVOICE.width - 90, 1650))
    width = 760
    c, pad = card(doc, width, r=14)
    y = PHONE_TOP + int(900 * (1 - ease(t / 0.45)))
    img.alpha_composite(c, ((W - width) // 2 - pad, y - pad))
    chip(img, 'CGST 9% + SGST 9%', t, 1.2)
    if t > 2.4:
        chip(img, 'Payment reminder sent on WhatsApp  ✓', t, 2.4, y=CAPTION_Y, bg=(37, 211, 102), fg=(8, 40, 20))
    return img


def scene_end(t):
    img = BG.copy()
    d = ImageDraw.Draw(img)
    k = back_out(t / 0.5)
    size = max(10, int(260 * min(k, 1.05)))
    img.alpha_composite(LOGO.resize((size, size)), ((W - size) // 2, 470 - size // 2 + 130))
    a = phase(t, 0.3, 0.7)
    col = lambda c: tuple(int(v * a + 14 * (1 - a)) for v in c)
    d.text((W / 2, 820), 'From tape measure', font=font(78), fill=col(PAPER), anchor='mm')
    d.text((W / 2, 915), 'to GST invoice.', font=font(78), fill=col(TAPE), anchor='mm')
    d.text((W / 2, 1040), 'One app. One price for your whole team.', font=font(40, 'demi'), fill=col(MUTED), anchor='mm')
    if t > 0.9:
        kk = back_out((t - 0.9) / 0.4)
        rich_pill(img, 'Start your free 7-day trial', W / 2, 1250, max(20, int(50 * min(kk, 1.05))))
    if t > 1.3:
        d.text((W / 2, 1390), 'No payment to start  ·  quote-room.co.in', font=font(34, 'demi'), fill=MUTED, anchor='mm')
    return img


SCENES = [(scene_measure, 6.6), (scene_price, 4.0), (scene_send, 4.4), (scene_accept, 4.6), (scene_invoice, 4.2),
          (scene_end, 4.2)]
XFADE = 0.25
STARTS = []
_acc = 0.0
for _, dur in SCENES:
    STARTS.append(_acc)
    _acc += dur
TOTAL = _acc


def frame_at(T):
    for i, ((fn, dur), start) in enumerate(zip(SCENES, STARTS)):
        if T < start + dur or i == len(SCENES) - 1:
            img = fn(T - start)
            if i + 1 < len(SCENES) and T > start + dur - XFADE:       # cross-fade into the next scene
                nxt = SCENES[i + 1][0](0.0)
                img = Image.blend(img.convert('RGB'), nxt.convert('RGB'), (T - (start + dur - XFADE)) / XFADE)
            return img.convert('RGB')


def to_4x5(img):
    """The 9:16 frame scaled into a 4:5 canvas (same background, so the sides blend in)."""
    small = img.resize((int(W * 1350 / H), 1350), Image.LANCZOS)
    canvas = background(1080, 1350).convert('RGB')
    canvas.paste(small, ((1080 - small.width) // 2, 0))
    return canvas


def render(path, fmt):
    size = (1080, 1920) if fmt == '9x16' else (1080, 1350)
    music = make_music(TOTAL + 0.5, os.path.join(OUT, 'music-reel.wav'))
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
        times = [STARTS[1] + 2.4, STARTS[2] + 3.4, STARTS[3] + 3.4, STARTS[4] + 3.0, STARTS[5] + 2.0]
        sheet = Image.new('RGB', (370 * len(times), 640), 'white')
        for i, T in enumerate(times):
            sheet.paste(frame_at(T).resize((360, 640)), (i * 370, 0))
        sheet.save(os.path.join(OUT, 'reel-tape-to-invoice-frames.png'))
        print('stills done')
    else:
        for fmt in ('9x16', '4x5'):
            render(os.path.join(OUT, f'reel-tape-to-invoice-{fmt}.mp4'), fmt)
