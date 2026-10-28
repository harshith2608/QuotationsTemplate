"""Reel 'Bring your old quotation': got an old quotation? → upload it (PDF or Excel) → every line read, same total →
one tap: items and rates, terms, the quotation rebuilt, saved as a starting quotation → your next quotation starts
filled in → free trial. The app on a LAPTOP with a close-up below, from the screens recorded for tutorial 15
(tools/tutorials/import_walkthrough.py, the fictional "Nest & Grain Interiors").

    python tools/ad_video/reel_import.py <tutorial workdir>          → ad-videos/reel-import-9x16.mp4
    python tools/ad_video/reel_import.py <tutorial workdir> stills   → ad-videos/reel-import-frames.png
"""
import json
import os
import sys

from PIL import Image, ImageDraw

from carousel_lost_jobs import rich_pill
from reel_tape_to_invoice import LOGO, back_out, ease, phase
from reel_templates import BG, W, heading, make_frame_at, put_laptop, render, zoom
from static_ads import INK, MUTED, OUT, PAPER, TAPE, brand, font, shadowed


def load(workdir):
    tl = json.load(open(os.path.join(workdir, 'import', 'timeline.json')))
    items = tl['items']
    img = lambda it: Image.open(it['png']).convert('RGB')
    title = lambda t: next(it for it in items if it.get('title') == t)
    cap = lambda c: [it for it in items if (it.get('caption') or '').startswith(c)]
    pick = cap('Pick it.')
    return {
        'old': img(cap('Your old quotation')[0]),
        'chosen': img(title('Choose the file')), 'box_chosen': title('Choose the file')['box'],
        'read_tap': cap('Read my quotation.')[0]['tap'], 'reading': img(cap('Reading your quotation')[0]),
        'review': img(title('Every line, read for you')), 'box_ok': title('Every line, read for you')['box'],
        'lines': img(title('Edit anything')), 'box_lines': title('Edit anything')['box'],
        'done': img(title('Your app is set up')),
        'pdf': img(cap('Your quotation, rebuilt')[0]), 'pdf_end': img(cap('Same items, same rates')[0]),
        'start': img(title('Saved as a starting quotation')), 'box_start': title('Saved as a starting quotation')['box'],
        'pick_tap': pick[0]['tap'],
        'filled': img(title('Every line ready')), 'box_filled': title('Every line ready')['box'],
    }


def paper(img, page, t, y=760, width=760, tilt=-4):
    """The old quotation as a sheet of paper, dropping in."""
    a = ease(min(1.0, t / 0.6))
    crop = page.crop((int(page.width * 0.15), 20, int(page.width * 0.85), int(page.height * 0.78)))
    k = width / crop.width
    sheet = crop.resize((width, int(crop.height * k)), Image.LANCZOS).convert('RGBA')
    sheet = sheet.rotate(tilt * a, expand=True, resample=Image.BICUBIC)
    sh_img, pad = shadowed(sheet, 6, blur=24, alpha=150, pad=40)
    if a < 1:
        sh_img.putalpha(sh_img.getchannel('A').point(lambda v: int(v * a)))
    img.alpha_composite(sh_img, ((W - sheet.width) // 2 - pad, y - pad + int(120 * (1 - a))))


def checklist(img, rows, t, top=1180, start=0.5, gap=0.42):
    """✓ rows popping in one after another (the set-up's results)."""
    d = ImageDraw.Draw(img)
    for i, text in enumerate(rows):
        a = phase(t, start + i * gap, start + i * gap + 0.3)
        if a <= 0:
            continue
        y = top + i * 128 + int(24 * (1 - a))
        x0, x1 = 110, W - 110
        layer = Image.new('RGBA', img.size, (0, 0, 0, 0))
        ld = ImageDraw.Draw(layer)
        ld.rounded_rectangle([x0, y, x1, y + 104], radius=52, fill=(245, 246, 242, int(240 * a)))
        ld.ellipse([x0 + 22, y + 20, x0 + 86, y + 84], fill=TAPE + (int(255 * a),))
        ld.line([(x0 + 38, y + 52), (x0 + 50, y + 66), (x0 + 72, y + 38)], fill=INK + (int(255 * a),), width=8)
        ld.text((x0 + 112, y + 52), text, font=font(44, 'bold'), fill=INK + (int(255 * a),), anchor='lm')
        img.alpha_composite(layer)


def scenes(S):
    def hook(t):
        img = BG.copy()
        d = ImageDraw.Draw(img)
        brand(img, 60, 110, 46)
        a = phase(t, 0.0, 0.4)
        col = lambda c: tuple(int(v * a + 14 * (1 - a)) for v in c)
        d.text((60, 250), 'Got an old quotation?', font=font(78), fill=col(PAPER))
        d.text((60, 345), 'Your app is set up.', font=font(78), fill=col(TAPE))
        paper(img, S['old'], t, y=560)
        b = phase(t, 1.2, 1.6)
        if b > 0:
            colb = lambda c: tuple(int(v * b + 14 * (1 - b)) for v in c)
            d.text((W / 2, 1640), 'Items. Rates. Terms. In a minute.', font=font(50), fill=colb(PAPER), anchor='mm')
        return img

    def upload(t):
        img = BG.copy()
        heading(img, 'Upload your old quotation', 'PDF or Excel file', t)
        screen = S['chosen'] if t < 1.7 else S['reading']
        put_laptop(img, screen, S['read_tap'], t - 1.1 if 1.1 <= t < 1.7 else None)
        zoom(img, S['chosen'], S['box_chosen'], t, start=0.3)
        return img

    def read(t):
        img = BG.copy()
        heading(img, 'Every line, read for you', 'Same items, same rates, same total', t)
        put_laptop(img, S['review'] if t < 1.6 else S['lines'])
        zoom(img, S['review'], S['box_ok'], t, start=0.3) if t < 1.6 else zoom(img, S['lines'], S['box_lines'], t - 1.6, start=0.0)
        return img

    def setup(t):
        img = BG.copy()
        heading(img, 'One tap. All set up.', '', t)
        put_laptop(img, S['done'])
        checklist(img, ['Your items and rates', 'Payment terms and T&C', 'Your quotation, rebuilt',
                        'Saved as a template'], t)
        return img

    def rebuilt(t):
        img = BG.copy()
        heading(img, 'Your quotation, in QuoteRoom', 'Ready to send as a clean PDF', t)
        put_laptop(img, S['pdf'] if t < 1.5 else S['pdf_end'])
        w, h = S['pdf_end'].size
        if t >= 1.5:
            zoom(img, S['pdf_end'], (w * 0.2, h * 0.02, w * 0.8, h * 0.45), t - 1.5, start=0.0)
        else:
            zoom(img, S['pdf'], (w * 0.2, h * 0.02, w * 0.8, h * 0.40), t, start=0.3)
        return img

    def next_quote(t):
        img = BG.copy()
        heading(img, 'Your next quotation?', 'Starts filled in. Type the sizes, send.', t)
        if t < 1.5:
            put_laptop(img, S['start'], S['pick_tap'], t - 0.9 if t >= 0.9 else None)
            zoom(img, S['start'], S['box_start'], t, start=0.3)
        else:
            put_laptop(img, S['filled'])
            zoom(img, S['filled'], S['box_filled'], t - 1.5, start=0.0)
        return img

    def end(t):
        img = BG.copy()
        d = ImageDraw.Draw(img)
        k = back_out(t / 0.5)
        size = max(10, int(240 * min(k, 1.05)))
        img.alpha_composite(LOGO.resize((size, size)), ((W - size) // 2, 560 - size // 2))
        a = phase(t, 0.3, 0.7)
        col = lambda c: tuple(int(v * a + 14 * (1 - a)) for v in c)
        d.text((W / 2, 820), 'Set up in a minute,', font=font(78), fill=col(PAPER), anchor='mm')
        d.text((W / 2, 915), 'not in days.', font=font(78), fill=col(TAPE), anchor='mm')
        d.text((W / 2, 1040), 'Just upload one quotation you\'ve sent.', font=font(38, 'demi'), fill=col(MUTED), anchor='mm')
        if t > 0.9:
            kk = back_out((t - 0.9) / 0.4)
            rich_pill(img, 'Start your free 7-day trial', W / 2, 1250, max(20, int(50 * min(kk, 1.05))))
        if t > 1.3:
            d.text((W / 2, 1390), 'No payment to start  ·  quote-room.co.in', font=font(34, 'demi'), fill=MUTED, anchor='mm')
        return img

    return [(hook, 2.8), (upload, 2.8), (read, 3.2), (setup, 3.0), (rebuilt, 3.0), (next_quote, 3.2), (end, 4.4)]


if __name__ == '__main__':
    os.makedirs(OUT, exist_ok=True)
    frame_at, total, starts = make_frame_at(scenes(load(sys.argv[1])))
    if len(sys.argv) > 2 and sys.argv[2] == 'stills':
        times = [s + d - 0.4 for s, (_, d) in zip(starts, scenes(load(sys.argv[1])))]
        sheet = Image.new('RGB', (370 * len(times), 640), 'white')
        for i, T in enumerate(times):
            sheet.paste(frame_at(T).resize((360, 640)), (i * 370, 0))
        sheet.save(os.path.join(OUT, 'reel-import-frames.png'))
        print('stills done', round(total, 1), 's')
    else:
        render(frame_at, total, os.path.join(OUT, 'reel-import-9x16.mp4'), '9x16')
