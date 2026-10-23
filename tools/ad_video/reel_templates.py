"""Reel 'Starting quotations': still typing every quotation from scratch? → pick your usual quotation → everything
filled in → type the sizes → total → PDF → free trial. The app is shown on a LAPTOP (with a close-up below it, so it
reads on a phone), from the screens recorded for the tutorial (tools/tutorials/template_walkthrough.py).

    python tools/ad_video/reel_templates.py <tutorial workdir>          → ad-videos/reel-templates-9x16.mp4 and -4x5.mp4
    python tools/ad_video/reel_templates.py <tutorial workdir> stills   → ad-videos/reel-templates-frames.png
"""
import json
import math
import os
import subprocess
import sys

import imageio_ffmpeg
from PIL import Image, ImageDraw

from carousel_lost_jobs import rich_pill
from music import make_music
from reel_tape_to_invoice import LOGO, back_out, ease, phase, to_4x5
from static_ads import MUTED, OUT, PAPER, TAPE, background, brand, font, rounded_mask, shadowed

W, H, FPS = 1080, 1920, 30
BG = background(W, H)
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
LAP_SCREEN_W, LAP_TOP = 940, 470             # laptop screen width and top on the frame
ZOOM_TOP, ZOOM_W, ZOOM_H = 1140, 1000, 600   # the close-up under the laptop


def part(box, fx0, fy0, fx1, fy1):
    """A part of a box (fractions of its width and height): what the close-up shows."""
    x0, y0, x1, y1 = box
    return (x0 + (x1 - x0) * fx0, y0 + (y1 - y0) * fy0, x0 + (x1 - x0) * fx1, y0 + (y1 - y0) * fy1)


def load(workdir):
    tl = json.load(open(os.path.join(workdir, 'templates', 'timeline.json')))
    items = tl['items']
    by_cap = lambda text: [it for it in items if (it.get('caption') or '').startswith(text)]
    box = lambda title: next(it['box'] for it in items if it.get('title') == title)
    img = lambda it: Image.open(it['png']).convert('RGB')
    pick = by_cap('Pick "2 BHK turnkey"')
    sizes = by_cap('…or the size.')
    return {
        'blank': img(by_cap('New Quotation.')[0]),
        'pick': img(pick[0]), 'pick_tap': pick[0]['tap'],
        'filled': img(next(it for it in items if it.get('title') == 'Every line is ready')),   # the lines on screen
        'sizes': [img(it) for it in sizes[::2]] + [img(sizes[-1])],
        'size_done': img(next(it for it in items if it.get('title') == 'Size in, amount out')),   # TV Unit, typed
        'saved': img(next(it for it in items if it.get('title') == 'A total for every section')),
        'pdf': img(by_cap('The PDF your customer gets.')[0]),
        'box_start': part(box('Your starting quotations'), 0, 0, 0.42, 1),          # the title and the buttons
        'box_filled': part(box('Every line is ready'), 0, 0.1, 1, 0.5),              # the first lines
        'box_size': box('Size in, amount out'), 'box_total': box('A total for every section'),
    }


def laptop(screen):
    """The screen in a laptop: lid with a thin bezel, and the keyboard deck below."""
    k = LAP_SCREEN_W / screen.width
    sh = int(screen.height * k)
    bez = 16
    lid = Image.new('RGBA', (LAP_SCREEN_W + 2 * bez, sh + 2 * bez + 10), (0, 0, 0, 0))
    d = ImageDraw.Draw(lid)
    d.rounded_rectangle([0, 0, lid.width - 1, lid.height - 1], radius=22, fill=(12, 20, 17, 255))
    d.rounded_rectangle([2, 2, lid.width - 3, lid.height - 3], radius=22, outline=(70, 92, 84, 255), width=3)
    lid.paste(screen.resize((LAP_SCREEN_W, sh), Image.LANCZOS), (bez, bez), rounded_mask((LAP_SCREEN_W, sh), 6))
    deck_w = lid.width + 80
    body = Image.new('RGBA', (deck_w, lid.height + 30), (0, 0, 0, 0))
    body.alpha_composite(lid, (40, 0))
    d = ImageDraw.Draw(body)
    d.polygon([(0, lid.height + 4), (deck_w, lid.height + 4), (deck_w - 30, lid.height + 28), (30, lid.height + 28)],
              fill=(150, 165, 158, 255))
    d.rounded_rectangle([deck_w / 2 - 70, lid.height + 4, deck_w / 2 + 70, lid.height + 12], radius=4,
                        fill=(110, 125, 118, 255))
    return body, 40 + bez, bez, k


def put_laptop(img, screen, tap=None, tap_t=None, rise=1.0):
    body, sx, sy, k = laptop(screen)
    x0 = (W - body.width) // 2
    y0 = LAP_TOP + int(60 * (1 - rise))
    sh_img, pad = shadowed(body, 24, blur=26, alpha=160, pad=40)
    img.alpha_composite(sh_img, (x0 - pad, y0 - pad))
    if tap is not None and tap_t is not None and tap_t < 0.9:
        cx, cy = x0 + sx + tap[0] * k, y0 + sy + tap[1] * k
        r = 16 + 30 * min(1.0, tap_t / 0.6)
        alpha = int(230 * (1 - min(1.0, tap_t / 0.9)))
        layer = Image.new('RGBA', img.size, (0, 0, 0, 0))
        ld = ImageDraw.Draw(layer)
        ld.ellipse([cx - r, cy - r, cx + r, cy + r], outline=TAPE + (alpha,), width=6)
        ld.ellipse([cx - 12, cy - 12, cx + 12, cy + 12], fill=TAPE + (min(210, alpha),))
        img.alpha_composite(layer)


def zoom(img, screen, box, t, start=0.35, pad=10):
    """A magnified close-up of `box` (screenshot pixels) under the laptop, popping in."""
    a = phase(t, start, start + 0.4)
    if a <= 0:
        return
    x0, y0, x1, y1 = box
    crop = screen.crop((max(0, int(x0 - pad)), max(0, int(y0 - pad)), min(screen.width, int(x1 + pad)),
                        min(screen.height, int(y1 + pad))))
    k = min(ZOOM_W / crop.width, ZOOM_H / crop.height)
    crop = crop.resize((int(crop.width * k), int(crop.height * k)), Image.LANCZOS)
    card = Image.new('RGBA', (crop.width + 12, crop.height + 12), TAPE + (255,))
    card.paste(crop, (6, 6))
    card = card.resize((max(1, int(card.width * (0.9 + 0.1 * a))), max(1, int(card.height * (0.9 + 0.1 * a)))))
    sh_img, p = shadowed(card, 18, blur=22, alpha=int(170 * a), pad=36)
    if a < 1:
        sh_img.putalpha(sh_img.getchannel('A').point(lambda v: int(v * a)))
    img.alpha_composite(sh_img, ((W - card.width) // 2 - p, ZOOM_TOP + (ZOOM_H - card.height) // 2 - p + int(30 * (1 - a))))


def heading(img, title, sub, t, accent=None):
    d = ImageDraw.Draw(img)
    brand(img, 60, 110, 46)
    a = phase(t, 0.0, 0.35)
    shift = int(30 * (1 - a))
    col = lambda c: tuple(int(v * a + 14 * (1 - a)) for v in c)
    size = 76
    while font(size).getlength(title) > W - 120 and size > 40:
        size -= 2
    d.text((60, 250 + shift), title, font=font(size), fill=col(accent or PAPER))
    if sub:
        d.text((60, 250 + size + 26 + shift), sub, font=font(40, 'demi'), fill=col(MUTED))


# ── scenes ──

def scenes(S):
    def hook(t):
        img = BG.copy()
        d = ImageDraw.Draw(img)
        brand(img, 60, 110, 46)
        a = phase(t, 0.0, 0.4)
        col = lambda c: tuple(int(v * a + 14 * (1 - a)) for v in c)
        d.text((60, 250), 'Still typing every', font=font(78), fill=col(PAPER))
        d.text((60, 345), 'quotation from scratch?', font=font(78), fill=col(TAPE))
        put_laptop(img, S['blank'], rise=ease(t / 0.6))
        b = phase(t, 0.9, 1.3)
        if b > 0:
            colb = lambda c: tuple(int(v * b + 14 * (1 - b)) for v in c)
            d.text((W / 2, 1300), 'Every room. Every item.', font=font(58), fill=colb(PAPER), anchor='mm')
            d.text((W / 2, 1385), 'Every rate. Every time.', font=font(58), fill=colb(PAPER), anchor='mm')
            d.text((W / 2, 1520), 'There\'s a faster way.', font=font(44, 'demi'), fill=colb(TAPE), anchor='mm')
        return img

    def pick(t):
        img = BG.copy()
        heading(img, 'Start from your usual quotation', '1 BHK, 2 BHK, turnkey… set up once', t)
        put_laptop(img, S['pick'], S['pick_tap'], t - 1.4 if t >= 1.4 else None)
        zoom(img, S['pick'], S['box_start'], t)
        return img

    def filled(t):
        img = BG.copy()
        heading(img, 'Every item and rate, filled in', 'From your own list, with descriptions', t)
        put_laptop(img, S['filled'])
        zoom(img, S['filled'], S['box_filled'], t)
        return img

    def sizes(t):
        img = BG.copy()
        heading(img, 'Just type the sizes', 'Amounts work themselves out', t)
        frames = S['sizes']
        i = min(len(frames) - 1, int(t / 3.4 * len(frames)))
        put_laptop(img, frames[i])
        zoom(img, S['size_done'], S['box_size'], t, start=0.6)
        return img

    def total(t):
        img = BG.copy()
        heading(img, 'Your total, section by section', 'Lines you didn\'t need: removed', t)
        put_laptop(img, S['saved'])
        zoom(img, S['saved'], S['box_total'], t)
        return img

    def pdf(t):
        img = BG.copy()
        heading(img, 'A clean PDF, ready to send', 'Or a link they accept online', t)
        put_laptop(img, S['pdf'])
        w, h = S['pdf'].size
        zoom(img, S['pdf'], (w * 0.2, h * 0.30, w * 0.8, h * 0.66), t)          # its lines
        return img

    def end(t):
        img = BG.copy()
        d = ImageDraw.Draw(img)
        k = back_out(t / 0.5)
        size = max(10, int(240 * min(k, 1.05)))
        img.alpha_composite(LOGO.resize((size, size)), ((W - size) // 2, 560 - size // 2))
        a = phase(t, 0.3, 0.7)
        col = lambda c: tuple(int(v * a + 14 * (1 - a)) for v in c)
        d.text((W / 2, 820), 'Quotations in minutes,', font=font(78), fill=col(PAPER), anchor='mm')
        d.text((W / 2, 915), 'not hours.', font=font(78), fill=col(TAPE), anchor='mm')
        d.text((W / 2, 1040), 'Send us your old quotations: we set them up.', font=font(38, 'demi'), fill=col(MUTED),
               anchor='mm')
        if t > 0.9:
            kk = back_out((t - 0.9) / 0.4)
            rich_pill(img, 'Start your free 7-day trial', W / 2, 1250, max(20, int(50 * min(kk, 1.05))))
        if t > 1.3:
            d.text((W / 2, 1390), 'No payment to start  ·  quote-room.co.in', font=font(34, 'demi'), fill=MUTED, anchor='mm')
        return img

    return [(hook, 2.6), (pick, 3.0), (filled, 3.0), (sizes, 3.6), (total, 3.0), (pdf, 2.6), (end, 4.4)]


XFADE = 0.25


def make_frame_at(SC):
    starts, acc = [], 0.0
    for _, dur in SC:
        starts.append(acc)
        acc += dur

    def frame_at(T):
        for i, ((fn, dur), start) in enumerate(zip(SC, starts)):
            if T < start + dur or i == len(SC) - 1:
                img = fn(T - start)
                if i + 1 < len(SC) and T > start + dur - XFADE:
                    nxt = SC[i + 1][0](0.0)
                    img = Image.blend(img.convert('RGB'), nxt.convert('RGB'), (T - (start + dur - XFADE)) / XFADE)
                return img.convert('RGB')
    return frame_at, acc, starts


def render(frame_at, total, path, fmt):
    size = (1080, 1920) if fmt == '9x16' else (1080, 1350)
    music = make_music(total + 0.5, os.path.join(OUT, 'music-reel.wav'))
    cmd = [FFMPEG, '-y', '-loglevel', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{size[0]}x{size[1]}',
           '-r', str(FPS), '-i', '-', '-i', music,
           '-filter_complex', '[1:a]volume=0.9,loudnorm=I=-16:TP=-1.5,aresample=48000[a]',
           '-map', '0:v', '-map', '[a]', '-c:v', 'libx264', '-preset', 'medium', '-crf', '17', '-pix_fmt', 'yuv420p',
           '-c:a', 'aac', '-b:a', '160k', '-shortest', '-movflags', '+faststart', path]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for k in range(int(math.ceil(total * FPS))):
        img = frame_at(k / FPS)
        proc.stdin.write((img if fmt == '9x16' else to_4x5(img)).tobytes())
    proc.stdin.close()
    proc.wait()
    print('wrote', path)


if __name__ == '__main__':
    os.makedirs(OUT, exist_ok=True)
    frame_at, total, starts = make_frame_at(scenes(load(sys.argv[1])))
    if len(sys.argv) > 2 and sys.argv[2] == 'stills':
        times = [s + 2.0 for s in starts]
        sheet = Image.new('RGB', (370 * len(times), 640), 'white')
        for i, T in enumerate(times):
            sheet.paste(frame_at(T).resize((360, 640)), (i * 370, 0))
        sheet.save(os.path.join(OUT, 'reel-templates-frames.png'))
        print('stills done')
    else:
        for fmt in ('9x16', '4x5'):
            render(frame_at, total, os.path.join(OUT, f'reel-templates-{fmt}.mp4'), fmt)
