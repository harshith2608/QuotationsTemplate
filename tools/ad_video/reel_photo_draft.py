"""Reel 'How long to turn your site notes into a quotation?' (Draft from photos of site notes), about 30 s:
the hook asks how long a notebook page takes to become a quotation (guesses pop up) → snap the pages → tap Draft, a
stopwatch runs while the AI reads the handwriting → the real time it took → handwritten lines next to the rows the app
made from them → a size the notes didn't have waits to be typed → saved, with its total → free trial.

The notebook pages are the owner's own site notes (no customer details). The app screens were recorded with the real
AI on a local copy of the fictional "Nest & Grain Interiors" (tools/tutorials/photo_draft_reel_screens.py), so the
time, the sizes and the rows are what it actually did; the rates are made up.

    python tools/ad_video/reel_photo_draft.py <workdir>          → ad-videos/reel-photo-draft-9x16.mp4
    python tools/ad_video/reel_photo_draft.py <workdir> stills   → ad-videos/reel-photo-draft-frames.png
    (<workdir> has page1.jpg, page2.jpg and photodraft/ from the screens script)
"""
import json
import os
import sys

from PIL import Image, ImageDraw

from carousel_lost_jobs import rich_pill, rich_text
from reel_tape_to_invoice import LOGO, back_out, ease, phase
from reel_templates import BG, W, heading, make_frame_at, put_laptop, render, zoom
from static_ads import INK, MUTED, OUT, PAPER, TAPE, brand, font, shadowed

CHIP_Y = 1825
# a handwritten line on page 1 (photo pixels) and the row the app made from it (screenshot pixels)
PAIRS = [('TV Unit', (230, 140, 820, 212), 'room0', (30, 250, 1000, 330)),
         ('Wardrobe', (180, 472, 780, 545), 'room1', (30, 585, 1000, 670)),
         ('False ceiling', (220, 255, 820, 325), 'room0', (30, 590, 1000, 665))]
THUMBS = (38, 432, 300, 535)            # the two photos, chosen
WAITING = (30, 250, 1000, 500)          # the kitchen's highlighted rows
TOTAL = (650, 510, 1520, 830)           # the saved quotation's cost summary


def load(workdir):
    d = os.path.join(workdir, 'photodraft')
    S = {os.path.splitext(f)[0]: Image.open(os.path.join(d, f)).convert('RGB') for f in os.listdir(d) if f.endswith('.png')}
    S['m'] = json.load(open(os.path.join(d, 'marks.json')))
    S['page1'] = Image.open(os.path.join(workdir, 'page1.jpg')).convert('RGB')
    S['page2'] = Image.open(os.path.join(workdir, 'page2.jpg')).convert('RGB')
    return S


def chip(img, text, t, start, fg=INK, bg=TAPE):
    if t < start:
        return
    k = back_out((t - start) / 0.35)
    rich_pill(img, text, W / 2, CHIP_Y + int(30 * (1 - min(k, 1))), max(16, int(42 * min(k, 1.05))), fg=fg, bg=bg)


def paper(img, page, cx, cy, width, tilt, a=1.0, scale=1.0):
    """A notebook photo as a card on the background."""
    w = int(width * scale)
    sheet = page.resize((w, int(page.height * w / page.width)), Image.LANCZOS).convert('RGBA')
    sheet = sheet.rotate(tilt, expand=True, resample=Image.BICUBIC)
    sh_img, pad = shadowed(sheet, 8, blur=26, alpha=int(160 * a), pad=44)
    if a < 1:
        sh_img.putalpha(sh_img.getchannel('A').point(lambda v: int(v * a)))
    img.alpha_composite(sh_img, (int(cx - sheet.width / 2 - pad), int(cy - sheet.height / 2 - pad)))


def stopwatch(img, seconds, cx, cy, size, done=False):
    """A big stopwatch reading: a dial and '11.2 s'."""
    d = ImageDraw.Draw(img)
    r = size * 0.62
    col = TAPE if done else PAPER
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=col, width=max(4, size // 14))
    d.rounded_rectangle([cx - size * 0.12, cy - r - size * 0.22, cx + size * 0.12, cy - r - size * 0.06], radius=4, fill=col)
    import math
    ang = (seconds % 60) / 60 * 2 * math.pi - math.pi / 2
    d.line([(cx, cy), (cx + r * 0.78 * math.cos(ang), cy + r * 0.78 * math.sin(ang))], fill=col, width=max(4, size // 16))
    d.ellipse([cx - 7, cy - 7, cx + 7, cy + 7], fill=col)
    d.text((cx + r + 34, cy), f'{seconds:.1f} s', font=font(size), fill=col, anchor='lm')


def scenes(S):
    took = S['m']['took']

    def hook(t):
        img = BG.copy()
        d = ImageDraw.Draw(img)
        brand(img, 60, 110, 46)
        a = phase(t, 0.0, 0.35)
        col = lambda c: tuple(int(v * a + 14 * (1 - a)) for v in c)
        d.text((60, 230 + int(30 * (1 - a))), 'How long to turn', font=font(80), fill=col(PAPER))
        d.text((60, 330 + int(30 * (1 - a))), 'this into a quotation?', font=font(80), fill=col(TAPE))
        paper(img, S['page1'], W / 2, 1110, 640, -3, a=phase(t, 0.1, 0.5), scale=1.0 + 0.05 * ease(min(1, t / 3.4)))
        for i, (guess, x) in enumerate([('1 hour?', 250), ('30 min?', 540), ('10 min?', 830)]):
            start = 1.2 + i * 0.45
            if t > start:
                k = back_out((t - start) / 0.35)
                rich_pill(img, guess, x, 1745, max(16, int(46 * min(k, 1.05))), fg=PAPER, bg=(31, 77, 63))
        return img

    def snap(t):
        img = BG.copy()
        heading(img, 'Snap your site notes', 'One photo per page', t)
        put_laptop(img, S['chosen'], rise=phase(t, 0, 0.4))
        zoom(img, S['chosen'], THUMBS, t, start=0.4)
        chip(img, '2 pages, 2 photos', t, 1.4)
        return img

    def draft(t):
        img = BG.copy()
        heading(img, 'Tap Draft', 'The AI reads your handwriting', t)
        screen = S['chosen'] if t < 0.5 else S['drafting']
        put_laptop(img, screen, tap=S['m']['chosen']['tap'], tap_t=t - 0.15)
        # the notes, with a scan line moving down them
        strip = S['page1'].crop((0, 100, 960, 760))
        w = 900
        strip = strip.resize((w, int(strip.height * w / strip.width)), Image.LANCZOS).convert('RGBA')
        y0 = 1140
        img.alpha_composite(strip.crop((0, 0, w, 470)), ((W - w) // 2, y0))
        sy = y0 + int(470 * ((t * 0.9) % 1.0))
        layer = Image.new('RGBA', img.size, (0, 0, 0, 0))
        ImageDraw.Draw(layer).rectangle([(W - w) // 2, sy - 3, (W + w) // 2, sy + 3], fill=TAPE + (230,))
        img.alpha_composite(layer)
        stopwatch(img, took * ease(min(1.0, t / 3.0)), 380, 1760, 70)
        return img

    def done(t):
        img = BG.copy()
        d = ImageDraw.Draw(img)
        brand(img, 60, 110, 46)
        k = back_out(t / 0.45)
        size = max(10, int(120 * min(k, 1.05)))
        d.text((60, 300), f'{took:.0f} seconds.', font=font(size), fill=TAPE, anchor='lm')
        a = phase(t, 0.3, 0.6)
        d.text((60, 400), 'Every room, drafted.', font=font(48, 'demi'), fill=tuple(int(v * a + 14 * (1 - a)) for v in MUTED))
        put_laptop(img, S['result'])
        zoom(img, S['result'], S['m']['result']['box'], t, start=0.5)
        chip(img, 'Living, master, kids, kitchen', t, 1.4)
        return img

    def pair(i):
        label, note_box, room, row_box = PAIRS[i]

        def scene(t):
            img = BG.copy()
            heading(img, 'It reads your handwriting', 'Item, size and room', t if i == 0 else 1.0)
            a = phase(t, 0.0, 0.35)
            note = S['page1'].crop(note_box)
            nw = 960
            note = note.resize((nw, int(note.height * nw / note.width)), Image.LANCZOS)
            paper(img, note, W / 2, 720 + int(40 * (1 - a)), nw, -1.5, a=a)
            # arrow down
            b = phase(t, 0.35, 0.6)
            if b > 0:
                d = ImageDraw.Draw(img)
                cx, top = W / 2, 860
                d.line([(cx, top), (cx, top + 120 * b)], fill=TAPE, width=10)
                if b > 0.9:
                    d.polygon([(cx - 30, top + 100), (cx + 30, top + 100), (cx, top + 150)], fill=TAPE)
            c = phase(t, 0.55, 0.9)
            if c > 0:
                row = S[room].crop(row_box)
                rw = 1000
                row = row.resize((rw, int(row.height * rw / row.width)), Image.LANCZOS)
                card = Image.new('RGBA', (row.width + 12, row.height + 12), TAPE + (255,))
                card.paste(row, (6, 6))
                sh_img, p = shadowed(card, 14, blur=22, alpha=int(170 * c), pad=36)
                if c < 1:
                    sh_img.putalpha(sh_img.getchannel('A').point(lambda v: int(v * c)))
                img.alpha_composite(sh_img, ((W - card.width) // 2 - p, 1060 + int(30 * (1 - c)) - p))
            chip(img, f'{label}: read exactly', t, 1.0)
            return img
        return scene

    def waiting(t):
        img = BG.copy()
        heading(img, 'Not in your notes?', 'It waits for you to type it', t)
        screen = S['kitchen_waiting'] if t < 1.9 else S['kitchen_done']
        put_laptop(img, screen)
        zoom(img, screen, WAITING, t if t < 1.9 else 1.0, start=0.35)
        chip(img, 'Type the size. Done.' if t >= 1.9 else 'Kitchen sizes: not written down', t, 0.9)
        return img

    def total(t):
        img = BG.copy()
        heading(img, 'Saved, at your own rates', 'Ready to send as a PDF', t)
        put_laptop(img, S['saved'])
        zoom(img, S['saved'], TOTAL, t, start=0.35)
        chip(img, 'From notebook to quotation', t, 1.3)
        return img

    def end(t):
        img = BG.copy()
        d = ImageDraw.Draw(img)
        k = back_out(t / 0.5)
        size = max(10, int(240 * min(k, 1.05)))
        img.alpha_composite(LOGO.resize((size, size)), ((W - size) // 2, 520 - size // 2))
        a = phase(t, 0.3, 0.7)
        col = lambda c: tuple(int(v * a + 14 * (1 - a)) for v in c)
        d.text((W / 2, 790), 'Your site notes.', font=font(84), fill=col(PAPER), anchor='mm')
        d.text((W / 2, 895), 'Your quotation.', font=font(84), fill=col(TAPE), anchor='mm')
        d.text((W / 2, 1015), 'Snap the pages. Check. Send.', font=font(40, 'demi'), fill=col(MUTED), anchor='mm')
        if t > 0.9:
            kk = back_out((t - 0.9) / 0.4)
            rich_pill(img, 'Start your free 7-day trial', W / 2, 1220, max(20, int(50 * min(kk, 1.05))))
        if t > 1.3:
            d.text((W / 2, 1360), 'No payment to start  ·  quote-room.co.in', font=font(34, 'demi'), fill=MUTED,
                   anchor='mm')
        return img

    return [(hook, 3.4), (snap, 2.8), (draft, 3.4), (done, 2.8), (pair(0), 2.2), (pair(1), 2.0), (pair(2), 2.0),
            (waiting, 3.6), (total, 3.0), (end, 4.2)]


if __name__ == '__main__':
    os.makedirs(OUT, exist_ok=True)
    frame_at, total, starts = make_frame_at(scenes(load(sys.argv[1])))
    if len(sys.argv) > 2 and sys.argv[2] == 'stills':
        times = [s + 1.8 for s in starts]
        sheet = Image.new('RGB', (370 * 5, 650 * 2), 'white')
        for i, T in enumerate(times):
            sheet.paste(frame_at(T).resize((360, 640)), ((i % 5) * 370, (i // 5) * 650))
        sheet.save(os.path.join(OUT, 'reel-photo-draft-frames.png'))
        print('stills done', round(total, 1), 's')
    else:
        render(frame_at, total, os.path.join(OUT, 'reel-photo-draft-9x16.mp4'), '9x16', style='pop')
