"""Render the recorded tutorial parts into videos (one per part + the full walkthrough).

    python tools/tutorials/make_videos.py <workdir>            all parts + the full walkthrough (parts 1–5)
    python tools/tutorials/make_videos.py <workdir> 6          just part 6
"""
import os
import sys

import recorder as R

WORK = sys.argv[1]
OUT = os.path.join(R.OUT, 'tutorials')
PARTS = [
    (1, 'company', 'Add your company name, contact details, logo and colours.', 'Your quotations now carry your brand.'),
    (2, 'rates', 'Set your rates, add your own materials and fittings.', 'Your rates are ready for every quotation.'),
    (3, 'first-quotation', 'Rooms, items in feet and inches, fittings and a discount.', 'Your first quotation, in minutes.'),
    (4, 'send-and-accept', 'Share the PDFs and let your customer accept online.', 'Accepted online. No chasing.'),
    (5, 'get-paid', 'Record payments, issue a GST invoice and see who owes you.', 'From quote to paid, in one app.'),
    (6, 'profit', 'Add your costs and see the profit on every job and every year.', 'Know what you make on every job.'),
    (7, 'change-a-quotation', 'Your customer asks for a change, then changes their mind.', 'Every version kept. Nothing re-typed.'),
]
WALKTHROUGH = (1, 2, 3, 4, 5)
STYLE = {6: 'pop', 7: 'funk'}            # parts 1–5 and the walkthrough: lo-fi; later parts vary, since they're also posted as Reels
SUB = {n: s for n, _, s, _ in PARTS}

if __name__ == '__main__':
    os.makedirs(OUT, exist_ok=True)
    only = {int(a) for a in sys.argv[2:]}
    for n, slug, _, outro in PARTS:
        if not only or n in only:
            R.render([os.path.join(WORK, f'part{n}')], os.path.join(OUT, f'quoteroom-tutorial-{n}-{slug}.mp4'), SUB.get, outro,
                     style=STYLE.get(n, 'lofi'))
    if not only:
        R.render([os.path.join(WORK, f'part{n}') for n in WALKTHROUGH], os.path.join(OUT, 'quoteroom-tutorial-full.mp4'), SUB.get,
                 'You\'re all set. Welcome to QuoteRoom!')
