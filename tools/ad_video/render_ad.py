"""QuoteRoom vertical ad (9:16): frames drawn with Pillow from static/ads/, macOS voice-over, encoded with ffmpeg.

    pip install pillow imageio-ffmpeg
    python tools/ad_video/render_ad.py Aman          # voice: Aman / Rishi / Tara (Indian English, built into macOS)
    python tools/ad_video/render_ad.py Aman stills   # preview frames only

Output: ad-videos/quoteroom-ad-9x16-<voice>.mp4 (git-ignored).
"""
import math
import os
import subprocess
import sys
import wave
import array

from PIL import Image, ImageDraw, ImageFilter, ImageFont
import imageio_ffmpeg

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
ADS = os.path.join(ROOT, 'static', 'ads')
OUT = os.path.join(ROOT, 'ad-videos')            # git-ignored
os.makedirs(OUT, exist_ok=True)
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()

VOICE = sys.argv[1] if len(sys.argv) > 1 else 'Rishi'
W, H = (1080, 1920)
FPS = 30

PINE = (31, 77, 63)
PINE_DARK = (18, 46, 38)
TAPE = (242, 183, 5)
PAPER = (245, 246, 242)
INK = (22, 35, 31)
WA_GREEN = (37, 211, 102)

AV = '/System/Library/Fonts/Avenir Next.ttc'
def font(size, weight='heavy'):
    return ImageFont.truetype(AV, size, index={'bold': 0, 'demi': 2, 'medium': 5, 'regular': 7, 'heavy': 8}[weight])


# ── easing ──
def clamp(x, a=0.0, b=1.0):
    return max(a, min(b, x))

def ease_out(x):
    x = clamp(x)
    return 1 - (1 - x) ** 3

def ease_in_out(x):
    x = clamp(x)
    return 4 * x ** 3 if x < 0.5 else 1 - (-2 * x + 2) ** 3 / 2

def back_out(x):
    x = clamp(x)
    c1, c3 = 1.70158, 2.70158
    return 1 + c3 * (x - 1) ** 3 + c1 * (x - 1) ** 2


# ── voice-over ──
LINES = [
    'Still sending quotations days after the site visit?',
    'With Quote Room, measure each room in feet and inches, right on your phone.',
    'Your rates are applied instantly, and every payment is tracked.',
    'Send a detailed quotation to your client, immediately after measurements.',
    'Quote Room. Start your free seven-day trial today.',
]

def make_voice():
    clips = []
    for i, line in enumerate(LINES):
        aiff = os.path.join(OUT, f'vo{i}.aiff')
        wav = os.path.join(OUT, f'vo{i}.wav')
        subprocess.run(['say', '-v', VOICE, '-r', '196', '-o', aiff, line], check=True)
        subprocess.run([FFMPEG, '-y', '-loglevel', 'error', '-i', aiff, '-ar', '48000', '-ac', '1', wav], check=True)
        with wave.open(wav) as w:
            clips.append((wav, w.getnframes() / w.getframerate()))
    return clips

# ── recorded voice-over (a real recording instead of `say`) ──
# Parts of the recording (seconds, from silence detection) → scene, with the gap to leave before each part.
RECORDING_PARTS = [  # (scene, start, end, gap_before)
    (0, 0.00, 2.27, 0.00),    # Still sending quotations days after the site visit?
    (1, 2.86, 6.18, 0.45),    # Type the measurements on site, QuoteRoom does the math instantly.
    (2, 6.70, 8.27, 0.40),    # Your rates are applied instantly,
    (2, 8.67, 10.09, 0.30),   # and every payment is tracked.
    (3, 10.62, 12.37, 0.45),  # Send a detailed quotation to your client
    (3, 12.74, 15.98, 0.06),  # immediately after the measurements before you even leave the site.  (pause removed)
    (4, 16.50, 19.05, 0.50),  # QuoteRoom. Start your free seven-day trial today.
]
RECORDED = VOICE.lower().endswith(('.m4a', '.wav', '.mp3', '.aac', '.aiff'))

def load_recording(path):
    wav = os.path.join(OUT, 'recording.wav')
    subprocess.run([FFMPEG, '-y', '-loglevel', 'error', '-i', path, '-ar', '48000', '-ac', '1', wav], check=True)
    with wave.open(wav) as w:
        return array.array('h', w.readframes(w.getnframes())), w.getframerate()

if RECORDED:
    REC, RATE = load_recording(VOICE)
    PAD_IN, PAD_OUT = 0.06, 0.12                  # keep soft consonants at the cut points
    placed, cursor = [], 0.25                     # (scene, time in video, samples)
    for i, (scene, a, b, gap) in enumerate(RECORDING_PARTS):
        lo = a - PAD_IN if i == 0 else max(a - PAD_IN, RECORDING_PARTS[i - 1][2] + 0.02)
        hi = b + PAD_OUT if i == len(RECORDING_PARTS) - 1 else min(b + PAD_OUT, RECORDING_PARTS[i + 1][1] - 0.02)
        lo = max(lo, 0.0)
        seg = REC[int(lo * RATE):int(hi * RATE)]
        fade = int(0.012 * RATE)                  # 12 ms fades: no clicks at the cuts
        for k in range(min(fade, len(seg))):
            seg[k] = int(seg[k] * k / fade)
            seg[-1 - k] = int(seg[-1 - k] * k / fade)
        cursor += gap if i else 0.0
        placed.append((scene, cursor, seg))
        cursor += len(seg) / RATE
    first = {}
    for scene, at, _ in placed:
        first.setdefault(scene, at)
    starts = [0.0] + [first[k] - 0.25 for k in range(1, 5)]
    TOTAL = cursor + 1.3
    durs = [starts[k + 1] - starts[k] for k in range(4)] + [TOTAL - starts[4]]
    print('recording', VOICE, 'scene durations', [round(d, 2) for d in durs], 'total', round(TOTAL, 2))

    def make_audio():
        total = int(TOTAL * RATE) + RATE // 2
        mix = array.array('h', [0]) * total
        for _, at, seg in placed:
            off = int(at * RATE)
            n = max(0, min(len(seg), total - off))
            mix[off:off + n] = seg[:n]
        path = os.path.join(OUT, 'voice_track.wav')
        with wave.open(path, 'wb') as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(RATE); w.writeframes(mix.tobytes())
        return path

clips = [] if RECORDED else make_voice()
LEAD = 0.25                                  # silence before each line within its scene
TAIL = [0.3, 0.35, 0.3, 0.75, 1.1]          # breathing room after each line
if not RECORDED:
    durs = [LEAD + d + t for (_, d), t in zip(clips, TAIL)]
    starts = [sum(durs[:i]) for i in range(len(durs))]
    TOTAL = sum(durs)
    print('voice', VOICE, 'scene durations', [round(d, 2) for d in durs], 'total', round(TOTAL, 2))

def make_tts_audio():
    rate = 48000
    total = int(TOTAL * rate) + rate // 2
    mix = array.array('h', [0]) * total
    for (wav, _), st in zip(clips, starts):
        with wave.open(wav) as w:
            data = array.array('h', w.readframes(w.getnframes()))
        off = int((st + LEAD) * rate)
        for i, v in enumerate(data):
            if off + i < total:
                mix[off + i] = v
    path = os.path.join(OUT, 'voice_track.wav')
    with wave.open(path, 'wb') as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate); w.writeframes(mix.tobytes())
    return path


# ── shared art ──
def make_background():
    bg = Image.new('RGB', (W, H), PINE)
    glow = Image.new('L', (W, H), 0)
    d = ImageDraw.Draw(glow)
    d.ellipse([-400, -300, W + 200, 1100], fill=90)
    glow = glow.filter(ImageFilter.GaussianBlur(220))
    light = Image.new('RGB', (W, H), (52, 110, 90))
    bg = Image.composite(light, bg, glow)
    shade = Image.new('L', (W, H), 0)
    ImageDraw.Draw(shade).rectangle([0, int(H * 0.72), W, H], fill=120)
    shade = shade.filter(ImageFilter.GaussianBlur(160))
    bg = Image.composite(Image.new('RGB', (W, H), PINE_DARK), bg, shade)
    return bg

BG = make_background()

def tape_strip(width, height=34, offset=0.0):
    """The measuring-tape band from the website (yellow with tick marks)."""
    strip = Image.new('RGB', (width + 120, height), TAPE)
    d = ImageDraw.Draw(strip)
    for x in range(0, width + 120, 10):
        h = height * (0.62 if x % 60 == 0 else 0.4 if x % 30 == 0 else 0.22)
        d.line([(x, 0), (x, h)], fill=(40, 34, 0), width=2 if x % 60 == 0 else 1)
    sx = int(offset) % 60
    return strip.crop((sx, 0, sx + width, height))

SCREEN_W, SCREEN_H = 640, 1386
BEZEL = 20
PHONE_W, PHONE_H = SCREEN_W + 2 * BEZEL, SCREEN_H + 2 * BEZEL

def rounded_mask(size, r):
    m = Image.new('L', size, 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, size[0] - 1, size[1] - 1], radius=r, fill=255)
    return m

SCREEN_MASK = rounded_mask((SCREEN_W, SCREEN_H), 56)

def make_phone_shell():
    shell = Image.new('RGBA', (PHONE_W + 120, PHONE_H + 120), (0, 0, 0, 0))
    sh = Image.new('L', shell.size, 0)
    ImageDraw.Draw(sh).rounded_rectangle([60, 80, 60 + PHONE_W, 80 + PHONE_H], radius=78, fill=150)
    sh = sh.filter(ImageFilter.GaussianBlur(30))
    shell.paste(Image.new('RGBA', shell.size, (0, 0, 0, 255)), (0, 0), sh)
    d = ImageDraw.Draw(shell)
    d.rounded_rectangle([60, 60, 60 + PHONE_W, 60 + PHONE_H], radius=78, fill=(14, 22, 19, 255))
    d.rounded_rectangle([62, 62, 58 + PHONE_W, 58 + PHONE_H], radius=76, outline=(70, 90, 82, 255), width=3)
    return shell

PHONE_SHELL = make_phone_shell()

def screen_view(img, cx, cy, zoom):
    """Crop of a 750x1624 screenshot centred on (cx, cy) in screenshot pixels at `zoom` (1 = whole screen)."""
    cw, ch = img.width / zoom, img.height / zoom
    x0 = clamp(cx - cw / 2, 0, img.width - cw)
    y0 = clamp(cy - ch / 2, 0, img.height - ch)
    view = img.crop((int(x0), int(y0), int(x0 + cw), int(y0 + ch))).resize((SCREEN_W, SCREEN_H), Image.LANCZOS)
    return view, (x0, y0, cw / SCREEN_W)

def phone(img, cx, cy, zoom, highlights=()):
    """Phone image (RGBA) showing a view of the screenshot, with optional yellow highlight boxes.
    highlights: [(x0, y0, x1, y1, alpha)] in screenshot pixels."""
    view, (x0, y0, k) = screen_view(img, cx, cy, zoom)
    view = view.convert('RGBA')
    for hx0, hy0, hx1, hy1, a in highlights:
        if a <= 0:
            continue
        box = [(hx0 - x0) / k, (hy0 - y0) / k, (hx1 - x0) / k, (hy1 - y0) / k]
        layer = Image.new('RGBA', view.size, (0, 0, 0, 0))
        ImageDraw.Draw(layer).rounded_rectangle(box, radius=18, outline=TAPE + (int(255 * a),), width=7)
        glow = layer.filter(ImageFilter.GaussianBlur(10))
        view = Image.alpha_composite(view, glow)
        view = Image.alpha_composite(view, layer)
    out = PHONE_SHELL.copy()
    out.paste(view, (60 + BEZEL, 60 + BEZEL), SCREEN_MASK)
    return out

def scaled(img, k):
    return img.resize((int(img.width * k), int(img.height * k)), Image.LANCZOS)

def paste_center(base, img, cx, cy, alpha=1.0):
    if alpha < 1.0:
        img = img.copy()
        a = img.getchannel('A').point(lambda v: int(v * alpha))
        img.putalpha(a)
    base.alpha_composite(img, (int(cx - img.width / 2), int(cy - img.height / 2)))

def draw_lines(base, lines, top, size, t, delay=0.0, step=0.12, center=True, weight='heavy', line_gap=1.12):
    """lines: [[(text, colour), ...], ...]; each line slides up and fades in."""
    f = font(size, weight)
    y = top
    for i, parts in enumerate(lines):
        p = ease_out((t - delay - i * step) / 0.45)
        if p <= 0:
            y += int(size * line_gap)
            continue
        width = sum(f.getlength(txt) for txt, _ in parts)
        layer = Image.new('RGBA', base.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        x = (W - width) / 2 if center else 90
        yy = y + (1 - p) * 40
        for txt, col in parts:
            d.text((x, yy), txt, font=f, fill=col + (int(255 * p),))
            x += f.getlength(txt)
        base.alpha_composite(layer)
        y += int(size * line_gap)
    return y

def pill(base, text, cx, cy, fg, bg, size=46, alpha=1.0, scale=1.0, icon=None, pad=(46, 24)):
    f = font(int(size * scale), 'bold')
    tw = f.getlength(text)
    iw = int(size * scale * 1.1) if icon else 0
    w = int(tw + iw + 2 * pad[0] * scale)
    h = int(size * scale + 2 * pad[1] * scale)
    layer = Image.new('RGBA', (w + 40, h + 40), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    sh = Image.new('L', layer.size, 0)
    ImageDraw.Draw(sh).rounded_rectangle([20, 28, 20 + w, 28 + h], radius=h // 2, fill=int(110 * alpha))
    layer.paste(Image.new('RGBA', layer.size, (0, 0, 0, 255)), (0, 0), sh.filter(ImageFilter.GaussianBlur(10)))
    d.rounded_rectangle([20, 20, 20 + w, 20 + h], radius=h // 2, fill=bg + (int(255 * alpha),))
    x = 20 + pad[0] * scale
    if icon == 'check':
        r = size * scale * 0.48
        icx, icy = x + r, 20 + h / 2
        d.ellipse([icx - r, icy - r, icx + r, icy + r], fill=fg + (int(255 * alpha),))
        d.line([(icx - r * 0.45, icy), (icx - r * 0.1, icy + r * 0.38), (icx + r * 0.5, icy - r * 0.35)],
               fill=bg + (int(255 * alpha),), width=max(3, int(r * 0.22)), joint='curve')
        x += iw
    d.text((x, 20 + (h - size * scale) / 2 - size * scale * 0.08), text, font=f, fill=fg + (int(255 * alpha),))
    base.alpha_composite(layer, (int(cx - layer.width / 2), int(cy - layer.height / 2)))


# ── assets ──
S_LIST = Image.open(f'{ADS}/01-quotations-list.jpg').convert('RGB')
S_ADD = Image.open(f'{ADS}/02-add-item-measure.jpg').convert('RGB')
S_PAY = Image.open(f'{ADS}/04-room-totals-payments.jpg').convert('RGB')
PDF = Image.open(f'{ADS}/06-full-quotation-pdf.png').convert('RGB')
LOGO = Image.open(f'{ADS}/quoteroom-logo-512.png').convert('RGBA')

W_ = (255, 255, 255)


# ── scenes (t = seconds since scene start, d = scene length) ──
def scene_hook(t, d):
    f = BG.copy().convert('RGBA')
    f.paste(tape_strip(W, 34, t * 80), (0, 150))
    draw_lines(f, [[('Still sending', PAPER)], [('quotations', PAPER)], [('days after', TAPE)], [('the site visit?', PAPER)]],
               330, 118, t, delay=0.05, step=0.14)
    p = ease_out((t - 0.5) / 0.9)
    paste_center(f, phone(S_LIST, 375, 812, 1.0), W / 2, H + 520 - p * 470)
    return f

def scene_measure(t, d):
    f = BG.copy().convert('RGBA')
    draw_lines(f, [[('Measure on site.', PAPER)], [('QuoteRoom ', PAPER), ('does the math.', TAPE)]], 190, 74, t, step=0.12)
    hi1 = ease_out((t - 1.1) / 0.4)
    hi2 = ease_out((t - 2.1) / 0.4)
    ph = phone(S_ADD, 375, 812, 1.0, highlights=[(50, 775, 700, 862, hi1 * (1 - hi2 * 0.7)), (52, 1050, 698, 1126, hi2)])
    k = 0.8 + 0.06 * ease_in_out(t / d)              # slow push-in on the whole phone
    pe = ease_out(t / 0.5)
    paste_center(f, scaled(ph, k), W / 2, 1060 + (1 - pe) * 120, alpha=pe)
    if t > 2.2:
        s = back_out((t - 2.2) / 0.45)
        pill(f, "8'6\" × 6' = 51 sqft", W / 2, 1585, INK, TAPE, size=54, scale=0.6 + 0.4 * s, alpha=clamp(s))
    return f

def scene_totals(t, d):
    f = BG.copy().convert('RGBA')
    draw_lines(f, [[('Your rates. ', PAPER), ('Instant totals.', TAPE)], [('Every payment tracked.', PAPER)]], 190, 74, t, step=0.12)
    hi_room = ease_out((t - 0.4) / 0.4) * (1 - ease_out((t - 1.7) / 0.4))
    hi_pay = ease_out((t - 2.1) / 0.4)
    ph = phone(S_PAY, 375, 812, 1.0, highlights=[(52, 905, 698, 1015, hi_room), (60, 1210, 690, 1360, hi_pay)])
    k = 0.8 + 0.06 * ease_in_out(t / d)
    pe = ease_out(t / 0.4)
    paste_center(f, scaled(ph, k), W / 2, 1060, alpha=pe)
    return f

def pdf_card(t, d):
    """White document card showing a scrolling window of the full quotation."""
    cw, chh = 940, 1160
    x0, x1 = 105, PDF.width - 105                    # trim the page margins so the tables read larger
    scale = cw / (x1 - x0)
    win_h = chh / scale
    y0 = 110 + (2130 - win_h - 110) * ease_in_out((t - 0.4) / (d - 1.7))
    y0 = clamp(y0, 0, PDF.height - win_h)
    view = PDF.crop((x0, int(y0), x1, int(y0 + win_h))).resize((cw, chh), Image.LANCZOS)
    card = Image.new('RGBA', (cw + 120, chh + 120), (0, 0, 0, 0))
    sh = Image.new('L', card.size, 0)
    ImageDraw.Draw(sh).rounded_rectangle([60, 80, 60 + cw, 80 + chh], radius=26, fill=170)
    card.paste(Image.new('RGBA', card.size, (0, 0, 0, 255)), (0, 0), sh.filter(ImageFilter.GaussianBlur(28)))
    card.paste(view, (60, 60), rounded_mask((cw, chh), 26))
    return card.rotate(-2.2, resample=Image.BICUBIC, expand=True)

def scene_quote(t, d):
    f = BG.copy().convert('RGBA')
    draw_lines(f, [[('Send a ', PAPER), ('detailed quotation', TAPE)], [('before you leave the site', PAPER)]], 200, 64, t, step=0.12)
    pe = ease_out(t / 0.5)
    paste_center(f, pdf_card(t, d), W / 2 + (1 - pe) * 80, 1040, alpha=pe)
    if t > d - 1.7:
        s = back_out((t - (d - 1.7)) / 0.45)
        pill(f, 'Sent to client', W / 2, 1585, W_, (18, 140, 80), size=50, scale=0.6 + 0.4 * s,
             alpha=clamp(s), icon='check')
    return f

def scene_end(t, d):
    f = BG.copy().convert('RGBA')
    f.paste(tape_strip(W, 34, t * 80), (0, 150))
    s = back_out(t / 0.55)
    lg = LOGO.resize((max(1, int(250 * (0.7 + 0.3 * s))),) * 2, Image.LANCZOS)
    paste_center(f, lg, W / 2, 560, alpha=clamp(s))
    draw_lines(f, [[('QuoteRoom', PAPER)]], 730, 132, t, delay=0.15)
    draw_lines(f, [[('Quotes before you leave the site.', (205, 222, 214))]], 905, 50, t, delay=0.35, weight='demi')
    if t > 0.6:
        s2 = back_out((t - 0.6) / 0.5)
        pill(f, 'Start your 7-day free trial', W / 2, 1130, INK, TAPE, size=54, scale=0.6 + 0.4 * s2, alpha=clamp(s2))
    draw_lines(f, [[('quote-room.co.in', PAPER)]], 1270, 56, t, delay=0.9, weight='bold')
    draw_lines(f, [[('No payment needed to start', (170, 196, 185))]], 1365, 40, t, delay=1.1, weight='medium')
    return f

SCENES = [scene_hook, scene_measure, scene_totals, scene_quote, scene_end]
XFADE = 0.22


def frame_at(T):
    i = max(k for k in range(len(SCENES)) if starts[k] <= T + 1e-9)
    t = T - starts[i]
    img = SCENES[i](t, durs[i])
    if i > 0 and t < XFADE:                    # crossfade from the previous scene's last moment
        prev = SCENES[i - 1](durs[i - 1] - 0.001, durs[i - 1])
        img = Image.blend(prev, img, ease_in_out(t / XFADE))
    return img.convert('RGB')


def make_music(seconds, path, rate=48000):
    """A gentle ambient bed composed here (so it's free to use in ads): warm chords + soft plucks, 96 bpm.
    Fmaj7 → Am7 → Dm7 → Cmaj7, one chord per bar."""
    import numpy as np
    n = int(seconds * rate)
    t = np.arange(n) / rate
    out = np.zeros(n)
    bar = 60 / 96 * 4
    chords = [  # (bass, pad notes) in Hz
        (87.31, [174.61, 220.00, 261.63, 329.63]),   # Fmaj7
        (110.00, [220.00, 261.63, 329.63, 392.00]),  # Am7
        (73.42, [146.83, 174.61, 220.00, 261.63]),   # Dm7
        (65.41, [130.81, 164.81, 196.00, 246.94]),   # Cmaj7
    ]
    rng = np.random.default_rng(7)
    for b in range(int(seconds / bar) + 2):
        bass, notes = chords[b % 4]
        t0, t1 = b * bar, (b + 1) * bar + 0.9                   # overlap into the next bar = smooth changes
        i0, i1 = max(0, int(t0 * rate)), min(n, int(t1 * rate))
        if i0 >= n:
            break
        tt = t[i0:i1] - t0
        env = np.minimum(1, tt / 0.7) * np.minimum(1, (t1 - t0 - tt) / 0.9)   # slow attack, soft release
        pad = sum(np.sin(2 * np.pi * f * (1 + d) * tt + rng.uniform(0, 6.28)) * (0.55 if k else 0.8)
                  for k, f in enumerate(notes) for d in (-0.0015, 0.0015)) / 8
        pad += 0.25 * sum(np.sin(2 * np.pi * 2 * f * tt) for f in notes) / 8       # a little shimmer
        out[i0:i1] += env * (0.55 * pad + 0.35 * np.sin(2 * np.pi * bass * tt))
        step = bar / 8                                               # soft eighth-note plucks
        for k in range(8):
            if k in (3, 7):
                continue                                             # leave space, don't fill every step
            f = notes[[0, 2, 1, 3, 2, 0, 3, 1][k]] * 2
            s0 = int((t0 + k * step) * rate)
            if s0 >= n:
                break
            m = min(n - s0, int(1.2 * rate))
            pt = np.arange(m) / rate
            pluck = (np.sin(2 * np.pi * f * pt) + 0.18 * np.sin(2 * np.pi * 3 * f * pt)) * np.exp(-pt / 0.32)
            out[s0:s0 + m] += 0.10 * pluck * np.minimum(1, pt / 0.004)
    # gentle low-pass (one-pole) to keep it warm, then fades
    y = np.empty_like(out); a = 0.18; acc = 0.0
    for i, v in enumerate(out):
        acc += a * (v - acc); y[i] = acc
    y *= np.minimum(1, t / 1.0) * np.minimum(1, (seconds - t) / 1.8)
    y = y / (np.abs(y).max() + 1e-9) * 0.5
    with wave.open(path, 'wb') as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes((y * 32767).astype('<i2').tobytes())
    return path


MUSIC_LEVEL = 0.16        # music under the voice (it also ducks further while someone is speaking)


def render(path, size=(W, H), crop_to=None):
    audio = make_audio() if RECORDED else make_tts_audio()
    n = int(math.ceil(TOTAL * FPS))
    out_w, out_h = crop_to or size
    music = make_music(TOTAL + 0.5, os.path.join(OUT, 'music.wav'))
    voice_fx = 'highpass=f=75,acompressor=threshold=-20dB:ratio=2.5:attack=5:release=150,' if RECORDED else ''
    mix = (f'[1:a]{voice_fx}asplit=2[v][sc];'
           f'[2:a]volume={MUSIC_LEVEL}[m];'
           '[m][sc]sidechaincompress=threshold=0.02:ratio=6:attack=30:release=400[md];'
           '[v][md]amix=inputs=2:duration=first:normalize=0,loudnorm=I=-16:TP=-1.5,aresample=48000[a]')
    cmd = [FFMPEG, '-y', '-loglevel', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{out_w}x{out_h}',
           '-r', str(FPS), '-i', '-', '-i', audio, '-i', music, '-filter_complex', mix,
           '-map', '0:v', '-map', '[a]', '-c:v', 'libx264', '-preset', 'medium', '-crf', '17',
           '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '160k', '-shortest', '-movflags', '+faststart', path]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for k in range(n):
        img = frame_at(k / FPS)
        if crop_to:
            img = img.crop(((W - out_w) // 2, (H - out_h) // 2, (W + out_w) // 2, (H + out_h) // 2))
        proc.stdin.write(img.tobytes())
        if k % 90 == 0:
            print(f'frame {k}/{n}', flush=True)
    proc.stdin.close()
    proc.wait()
    print('wrote', path)


if __name__ == '__main__':
    mode = sys.argv[2] if len(sys.argv) > 2 else 'video'
    if mode == 'stills':
        for T in [1.6, starts[1] + 3.0, starts[2] + 2.9, starts[3] + 1.2, starts[3] + durs[3] - 0.5, starts[4] + 1.6]:
            frame_at(T).save(os.path.join(OUT, f'still_{T:05.2f}.png'))
        print('stills done')
    else:
        name = 'your-voice' if RECORDED else VOICE.lower()
        render(os.path.join(OUT, f'quoteroom-ad-9x16-{name}.mp4'))
