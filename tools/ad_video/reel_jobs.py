"""Reel 'Where is every job right now?' (track every job), about 40 s:
the problem (partner, supervisor and customers all asking where a job stands; the answers in a diary and on sticky
notes) → QuoteRoom shows every job on one screen → the pipeline by stage → only the jobs on site → work started? move
it, with a note → who did what, and when → the bell → free trial. The app on a LAPTOP with a close-up below. Lo-fi music.

Screens recorded by tools/tutorials/jobs_reel_screens.py (fictional "Nest & Grain Interiors", nine made-up jobs;
Farhan Example's kitchen is moved from Confirmed to Ongoing).

    python tools/ad_video/reel_jobs.py <workdir>          → ad-videos/reel-jobs-9x16.mp4
    python tools/ad_video/reel_jobs.py <workdir> stills   → ad-videos/reel-jobs-frames.png
"""
import json
import os
import sys

from PIL import Image, ImageDraw

from carousel_lost_jobs import rich_pill
from reel_tape_to_invoice import LOGO, back_out, ease, phase
from reel_templates import BG, W, heading, make_frame_at, put_laptop, render, zoom
from static_ads import INK, MUTED, OUT, PAPER, TAPE, font

CHIP_Y = 1825
RED = (220, 53, 69)
GREEN, GREEN_INK = (37, 211, 102), (8, 40, 20)

# close-ups, in screenshot pixels (1536 × 960)
PIPELINE = (19, 107, 770, 335)           # Awaiting, Confirmed, Ongoing
FILTER = (19, 232, 800, 450)             # the stage chips and the jobs on site
FORM = (880, 160, 1517, 330)             # Move to, Note, Update stage
STEPPER = (30, 140, 830, 330)
HISTORY = (38, 360, 640, 490)
BELL = (19, 150, 700, 510)


def load(workdir):
    d = os.path.join(workdir, 'jobs')
    S = {os.path.splitext(f)[0]: Image.open(os.path.join(d, f)).convert('RGB') for f in os.listdir(d) if f.endswith('.png')}
    S['m'] = json.load(open(os.path.join(d, 'marks.json')))
    return S


def chip(img, text, t, start, fg=INK, bg=TAPE):
    if t < start:
        return
    k = back_out((t - start) / 0.35)
    rich_pill(img, text, W / 2, CHIP_Y + int(30 * (1 - min(k, 1))), max(16, int(42 * min(k, 1.05))), fg=fg, bg=bg)


# ── the problem ──

ASKS = [(0.4, 'Partner', 'Is Farhan’s kitchen confirmed?'), (1.1, 'Site supervisor', 'Sir, which site tomorrow?'),
        (1.8, 'Customer', 'When does work start at our flat?'), (2.5, 'Partner', 'How many jobs are on hold?')]


def hook(t):
    img = BG.copy()
    heading(img, 'Where is every job right now?', 'Everyone keeps asking you.', t)
    layer = Image.new('RGBA', img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    y = 540
    for start, who, text in ASKS:
        if t < start:
            break
        a = ease((t - start) / 0.25)
        f = font(44, 'demi')
        w = max(f.getlength(text), font(30, 'bold').getlength(who)) + 80
        top = y + int(30 * (1 - a))
        d.rounded_rectangle([70, top, 70 + w, top + 170], radius=30, fill=(255, 255, 255, int(250 * a)))
        d.text((110, top + 48), who, font=font(30, 'bold'), fill=(18, 140, 126, int(255 * a)), anchor='lm')
        d.text((110, top + 112), text, font=f, fill=INK + (int(255 * a),), anchor='lm')
        y += 205
    img.alpha_composite(layer)
    return img


NOTES = [('Rahul – started?', -6, (90, 560)), ('Arjun – on hold??', 5, (560, 600)), ('Meera – call back', 4, (120, 900)),
         ('Kavya – handed over', -4, (540, 940)), ('Deepak – advance?', -3, (330, 1220))]


def problem(t):
    img = BG.copy()
    heading(img, 'And the answers are…', 'In a diary. On sticky notes. In your head.', t)
    for i, (text, angle, (x, y)) in enumerate(NOTES):
        st = 0.3 + i * 0.3
        if t < st:
            continue
        k = min(back_out((t - st) / 0.35), 1.05)
        note = Image.new('RGBA', (440, 260), (0, 0, 0, 0))
        nd = ImageDraw.Draw(note)
        nd.rectangle([10, 14, 430, 250], fill=(0, 0, 0, 60))
        nd.rectangle([0, 0, 420, 240], fill=(255, 226, 92, 255))
        nd.rectangle([0, 0, 420, 34], fill=(240, 205, 60, 255))
        nd.text((210, 135), text, font=font(40, 'demi'), fill=(60, 50, 20), anchor='mm')
        note = note.rotate(angle, expand=True, resample=Image.BICUBIC)
        size = (max(1, int(note.width * k)), max(1, int(note.height * k)))
        note = note.resize(size)
        img.alpha_composite(note, (x + (440 - size[0]) // 2, y + (260 - size[1]) // 2))
    if t > 2.0:
        k = back_out((t - 2.0) / 0.35)
        rich_pill(img, 'Something always gets missed.', W / 2, 1620, max(12, int(48 * min(k, 1.05))), fg='white', bg=RED)
    return img


def solution(t):
    img = BG.copy()
    d = ImageDraw.Draw(img)
    k = back_out(t / 0.5)
    size = max(10, int(220 * min(k, 1.05)))
    img.alpha_composite(LOGO.resize((size, size)), ((W - size) // 2, 560 - size // 2))
    a = phase(t, 0.25, 0.6)
    col = lambda c: tuple(int(v * a + 14 * (1 - a)) for v in c)
    d.text((W / 2, 800), 'Every job.', font=font(80), fill=col(PAPER), anchor='mm')
    d.text((W / 2, 900), 'One screen.', font=font(80), fill=col(TAPE), anchor='mm')
    b = phase(t, 0.7, 1.0)
    colb = lambda c: tuple(int(v * b + 14 * (1 - b)) for v in c)
    for i, line in enumerate(['Awaiting, confirmed, on site, on hold, done.', 'Always up to date, for your whole team.']):
        d.text((W / 2, 1040 + i * 66), line, font=font(40, 'demi'), fill=colb(MUTED), anchor='mm')
    return img


# ── how it works ──

def scenes(S):
    m = S['m']

    def step_pipeline(t):
        img = BG.copy()
        heading(img, '1. Every stage at a glance.', 'How many jobs, and how much money', t)
        put_laptop(img, S['pipeline'])
        zoom(img, S['pipeline'], PIPELINE, t, start=0.3)
        chip(img, 'Your whole business, on one screen', t, 1.5)
        return img

    def step_filter(t):
        img = BG.copy()
        heading(img, '2. Only the jobs on site.', 'Tap a stage', t)
        if t < 1.5:
            put_laptop(img, S['list'], m['list']['tap'], t - 0.8 if t >= 0.8 else None)
            zoom(img, S['list'], FILTER, t, start=0.3)
        else:
            put_laptop(img, S['list_ongoing'])
            zoom(img, S['list_ongoing'], FILTER, t - 1.5, start=0.0)
        chip(img, 'Or search by name or mobile', t, 2.3)
        return img

    def step_move(t):
        img = BG.copy()
        heading(img, '3. Work started? Move it.', 'With a note for your team', t)
        if t < 1.8:
            put_laptop(img, S['job_move'], m['job_move']['tap'], t - 1.1 if t >= 1.1 else None)
            zoom(img, S['job_move'], FORM, t, start=0.3)
        else:
            put_laptop(img, S['job_moved'])
            zoom(img, S['job_moved'], STEPPER, t - 1.8, start=0.0)
        chip(img, 'Confirmed  →  Ongoing', t, 2.4)
        return img

    def step_history(t):
        img = BG.copy()
        heading(img, '4. Who did what, and when.', 'Every step is saved', t)
        put_laptop(img, S['job_moved'])
        zoom(img, S['job_moved'], HISTORY, t, start=0.3)
        chip(img, 'No more “who told you that?”', t, 1.4)
        return img

    def step_bell(t):
        img = BG.copy()
        heading(img, '5. The bell keeps you posted.', 'While you are on site', t)
        if t < 1.1:
            put_laptop(img, S['bell_tap'], m['bell_tap']['tap'], t - 0.4 if t >= 0.4 else None)
        else:
            put_laptop(img, S['bell'])
            zoom(img, S['bell'], BELL, t - 1.1, start=0.0)
        chip(img, 'Accepted  ·  Changes asked  ·  Paid  ✓', t, 1.9, fg=GREEN_INK, bg=GREEN)
        return img

    def end(t):
        img = BG.copy()
        d = ImageDraw.Draw(img)
        k = back_out(t / 0.5)
        size = max(10, int(240 * min(k, 1.05)))
        img.alpha_composite(LOGO.resize((size, size)), ((W - size) // 2, 560 - size // 2))
        a = phase(t, 0.3, 0.7)
        col = lambda c: tuple(int(v * a + 14 * (1 - a)) for v in c)
        d.text((W / 2, 820), 'Stop answering “where is it?”', font=font(62), fill=col(PAPER), anchor='mm')
        d.text((W / 2, 915), 'Every job, always up to date.', font=font(60), fill=col(TAPE), anchor='mm')
        if t > 0.9:
            kk = back_out((t - 0.9) / 0.4)
            rich_pill(img, 'Start your free 7-day trial', W / 2, 1150, max(20, int(50 * min(kk, 1.05))))
        if t > 1.3:
            d.text((W / 2, 1290), 'No payment to start  ·  quote-room.co.in', font=font(34, 'demi'), fill=MUTED,
                   anchor='mm')
        return img

    scenes_ = [(hook, 3.6), (problem, 3.3), (solution, 2.3), (step_pipeline, 3.2), (step_filter, 3.4),
               (step_move, 3.6), (step_history, 2.9), (step_bell, 3.2), (end, 3.4)]
    # everything (scenes and the animations inside them) at 1/PACE speed: time to read each screen
    return [((lambda fn: lambda t: fn(t / PACE))(fn), dur * PACE) for fn, dur in scenes_]


PACE = 1.4


if __name__ == '__main__':
    os.makedirs(OUT, exist_ok=True)
    S = load(sys.argv[1])
    sc = scenes(S)
    frame_at, total, starts = make_frame_at(sc)
    if len(sys.argv) > 2 and sys.argv[2] == 'stills':
        times = [s + d - 0.4 for s, (_, d) in zip(starts, sc)]
        sheet = Image.new('RGB', (370 * len(times), 640), 'white')
        for i, T in enumerate(times):
            sheet.paste(frame_at(T).resize((360, 640)), (i * 370, 0))
        sheet.save(os.path.join(OUT, 'reel-jobs-frames.png'))
        print('stills done', round(total, 1), 's')
    else:
        render(frame_at, total, os.path.join(OUT, 'reel-jobs-9x16.mp4'), '9x16', style='lofi')
