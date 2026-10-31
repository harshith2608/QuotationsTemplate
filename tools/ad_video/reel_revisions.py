"""Reel 'Customer changed their mind?' (quotation revisions), 42 s:
the problem (changes on WhatsApp, then final.pdf, final_v2.pdf… which one did they agree to?) → QuoteRoom keeps every
version → edit, click Update (Rev 2, with what changed) → the same link shows it → changed their mind again: open
Rev 1, Restore → they accept, and you know exactly which one → free trial. The app on a LAPTOP with a close-up below.

Screens recorded by tools/tutorials/revisions_reel_screens.py (fictional "Nest & Grain Interiors", Sneha Example's
master bedroom: ₹82,800 with the loft, ₹69,200 without).

    python tools/ad_video/reel_revisions.py <workdir>          → ad-videos/reel-revisions-9x16.mp4
    python tools/ad_video/reel_revisions.py <workdir> stills   → ad-videos/reel-revisions-frames.png
"""
import json
import os
import sys

from PIL import Image, ImageDraw

from carousel_lost_jobs import rich_pill
from reel_tape_to_invoice import LOGO, back_out, ease, phase
from reel_templates import BG, W, heading, make_frame_at, part, put_laptop, render, zoom
from static_ads import INK, MUTED, OUT, PAPER, TAPE, font

CHIP_Y = 1825
RED = (220, 53, 69)
GREEN, GREEN_INK = (37, 211, 102), (8, 40, 20)


def load(workdir):
    d = os.path.join(workdir, 'revisions')
    S = {os.path.splitext(f)[0]: Image.open(os.path.join(d, f)).convert('RGB') for f in os.listdir(d) if f.endswith('.png')}
    S['m'] = json.load(open(os.path.join(d, 'marks.json')))
    return S


def chip(img, text, t, start, fg=INK, bg=TAPE):
    if t < start:
        return
    k = back_out((t - start) / 0.35)
    rich_pill(img, text, W / 2, CHIP_Y + int(30 * (1 - min(k, 1))), max(16, int(42 * min(k, 1.05))), fg=fg, bg=bg)


# ── the problem ──

CHAT = [(0.5, 'Can we drop the loft? Budget is tight.', 'Mon 11:02'), (1.3, 'Ok, send the new one', 'Mon 11:05'),
        (2.1, 'Actually… please keep the loft.', 'Wed 19:40'), (2.8, 'So which one is the final price?', 'Wed 19:41')]


def hook(t):
    img = BG.copy()
    heading(img, 'Customer changed their mind?', 'Again. And again.', t)
    layer = Image.new('RGBA', img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    y = 560
    for start, text, when in CHAT:
        if t < start:
            break
        a = ease((t - start) / 0.25)
        f = font(44, 'demi')
        w = f.getlength(text) + 80
        top = y + int(30 * (1 - a))
        d.rounded_rectangle([70, top, 70 + w, top + 150], radius=30, fill=(255, 255, 255, int(250 * a)))
        d.text((110, top + 58), text, font=f, fill=INK + (int(255 * a),), anchor='lm')
        d.text((70 + w - 28, top + 118), when, font=font(26, 'demi'), fill=(130, 140, 135, int(255 * a)), anchor='rm')
        y += 190
    img.alpha_composite(layer)
    if t > 0.3:
        ImageDraw.Draw(img).text((70, 520), 'Sneha (client) on WhatsApp', font=font(32, 'bold'), fill=MUTED)
    return img


FILES = ['Quotation_Sneha_final.pdf', 'Quotation_Sneha_final_v2.pdf', 'Quotation_Sneha_NEW_final.pdf',
         'Quotation_Sneha_FINAL_final (1).pdf']


def problem(t):
    img = BG.copy()
    heading(img, 'Then the mess starts.', 'Retype, rename, resend…', t)
    for i, name in enumerate(FILES):
        st = 0.35 + i * 0.4
        if t < st:
            continue
        k = back_out((t - st) / 0.35)
        yy = 560 + i * 200 + int(40 * (1 - min(k, 1)))
        layer = Image.new('RGBA', img.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        x0, x1 = 80, W - 80
        d.rounded_rectangle([x0, yy, x1, yy + 160], radius=26, fill=(250, 250, 248, 245))
        d.rounded_rectangle([x0 + 30, yy + 28, x0 + 116, yy + 132], radius=10, fill=RED)
        d.text((x0 + 73, yy + 80), 'PDF', font=font(28, 'bold'), fill='white', anchor='mm')
        d.text((x0 + 150, yy + 80), name, font=font(40, 'demi'), fill=INK, anchor='lm')
        img.alpha_composite(layer)
    if t > 2.1:
        k = back_out((t - 2.1) / 0.35)
        rich_pill(img, 'Which one did they say yes to?', W / 2, 1450, max(12, int(48 * min(k, 1.05))),
                  fg='white', bg=RED)
    return img


def solution(t):
    img = BG.copy()
    d = ImageDraw.Draw(img)
    k = back_out(t / 0.5)
    size = max(10, int(220 * min(k, 1.05)))
    img.alpha_composite(LOGO.resize((size, size)), ((W - size) // 2, 560 - size // 2))
    a = phase(t, 0.25, 0.6)
    col = lambda c: tuple(int(v * a + 14 * (1 - a)) for v in c)
    d.text((W / 2, 800), 'QuoteRoom keeps', font=font(80), fill=col(PAPER), anchor='mm')
    d.text((W / 2, 900), 'every version.', font=font(80), fill=col(TAPE), anchor='mm')
    b = phase(t, 0.7, 1.0)
    colb = lambda c: tuple(int(v * b + 14 * (1 - b)) for v in c)
    for i, line in enumerate(['One quotation. One link.', 'Change it, see what changed, go back any time.']):
        d.text((W / 2, 1040 + i * 66), line, font=font(40, 'demi'), fill=colb(MUTED), anchor='mm')
    return img


# ── how to use it ──

def scenes(S):
    m = S['m']
    grow = lambda box, top=0, bottom=0, left=0, right=0: (box[0] - left, box[1] - top, box[2] + right, box[3] + bottom)

    def step_edit(t):
        img = BG.copy()
        heading(img, '1. Edit it. Click Update.', 'Here: the loft taken out', t)
        if t < 1.7:
            put_laptop(img, S['edit_loft'], m['edit_loft']['tap'], t - 0.9 if t >= 0.9 else None)
            zoom(img, S['edit_loft'], grow(m['edit_loft']['box'], 70, 60), t, start=0.3)
        else:
            put_laptop(img, S['edit_update'], m['edit_update']['tap'], t - 1.9 if t >= 1.9 else None)
            zoom(img, S['edit_update'], grow(m['edit_update']['box'], top=100, bottom=10), t - 1.7, start=0.0)
        chip(img, 'Saved as Rev 2  ·  ₹82,800 → ₹69,200', t, 2.6)
        return img

    def step_kept(t):
        img = BG.copy()
        heading(img, '2. Every version, kept.', 'With exactly what changed', t)
        put_laptop(img, S['revisions2'])
        zoom(img, S['revisions2'], part(m['revisions2']['box'], 0, 0, 0.5, 1), t, start=0.3)
        chip(img, 'Who changed it, when, the new total', t, 1.4)
        return img

    def step_link(t):
        img = BG.copy()
        heading(img, '3. Same link, new version.', 'No new PDF to send', t)
        put_laptop(img, S['cust_rev2'])
        zoom(img, S['cust_rev2'], (330, 170, 1200, 350), t, start=0.3)
        chip(img, 'Your customer sees Rev 2 at once', t, 1.4, fg=GREEN_INK, bg=GREEN)
        return img

    def step_restore(t):
        img = BG.copy()
        heading(img, '4. Changed back? Restore.', 'Open Rev 1, click Restore', t)
        if t < 1.8:
            put_laptop(img, S['rev1_restore'], m['rev1_restore']['tap'], t - 1.1 if t >= 1.1 else None)
            zoom(img, S['rev1_restore'], part(m['rev1_restore']['box'], 0, 0, 0.5, 1), t, start=0.3)
        else:
            put_laptop(img, S['revisions3'])
            zoom(img, S['revisions3'], part(m['revisions3']['box'], 0, 0, 0.5, 1), t - 1.8, start=0.0)
        chip(img, 'The loft is back. Nothing retyped.', t, 2.6)
        return img

    def accepted(t):
        img = BG.copy()
        heading(img, 'They accept online.', 'And you know exactly which one', t)
        put_laptop(img, S['cust_accepted'])
        zoom(img, S['cust_accepted'], (330, 250, 1210, 530), t, start=0.3)
        chip(img, 'Accepted: ₹82,800, with the loft  ✓', t, 1.2, fg=GREEN_INK, bg=GREEN)
        return img

    def end(t):
        img = BG.copy()
        d = ImageDraw.Draw(img)
        k = back_out(t / 0.5)
        size = max(10, int(240 * min(k, 1.05)))
        img.alpha_composite(LOGO.resize((size, size)), ((W - size) // 2, 560 - size // 2))
        a = phase(t, 0.3, 0.7)
        col = lambda c: tuple(int(v * a + 14 * (1 - a)) for v in c)
        d.text((W / 2, 820), 'No more final_v2.pdf.', font=font(76), fill=col(PAPER), anchor='mm')
        d.text((W / 2, 915), 'Every version, one click away.', font=font(60), fill=col(TAPE), anchor='mm')
        if t > 0.9:
            kk = back_out((t - 0.9) / 0.4)
            rich_pill(img, 'Start your free 7-day trial', W / 2, 1150, max(20, int(50 * min(kk, 1.05))))
        if t > 1.3:
            d.text((W / 2, 1290), 'No payment to start  ·  quote-room.co.in', font=font(34, 'demi'), fill=MUTED,
                   anchor='mm')
        return img

    scenes_ = [(hook, 3.8), (problem, 3.4), (solution, 2.3), (step_edit, 3.8), (step_kept, 3.3), (step_link, 3.0),
               (step_restore, 4.0), (accepted, 2.9), (end, 3.4)]
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
        sheet.save(os.path.join(OUT, 'reel-revisions-frames.png'))
        print('stills done', round(total, 1), 's')
    else:
        render(frame_at, total, os.path.join(OUT, 'reel-revisions-9x16.mp4'), '9x16')
