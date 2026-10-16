"""Record app tutorials at phone size and turn them into captioned videos.

A tutorial script drives the real app with Playwright (a local copy with a fictional business), and calls:
    rec.shot(caption, hold)            a still moment
    rec.tap(locator, caption)          a tap, with a ripple where the finger goes
    rec.type(locator, text, caption)   typing, a few characters per frame
    rec.scroll_to(locator)             a smooth scroll
Each call saves screenshots + timing. render() composes 1080x1920 frames (title, caption, phone mockup, tap ripple)
and writes an mp4 with music.
"""
import json
import math
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'ad_video'))

import imageio_ffmpeg  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

from carousel_lost_jobs import rich_pill, rich_text, rich_width  # noqa: E402
from music import make_music  # noqa: E402
from static_ads import INK, MUTED, OUT, PAPER, TAPE, background, brand, font, phone  # noqa: E402

VIEW = {'width': 390, 'height': 844}
DPR = 2
W, H, FPS = 1080, 1920, 30
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
PHONE_W = 640
PHONE_TOP = 430


class Recorder:
    def __init__(self, page, workdir, chapter, title):
        self.page, self.dir = page, workdir
        self.chapter, self.title = chapter, title
        self.items = []                   # {'png', 'hold', 'caption', 'tap': (x, y) | None}
        os.makedirs(workdir, exist_ok=True)

    # ── capture ──
    PUBLIC = 'https://sharma.quote-room.co.in'     # what a real business's links look like

    def _mask_local(self):
        """The recording runs on a local copy; show the business's real web address in links and boxes instead."""
        self.page.evaluate("""pub => {
            const re = /https?:\\/\\/(localhost|127\\.0\\.0\\.1):\\d+/g;
            document.querySelectorAll('input, textarea').forEach(el => { if (re.test(el.value)) el.value = el.value.replace(re, pub); });
            const walk = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
            while (walk.nextNode()) { const n = walk.currentNode; if (re.test(n.nodeValue)) n.nodeValue = n.nodeValue.replace(re, pub); }
        }""", self.PUBLIC)

    def _snap(self, caption, hold, tap=None):
        self._mask_local()
        path = os.path.join(self.dir, f'{len(self.items):04d}.png')
        self.page.screenshot(path=path)
        self.items.append({'png': path, 'hold': hold, 'caption': caption, 'tap': tap})

    def shot(self, caption, hold=1.6):
        self.page.wait_for_timeout(250)
        self._snap(caption, hold)

    def _centre(self, locator):
        box = locator.bounding_box()
        return ((box['x'] + box['width'] / 2) * DPR, (box['y'] + box['height'] / 2) * DPR)

    def tap(self, locator, caption, hold=0.9, after_hold=1.2, wait=500):
        locator.scroll_into_view_if_needed()
        self.page.wait_for_timeout(150)
        self._snap(caption, hold, tap=self._centre(locator))      # the moment before the tap, with the ripple
        locator.click()
        self.page.wait_for_timeout(wait)
        self._snap(caption, after_hold)

    def type(self, locator, text, caption, per_frame=2, frame_time=0.09, hold=0.8):
        locator.scroll_into_view_if_needed()
        self._snap(caption, 0.5, tap=self._centre(locator))
        locator.click()
        locator.fill('')
        for i in range(per_frame, len(text) + per_frame, per_frame):
            locator.fill(text[:i])
            self._snap(caption, frame_time)
        self.items[-1]['hold'] = hold

    def scroll_to(self, locator, caption, offset=180, steps=6):
        # leave any text/number box first: the wheel would otherwise change a focused number (e.g. 5% → 4.94%)
        self.page.evaluate('document.activeElement && document.activeElement.blur()')
        box = locator.bounding_box()
        if not box:
            return
        delta = box['y'] - offset
        for _ in range(steps):
            self.page.mouse.wheel(0, delta / steps)
            self.page.wait_for_timeout(60)
            self._snap(caption, 0.06)

    def image(self, png, caption, hold=2.2):
        """Show a prepared image (e.g. a PDF page) in the phone, same size as a screenshot."""
        self.items.append({'png': png, 'hold': hold, 'caption': caption, 'tap': None})

    def pdf(self, url, caption, pages=((0, 0.0),), hold=2.4):
        """Fetch a PDF with the logged-in session and show its pages (page index, scroll fraction) in the phone."""
        import fitz
        data = self.page.request.get(url).body()
        doc = fitz.open(stream=data, filetype='pdf')
        sw, sh = VIEW['width'] * DPR, VIEW['height'] * DPR
        for i, (pg, frac) in enumerate(pages):
            pix = doc[pg].get_pixmap(matrix=fitz.Matrix(sw / doc[pg].rect.width, sw / doc[pg].rect.width))
            full = Image.frombytes('RGB', (pix.width, pix.height), pix.samples)
            top = int((full.height - sh) * frac) if full.height > sh else 0
            canvas = Image.new('RGB', (sw, sh), (82, 86, 89))
            canvas.paste(full.crop((0, top, sw, min(full.height, top + sh))), (0, 0))
            path = os.path.join(self.dir, f'{len(self.items):04d}-pdf.png')
            canvas.save(path)
            self.image(path, caption, hold)

    def save(self):
        with open(os.path.join(self.dir, 'timeline.json'), 'w') as f:
            json.dump({'chapter': self.chapter, 'title': self.title, 'items': self.items}, f, indent=1)


# ── render ──

def _frame(bg, screen, chapter, title, caption, tap, tap_t):
    img = bg.copy()
    d = ImageDraw.Draw(img)
    brand(img, 60, 70, 40)
    d.text((W - 60, 104), f'Part {chapter}', font=font(30, 'bold'), fill=TAPE, anchor='rm')
    d.text((60, 180), title, font=font(_fit(title, 64, 'heavy', W - 120)), fill=PAPER)
    # caption box
    lines = _wrap(caption, 40, 'demi', W - 160)
    y = 290
    for line in lines[:2]:
        rich_text(d, (60, y), line, 40, 'demi', MUTED if False else (230, 236, 233), 'lt')
        y += 52
    ph, pad = phone(screen, PHONE_W)
    x0 = (W - (ph.width - 2 * pad)) // 2 - pad
    img.alpha_composite(ph, (x0, PHONE_TOP - pad))
    if tap is not None and tap_t is not None and tap_t < 0.9:
        bezel = int(PHONE_W * 0.03)
        k = (PHONE_W - 2 * bezel) / screen.width
        cx = x0 + pad + bezel + tap[0] * k
        cy = PHONE_TOP + bezel + tap[1] * k
        r = 26 + 46 * min(1.0, tap_t / 0.6)
        alpha = int(220 * (1 - min(1.0, tap_t / 0.9)))
        layer = Image.new('RGBA', img.size, (0, 0, 0, 0))
        ld = ImageDraw.Draw(layer)
        ld.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(242, 183, 5, alpha), width=8)
        ld.ellipse([cx - 22, cy - 22, cx + 22, cy + 22], fill=(242, 183, 5, min(200, alpha)))
        img.alpha_composite(layer)
    return img


def _fit(text, size, weight, width):
    while size > 24 and font(size, weight).getlength(text) > width:
        size -= 2
    return size


def _wrap(text, size, weight, width):
    words, lines, line = text.split(), [], ''
    for w in words:
        trial = f'{line} {w}'.strip()
        if rich_width(trial, size, weight) <= width:
            line = trial
        else:
            lines.append(line)
            line = w
    lines.append(line)
    return lines


def title_card(chapter, title, subtitle, t):
    img = background(W, H)
    d = ImageDraw.Draw(img)
    brand(img, 60, 70, 40)
    a = min(1.0, t / 0.5)
    col = lambda c: tuple(int(v * a + 14 * (1 - a)) for v in c)
    d.text((W / 2, 760), f'PART {chapter}', font=font(40, 'bold'), fill=col(TAPE), anchor='mm')
    d.text((W / 2, 870), title, font=font(_fit(title, 90, 'heavy', W - 120)), fill=col(PAPER), anchor='mm')
    for i, line in enumerate(_wrap(subtitle, 42, 'demi', W - 200)):
        d.text((W / 2, 980 + i * 56), line, font=font(42, 'demi'), fill=col(MUTED), anchor='mm')
    return img


def end_card(text, t):
    img = background(W, H)
    d = ImageDraw.Draw(img)
    brand(img, 60, 70, 40)
    a = min(1.0, t / 0.5)
    for i, line in enumerate(_wrap(text, 70, 'heavy', W - 160)):
        d.text((W / 2, 840 + i * 86), line, font=font(70), fill=tuple(int(v * a + 14 * (1 - a)) for v in PAPER), anchor='mm')
    d.text((W / 2, 1180), 'Questions? Message us on WhatsApp anytime.', font=font(38, 'demi'), fill=MUTED, anchor='mm')
    return img


def render(timelines, path, subtitle_for, outro, style='lofi'):
    """timelines: list of workdirs (one per part). Writes one mp4."""
    bg = background(W, H)
    segments = []                                     # (kind, data, seconds)
    for wd in timelines:
        tl = json.load(open(os.path.join(wd, 'timeline.json')))
        segments.append(('title', tl, 2.6))
        for it in tl['items']:
            segments.append(('shot', (tl, it), it['hold']))
    segments.append(('end', None, 3.0))
    total = sum(s[2] for s in segments)
    music = make_music(total + 0.5, os.path.join(OUT, 'music-tutorial.wav'), style=style)
    cmd = [FFMPEG, '-y', '-loglevel', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{W}x{H}', '-r', str(FPS),
           '-i', '-', '-i', music, '-filter_complex', '[1:a]volume=0.55,loudnorm=I=-20:TP=-2,aresample=48000[a]',
           '-map', '0:v', '-map', '[a]', '-c:v', 'libx264', '-preset', 'medium', '-crf', '18', '-pix_fmt', 'yuv420p',
           '-c:a', 'aac', '-b:a', '128k', '-shortest', '-movflags', '+faststart', path]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    cache = {}
    for kind, data, secs in segments:
        n = max(1, round(secs * FPS))
        for f in range(n):
            t = f / FPS
            if kind == 'title':
                img = title_card(data['chapter'], data['title'], subtitle_for(data['chapter']), t)
            elif kind == 'end':
                img = end_card(outro, t)
            else:
                tl, it = data
                if it['png'] not in cache:
                    cache.clear()
                    cache[it['png']] = Image.open(it['png']).convert('RGB')
                img = _frame(bg, cache[it['png']], tl['chapter'], tl['title'], it['caption'],
                             it['tap'], t if it['tap'] else None)
            proc.stdin.write(img.convert('RGB').tobytes())
    proc.stdin.close()
    proc.wait()
    print('wrote', path, f'({total:.0f}s)')
