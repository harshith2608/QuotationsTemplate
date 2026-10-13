"""QuoteRoom vertical ad (9:16): frames drawn with Pillow from static/ads/, macOS voice-over, encoded with ffmpeg.

    pip install pillow imageio-ffmpeg
    python tools/ad_video/render_ad.py Aman          # voice: Aman / Rishi / Tara (Indian English, built into macOS)
    python tools/ad_video/render_ad.py Aman stills   # preview frames only
    python tools/ad_video/render_ad.py ~/Downloads/voice.m4a video 4x5   # a recording (see RECORDING_PARTS); format 9x16 / 4x5 / 16x9

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
FORMAT = sys.argv[3] if len(sys.argv) > 3 else '9x16'
# Positions per format. 9x16: Reels / Stories / Shorts. 4x5: Facebook & Instagram feed. 16x9: YouTube.
LAYOUTS = {
    '9x16': dict(size=(1080, 1920), tape_y=150, cap_cx=540, cap_top=190, cap_k=1.0,
                 hook_cx=540, hook_top=330, hook_size=118, hook_phone=(540, 1920 + 520, 470, 1.0),
                 phone_cx=540, phone_cy=1060, phone_k=0.80, chip=(540, 1585),
                 pdf=(540, 1040, 940, 1160), end_cx=540, end=(560, 730, 905, 1130, 1270, 1365), end_k=1.0),
    '4x5': dict(size=(1080, 1350), tape_y=70, cap_cx=540, cap_top=105, cap_k=0.86,
                hook_cx=540, hook_top=200, hook_size=104, hook_phone=(540, 1350 + 330, 330, 0.66),
                phone_cx=540, phone_cy=800, phone_k=0.60, chip=(540, 1210),
                pdf=(540, 790, 860, 900), end_cx=540, end=(330, 470, 625, 800, 920, 1000), end_k=0.9),
    '16x9': dict(size=(1920, 1080), tape_y=70, cap_cx=540, cap_top=420, cap_k=0.8,
                 hook_cx=600, hook_top=230, hook_size=104, hook_phone=(1420, 1080 + 330, 330, 0.66),
                 phone_cx=1420, phone_cy=545, phone_k=0.58, chip=(540, 680),
                 pdf=(1400, 560, 720, 900), end_cx=960, end=(245, 395, 545, 700, 815, 890), end_k=0.85),
}
L = LAYOUTS[FORMAT]
W, H = L['size']
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
    d.ellipse([-400, -300, W + 200, int(H * 0.57)], fill=90)
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

def draw_lines(base, lines, top, size, t, delay=0.0, step=0.12, center=True, weight='heavy', line_gap=1.12, cx=None):
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
        x = (cx if cx is not None else W / 2) - width / 2 if center else 90
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
    f.paste(tape_strip(W, 34, t * 80), (0, L['tape_y']))
    draw_lines(f, [[('Still sending', PAPER)], [('quotations', PAPER)], [('days after', TAPE)], [('the site visit?', PAPER)]],
               L['hook_top'], L['hook_size'], t, delay=0.05, step=0.14, cx=L['hook_cx'])
    p = ease_out((t - 0.5) / 0.9)
    hx, hy, rise, hk = L['hook_phone']
    paste_center(f, scaled(phone(S_LIST, 375, 812, 1.0), hk), hx, hy - p * rise)
    return f

def scene_measure(t, d):
    f = BG.copy().convert('RGBA')
    draw_lines(f, [[('Measure on site.', PAPER)], [('QuoteRoom ', PAPER), ('does the math.', TAPE)]], L['cap_top'], int(74 * L['cap_k']), t, step=0.12, cx=L['cap_cx'])
    hi1 = ease_out((t - 1.1) / 0.4)
    hi2 = ease_out((t - 2.1) / 0.4)
    ph = phone(S_ADD, 375, 812, 1.0, highlights=[(50, 775, 700, 862, hi1 * (1 - hi2 * 0.7)), (52, 1050, 698, 1126, hi2)])
    k = L['phone_k'] * (1 + 0.075 * ease_in_out(t / d))   # slow push-in on the whole phone
    pe = ease_out(t / 0.5)
    paste_center(f, scaled(ph, k), L['phone_cx'], L['phone_cy'] + (1 - pe) * 120, alpha=pe)
    if t > 2.2:
        s = back_out((t - 2.2) / 0.45)
        pill(f, "8'6\" × 6' = 51 sqft", L['chip'][0], L['chip'][1], INK, TAPE, size=int(54 * L['cap_k']), scale=0.6 + 0.4 * s, alpha=clamp(s))
    return f

def scene_totals(t, d):
    f = BG.copy().convert('RGBA')
    draw_lines(f, [[('Your rates. ', PAPER), ('Instant totals.', TAPE)], [('Every payment tracked.', PAPER)]], L['cap_top'], int(74 * L['cap_k']), t, step=0.12, cx=L['cap_cx'])
    hi_room = ease_out((t - 0.4) / 0.4) * (1 - ease_out((t - 1.7) / 0.4))
    hi_pay = ease_out((t - 2.1) / 0.4)
    ph = phone(S_PAY, 375, 812, 1.0, highlights=[(52, 905, 698, 1015, hi_room), (60, 1210, 690, 1360, hi_pay)])
    k = L['phone_k'] * (1 + 0.075 * ease_in_out(t / d))
    pe = ease_out(t / 0.4)
    paste_center(f, scaled(ph, k), L['phone_cx'], L['phone_cy'], alpha=pe)
    return f

def pdf_card(t, d):
    """White document card showing a scrolling window of the full quotation."""
    cw, chh = L['pdf'][2], L['pdf'][3]
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
    draw_lines(f, [[('Send a ', PAPER), ('detailed quotation', TAPE)], [('before you leave the site', PAPER)]], L['cap_top'] + 10, int(64 * L['cap_k']), t, step=0.12, cx=L['cap_cx'])
    pe = ease_out(t / 0.5)
    paste_center(f, pdf_card(t, d), L['pdf'][0] + (1 - pe) * 80, L['pdf'][1], alpha=pe)
    if t > d - 1.7:
        s = back_out((t - (d - 1.7)) / 0.45)
        pill(f, 'Sent to client', L['chip'][0] if FORMAT == '16x9' else L['pdf'][0], L['chip'][1], W_, (18, 140, 80), size=int(50 * L['cap_k']), scale=0.6 + 0.4 * s,
             alpha=clamp(s), icon='check')
    return f

def scene_end(t, d):
    f = BG.copy().convert('RGBA')
    f.paste(tape_strip(W, 34, t * 80), (0, L['tape_y']))
    ly, ty, gy, cy_, uy, ny = L['end']
    ek = L['end_k']
    s = back_out(t / 0.55)
    lg = LOGO.resize((max(1, int(250 * ek * (0.7 + 0.3 * s))),) * 2, Image.LANCZOS)
    paste_center(f, lg, L['end_cx'], ly, alpha=clamp(s))
    draw_lines(f, [[('QuoteRoom', PAPER)]], ty, int(132 * ek), t, delay=0.15, cx=L['end_cx'])
    draw_lines(f, [[('Quotes before you leave the site.', (205, 222, 214))]], gy, int(50 * ek), t, delay=0.35, weight='demi', cx=L['end_cx'])
    if t > 0.6:
        s2 = back_out((t - 0.6) / 0.5)
        pill(f, 'Start your 7-day free trial', L['end_cx'], cy_, INK, TAPE, size=int(54 * ek), scale=0.6 + 0.4 * s2, alpha=clamp(s2))
    draw_lines(f, [[('quote-room.co.in', PAPER)]], uy, int(56 * ek), t, delay=0.9, weight='bold', cx=L['end_cx'])
    draw_lines(f, [[('No payment needed to start', (170, 196, 185))]], ny, int(40 * ek), t, delay=1.1, weight='medium', cx=L['end_cx'])
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
    """An upbeat, catchy bed composed here (free to use in ads): 112 bpm, C → G → Am → F,
    four-on-the-floor kick, claps, hi-hats, bassline, chord stabs and a short melody hook."""
    import numpy as np
    n = int(seconds * rate)
    out = np.zeros(n)
    rng = np.random.default_rng(11)
    beat = 60 / 112
    bar = 4 * beat

    def add(at, sig, gain):
        i0 = int(at * rate)
        if i0 >= n:
            return
        m = min(len(sig), n - i0)
        out[i0:i0 + m] += gain * sig[:m]

    def tone(f, dur, decay, harmonics=((1, 1.0),), attack=0.004):
        tt = np.arange(int(dur * rate)) / rate
        sig = sum(a * np.sin(2 * np.pi * f * h * tt) for h, a in harmonics)
        return sig * np.exp(-tt / decay) * np.minimum(1, tt / attack)

    def highpass(x, k=8):
        return x - np.convolve(x, np.ones(k) / k, mode='same')

    def lowpass(x, k=6):
        return np.convolve(x, np.ones(k) / k, mode='same')

    kt = np.arange(int(0.35 * rate)) / rate                      # kick: pitch drop 120 → 45 Hz
    kick = np.sin(2 * np.pi * np.cumsum(45 + 75 * np.exp(-kt / 0.03)) / rate) * np.exp(-kt / 0.16)
    ct = np.arange(int(0.25 * rate)) / rate
    clap = highpass(rng.standard_normal(len(ct)), 6) * np.exp(-ct / 0.07)
    ht = np.arange(int(0.08 * rate)) / rate
    hat = highpass(rng.standard_normal(len(ht)), 2) * np.exp(-ht / 0.018)

    C = {'C3': 130.81, 'D3': 146.83, 'E3': 164.81, 'F3': 174.61, 'G3': 196.0, 'A3': 220.0, 'B3': 246.94,
         'C4': 261.63, 'D4': 293.66, 'E4': 329.63, 'F4': 349.23, 'G4': 392.0, 'A4': 440.0, 'B4': 493.88,
         'C5': 523.25, 'D5': 587.33, 'E5': 659.25, 'G5': 783.99, 'A5': 880.0}
    prog = [  # (bass root, chord tones)
        (65.41, ['C4', 'E4', 'G4']), (98.0, ['B3', 'D4', 'G4']), (110.0, ['C4', 'E4', 'A4']), (87.31, ['C4', 'F4', 'A4'])]
    hook = [('E5', 0, 1), ('G5', 1, 1), ('A5', 2, 1.5), ('G5', 3.5, .5), ('E5', 4, 1), ('D5', 5, 1), ('C5', 6, 2),
            ('E5', 8, 1), ('G5', 9, 1), ('A5', 10, 1.5), ('G5', 11.5, .5), ('E5', 12, 1), ('G5', 13, 1), ('C5', 14, 2)]
    piano = ((1, 1.0), (2, 0.45), (3, 0.2), (4, 0.08))
    bars = int(seconds / bar) + 1
    for b in range(bars):
        t0 = b * bar
        root, tones = prog[b % 4]
        for k in range(4):                                       # drums
            add(t0 + k * beat, kick, 0.9)
            add(t0 + k * beat + beat / 2, hat, 0.16)
            if k in (1, 3):
                add(t0 + k * beat, clap, 0.32)
        for k, at in enumerate([0, 1.5, 2, 3, 3.5]):             # syncopated bassline
            add(t0 + at * beat, tone(root * (2 if k == 3 else 1), 0.5, 0.22, ((1, 1), (2, 0.35), (3, 0.12))), 0.55)
        for at in (0.5, 1.5, 2.5, 3.5):                          # off-beat chord stabs
            for nme in tones:
                add(t0 + at * beat, tone(C[nme], 0.45, 0.16, piano), 0.11)
        if b >= 1:                                               # melody hook from bar 2 (let the intro breathe)
            cyc = (b - 1) % 4
            for nme, st, ln in hook:
                if cyc * 4 <= st < cyc * 4 + 4:
                    add(t0 + (st - cyc * 4) * beat, tone(C[nme], ln * beat + 0.3, 0.35 + 0.2 * ln, piano), 0.16)
    y = lowpass(out, 3)
    t = np.arange(n) / rate
    y *= np.minimum(1, t / 0.15) * np.minimum(1, (seconds - t) / 1.2)
    y = np.tanh(1.6 * y / (np.abs(y).max() + 1e-9)) / np.tanh(1.6)          # gentle glue / saturation
    y *= 0.7
    with wave.open(path, 'wb') as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes((y * 32767).astype('<i2').tobytes())
    return path


MUSIC_LEVEL = 0.42        # music level; it ducks a few dB while someone is speaking


def render(path, size=(W, H), crop_to=None):
    audio = make_audio() if RECORDED else make_tts_audio()
    n = int(math.ceil(TOTAL * FPS))
    out_w, out_h = crop_to or size
    music = make_music(TOTAL + 0.5, os.path.join(OUT, 'music.wav'))
    voice_fx = 'highpass=f=75,acompressor=threshold=-20dB:ratio=2.5:attack=5:release=150,' if RECORDED else ''
    mix = (f'[1:a]{voice_fx}asplit=2[v][sc];'
           f'[2:a]volume={MUSIC_LEVEL}[m];'
           '[m][sc]sidechaincompress=threshold=0.04:ratio=2.5:attack=20:release=300[md];'
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
            frame_at(T).save(os.path.join(OUT, f'still_{FORMAT}_{T:05.2f}.png'))
        print('stills done')
    else:
        name = 'your-voice' if RECORDED else VOICE.lower()
        render(os.path.join(OUT, f'quoteroom-ad-{FORMAT}-{name}.mp4'))
