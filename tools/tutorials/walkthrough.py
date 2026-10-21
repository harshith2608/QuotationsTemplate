"""Presentation-style laptop videos (1920x1080): the app recorded like landscape.py, plus pauses that explain.

On top of DeskRecorder's shot / tap / type / scroll_to:
    rec.slide(kicker, title, points)          a full-screen slide (section start, how pricing works, recap)
    rec.explain(locators, title, points)      the screen pauses: everything but the explained part is dimmed and
                                              outlined, and the points appear one by one beside it
Points can be plain text; hold times follow the amount of text, so there is time to read.
"""
import json
import os
import subprocess

from PIL import Image, ImageDraw

import recorder as R
from landscape import LH, LW, DeskRecorder, end_card, frame, title_card
from music import make_music
from recorder import FFMPEG, FPS, _wrap
from static_ads import MUTED, PAPER, TAPE, background, brand, font, rounded_mask, shadowed

READ_WPS = 2.6                    # words per second, comfortably readable with the screen to look at too


def _read_time(title, points, base=1.2, cap=3.0):
    """Short pauses (the owner asked for 2-3 seconds): a little longer for more text, never more than `cap`."""
    words = len(title.split()) + sum(len(p.split()) for p in points)
    return min(cap, max(2.2, base + words / 6))


WIN = {'width': 1280, 'height': 800}        # a common laptop size: the quotation's room tables fit without scrolling
WIN_DPR = 1.2                                 # same 1536x960 screenshots as landscape.DESK at 1.5


class WalkRecorder(DeskRecorder):
    def _centre(self, locator):
        box = locator.bounding_box()
        return ((box['x'] + box['width'] / 2) * WIN_DPR, (box['y'] + box['height'] / 2) * WIN_DPR)

    def slide(self, kicker, title, points=(), hold=None):
        if kicker.lower().startswith('step'):
            self.section = f'{kicker} · {title}'          # shown above the explanations that follow
        self.items.append({'kind': 'slide', 'kicker': kicker, 'title': title, 'points': list(points),
                           'hold': hold or _read_time(title, points, cap=2.8)})

    def explain(self, locators, title, points=(), kicker='', hold=None, pad=8):
        """Pause on the current screen and explain the part covered by `locators` (one locator or a list)."""
        locators = locators if isinstance(locators, (list, tuple)) else [locators]
        locators[0].scroll_into_view_if_needed()
        self.page.wait_for_timeout(200)
        boxes = [b for b in (loc.bounding_box() for loc in locators) if b]
        x0 = max(0, min(b['x'] for b in boxes) - pad)
        y0 = max(0, min(b['y'] for b in boxes) - pad)
        x1 = min(WIN['width'], max(b['x'] + b['width'] for b in boxes) + pad)
        y1 = min(WIN['height'], max(b['y'] + b['height'] for b in boxes) + pad)
        self._mask_local()
        path = os.path.join(self.dir, f'{len(self.items):04d}-explain.png')
        self.page.screenshot(path=path)
        self.items.append({'kind': 'explain', 'png': path, 'kicker': kicker or getattr(self, 'section', self.chapter), 'title': title,
                           'points': list(points), 'box': [v * WIN_DPR for v in (x0, y0, x1, y1)],
                           'hold': hold or _read_time(title, points)})


# ── render ──

EX_W = 1120                       # screen width on an explain frame (laptop on the left, text on the right)
PANEL_X = 60 + EX_W + 36 + 60


def _fade(t, start, dur=0.45):
    return max(0.0, min(1.0, (t - start) / dur))


def _mix(c, a, bg=(14, 34, 28)):
    return tuple(int(v * a + b * (1 - a)) for v, b in zip(c, bg))


def _points(d, x, y, points, t, width, size=36, first=0.3, gap=0.3):
    for i, p in enumerate(points):
        a = _fade(t, first + i * gap)
        if a <= 0:
            break
        lines = _wrap(p, size, 'demi', width - 44)
        d.ellipse([x, y + size * 0.36, x + 16, y + size * 0.36 + 16], fill=_mix(TAPE, a))
        for line in lines:
            d.text((x + 40, y), line, font=font(size, 'demi'), fill=_mix(PAPER, a))
            y += int(size * 1.32)
        y += int(size * 0.55)
    return y


def explain_frame(bg, screen, it, t):
    img = bg.copy()
    d = ImageDraw.Draw(img)
    brand(img, 60, 44, 30)
    k = EX_W / screen.width
    sh = int(screen.height * k)
    top = max(150, (LH - sh) // 2 + 30)
    # dim everything but the explained part
    shot = screen.resize((EX_W, sh), Image.LANCZOS).convert('RGBA')
    x0, y0, x1, y1 = [v * k for v in it['box']]
    a = _fade(t, 0.0, 0.3)
    dim = Image.new('RGBA', shot.size, (6, 14, 11, int(165 * a)))
    hole = Image.new('L', shot.size, 255)
    ImageDraw.Draw(hole).rounded_rectangle([x0, y0, x1, y1], radius=10, fill=0)
    shot.paste(dim, (0, 0), Image.composite(dim.split()[3], Image.new('L', shot.size, 0), hole))
    ImageDraw.Draw(shot).rounded_rectangle([x0, y0, x1, y1], radius=10, outline=(242, 183, 5, int(255 * a)), width=5)
    bez = 16
    body = Image.new('RGBA', (EX_W + 2 * bez, sh + 2 * bez), (0, 0, 0, 0))
    bd = ImageDraw.Draw(body)
    bd.rounded_rectangle([0, 0, body.width - 1, body.height - 1], radius=24, fill=(12, 20, 17, 255))
    bd.rounded_rectangle([2, 2, body.width - 3, body.height - 3], radius=24, outline=(70, 92, 84, 255), width=3)
    body.paste(shot, (bez, bez), rounded_mask((EX_W, sh), 8))
    shadow, pad = shadowed(body, 24, blur=24, alpha=150, pad=40)
    img.alpha_composite(shadow, (60 - bez - pad + 16, top - bez - pad))
    # text panel
    width = LW - PANEL_X - 60
    y = 210
    d.text((PANEL_X, y), it['kicker'].upper(), font=font(26, 'bold'), fill=_mix(TAPE, _fade(t, 0.1)))
    y += 54
    for line in _wrap(it['title'], 54, 'heavy', width)[:3]:
        d.text((PANEL_X, y), line, font=font(54, 'heavy'), fill=_mix(PAPER, _fade(t, 0.2)))
        y += 66
    _points(d, PANEL_X, y + 30, it['points'], t, width, size=38)
    return img


def slide_frame(it, t):
    img = background(LW, LH)
    d = ImageDraw.Draw(img)
    brand(img, 60, 44, 30)
    x, width = 260, LW - 520
    y = 300 if it['points'] else 420
    d.text((x, y), it['kicker'].upper(), font=font(32, 'bold'), fill=_mix(TAPE, _fade(t, 0)))
    y += 66
    for line in _wrap(it['title'], 80, 'heavy', width)[:2]:
        d.text((x, y), line, font=font(80, 'heavy'), fill=_mix(PAPER, _fade(t, 0.15)))
        y += 96
    _points(d, x, y + 40, it['points'], t, width, size=44)
    return img


def render(workdir, path, subtitle, outro, style='lofi'):
    tl = json.load(open(os.path.join(workdir, 'timeline.json')))
    bg = background(LW, LH).convert('RGBA')
    segments = [('title', None, 2.6)] + [(it.get('kind', 'shot'), it, it['hold']) for it in tl['items']] + [('end', None, 3.5)]
    total = sum(s[2] for s in segments)
    music = make_music(total + 0.5, os.path.join(R.OUT, 'music-walkthrough.wav'), style=style)
    cmd = [FFMPEG, '-y', '-loglevel', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{LW}x{LH}', '-r', str(FPS),
           '-i', '-', '-i', music, '-filter_complex', '[1:a]volume=0.45,loudnorm=I=-22:TP=-2,aresample=48000[a]',
           '-map', '0:v', '-map', '[a]', '-c:v', 'libx264', '-preset', 'medium', '-crf', '18', '-pix_fmt', 'yuv420p',
           '-c:a', 'aac', '-b:a', '128k', '-shortest', '-movflags', '+faststart', path]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    cache = {}

    def screen(png):
        if png not in cache:
            cache.clear()
            cache[png] = Image.open(png).convert('RGB')
        return cache[png]

    for kind, it, secs in segments:
        last = None
        for f in range(max(1, round(secs * FPS))):
            t = f / FPS
            if kind == 'title':
                img = title_card(tl['chapter'], tl['title'], subtitle, t)
            elif kind == 'end':
                img = end_card(outro, t)
            elif kind == 'slide':
                img = last if (last is not None and t > 0.3 + 0.3 * len(it['points']) + 0.5) else slide_frame(it, t)
            elif kind == 'explain':
                img = last if (last is not None and t > 0.3 + 0.3 * len(it['points']) + 0.5) else explain_frame(bg, screen(it['png']), it, t)
            else:
                img = frame(bg, screen(it['png']), tl['chapter'], it['caption'], it['tap'], t if it['tap'] else None)
            last = img
            proc.stdin.write(img.convert('RGB').tobytes())
    proc.stdin.close()
    proc.wait()
    print('wrote', path, f'({total:.0f}s)')
