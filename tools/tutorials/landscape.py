"""Landscape (1920x1080) videos of the app on a LAPTOP, for YouTube and for sending to leads.

Recorded like the phone tutorials (recorder.Recorder), but in a desktop browser window; shots taken on a phone
(e.g. the customer opening the link) are shown in a phone mockup beside the caption. Each shot is placed by its
shape: wide screenshots go in the laptop, tall ones in the phone.
"""
import json
import os
import subprocess

from PIL import Image, ImageDraw

import recorder as R
from recorder import FFMPEG, FPS, Recorder, _wrap
from static_ads import MUTED, PAPER, TAPE, background, brand, font, phone, rounded_mask, shadowed
from music import make_music

LW, LH = 1920, 1080
DESK = {'width': 1024, 'height': 640}       # browser window size (small, so text reads well in the video)
DESK_DPR = 1.5
SCREEN_W, SCREEN_TOP = 1360, 196             # laptop screen on the frame


class DeskRecorder(Recorder):
    """Recorder for a desktop browser window (taps are stored in screenshot pixels, like the phone ones)."""
    def _centre(self, locator):
        box = locator.bounding_box()
        return ((box['x'] + box['width'] / 2) * DESK_DPR, (box['y'] + box['height'] / 2) * DESK_DPR)

    def pdf(self, url, caption, page_no=0, hold=2.6):
        """Show the top of a PDF page across the screen, readable."""
        import fitz
        doc = fitz.open(stream=self.page.request.get(url).body(), filetype='pdf')
        sw, sh = int(DESK['width'] * DESK_DPR), int(DESK['height'] * DESK_DPR)
        pg = doc[page_no]
        k = (sw * 0.62) / pg.rect.width
        pix = pg.get_pixmap(matrix=fitz.Matrix(k, k))
        full = Image.frombytes('RGB', (pix.width, pix.height), pix.samples)
        canvas = Image.new('RGB', (sw, sh), (82, 86, 89))
        canvas.paste(full.crop((0, 0, full.width, min(full.height, sh - 40))), ((sw - full.width) // 2, 20))
        path = os.path.join(self.dir, f'{len(self.items):04d}-pdf.png')
        canvas.save(path)
        self.image(path, caption, hold)


def _laptop(screen):
    sh = int(SCREEN_W * screen.height / screen.width)
    bez = 18
    body = Image.new('RGBA', (SCREEN_W + 2 * bez, sh + 2 * bez), (0, 0, 0, 0))
    d = ImageDraw.Draw(body)
    d.rounded_rectangle([0, 0, body.width - 1, body.height - 1], radius=26, fill=(12, 20, 17, 255))
    d.rounded_rectangle([2, 2, body.width - 3, body.height - 3], radius=26, outline=(70, 92, 84, 255), width=3)
    body.paste(screen.resize((SCREEN_W, sh), Image.LANCZOS), (bez, bez), rounded_mask((SCREEN_W, sh), 8))
    return body, bez, SCREEN_W / screen.width


def _ripple(img, cx, cy, tap_t):
    r = 22 + 40 * min(1.0, tap_t / 0.6)
    alpha = int(220 * (1 - min(1.0, tap_t / 0.9)))
    layer = Image.new('RGBA', img.size, (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    ld.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(242, 183, 5, alpha), width=7)
    ld.ellipse([cx - 18, cy - 18, cx + 18, cy + 18], fill=(242, 183, 5, min(200, alpha)))
    img.alpha_composite(layer)


def frame(bg, screen, label, caption, tap, tap_t):
    img = bg.copy()
    d = ImageDraw.Draw(img)
    if screen.width >= screen.height:                       # laptop: caption across the top
        brand(img, 60, 44, 30)
        d.text((LW - 60, 72), label, font=font(28, 'bold'), fill=TAPE, anchor='rm')
        d.text((LW / 2, 140), caption, font=font(R._fit(caption, 46, 'demi', LW - 160), 'demi'), fill=PAPER, anchor='mm')
        lap, bez, k = _laptop(screen)
        x0 = (LW - lap.width) // 2
        sh, pad = shadowed(lap, 26, blur=24, alpha=150, pad=40)
        img.alpha_composite(sh, (x0 - pad, SCREEN_TOP - bez - pad))
        if tap is not None and tap_t is not None and tap_t < 0.9:
            _ripple(img, x0 + bez + tap[0] * k, SCREEN_TOP + tap[1] * k, tap_t)
    else:                                                    # phone: caption on the left, phone on the right
        brand(img, 60, 44, 30)
        d.text((LW - 60, 72), label, font=font(28, 'bold'), fill=TAPE, anchor='rm')
        y = 430
        for line in _wrap(caption, 58, 'heavy', 820)[:4]:
            d.text((120, y), line, font=font(58, 'heavy'), fill=PAPER)
            y += 76
        width = 440
        ph, pad = phone(screen, width)
        x0, top = 1180, 150
        img.alpha_composite(ph, (x0 - pad, top - pad))
        if tap is not None and tap_t is not None and tap_t < 0.9:
            bezel = int(width * 0.03)
            k = (width - 2 * bezel) / screen.width
            _ripple(img, x0 + bezel + tap[0] * k, top + bezel + tap[1] * k, tap_t)
    return img


def title_card(label, title, subtitle, t):
    img = background(LW, LH)
    d = ImageDraw.Draw(img)
    brand(img, 60, 44, 30)
    a = min(1.0, t / 0.5)
    col = lambda c: tuple(int(v * a + 14 * (1 - a)) for v in c)
    d.text((LW / 2, 380), label.upper(), font=font(36, 'bold'), fill=col(TAPE), anchor='mm')
    d.text((LW / 2, 480), title, font=font(96), fill=col(PAPER), anchor='mm')
    d.text((LW / 2, 590), subtitle, font=font(R._fit(subtitle, 44, 'demi', LW - 200), 'demi'), fill=col(MUTED), anchor='mm')
    return img


def end_card(text, t):
    img = background(LW, LH)
    d = ImageDraw.Draw(img)
    brand(img, 60, 44, 30)
    a = min(1.0, t / 0.5)
    d.text((LW / 2, 480), text, font=font(R._fit(text, 84, 'heavy', LW - 200)), fill=tuple(int(v * a + 14 * (1 - a)) for v in PAPER),
           anchor='mm')
    d.text((LW / 2, 620), 'Questions? Message us on WhatsApp anytime.', font=font(40, 'demi'), fill=MUTED, anchor='mm')
    return img


def render(workdir, path, subtitle, outro, style='pop'):
    tl = json.load(open(os.path.join(workdir, 'timeline.json')))
    bg = background(LW, LH).convert('RGBA')
    segments = [('title', None, 2.6)] + [('shot', it, it['hold']) for it in tl['items']] + [('end', None, 3.0)]
    total = sum(s[2] for s in segments)
    music = make_music(total + 0.5, os.path.join(R.OUT, 'music-tutorial.wav'), style=style)
    cmd = [FFMPEG, '-y', '-loglevel', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{LW}x{LH}', '-r', str(FPS),
           '-i', '-', '-i', music, '-filter_complex', '[1:a]volume=0.55,loudnorm=I=-20:TP=-2,aresample=48000[a]',
           '-map', '0:v', '-map', '[a]', '-c:v', 'libx264', '-preset', 'medium', '-crf', '18', '-pix_fmt', 'yuv420p',
           '-c:a', 'aac', '-b:a', '128k', '-shortest', '-movflags', '+faststart', path]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    cache = {}
    for kind, it, secs in segments:
        for f in range(max(1, round(secs * FPS))):
            t = f / FPS
            if kind == 'title':
                img = title_card(tl['chapter'], tl['title'], subtitle, t)
            elif kind == 'end':
                img = end_card(outro, t)
            else:
                if it['png'] not in cache:
                    cache.clear()
                    cache[it['png']] = Image.open(it['png']).convert('RGB')
                img = frame(bg, cache[it['png']], tl['chapter'], it['caption'], it['tap'], t if it['tap'] else None)
            proc.stdin.write(img.convert('RGB').tobytes())
    proc.stdin.close()
    proc.wait()
    print('wrote', path, f'({total:.0f}s)')
