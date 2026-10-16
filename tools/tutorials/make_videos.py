"""Render the recorded tutorial parts into videos (one per part + the full walkthrough).

    python tools/tutorials/make_videos.py <workdir>
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
]
SUB = {n: s for n, _, s, _ in PARTS}

if __name__ == '__main__':
    os.makedirs(OUT, exist_ok=True)
    for n, slug, _, outro in PARTS:
        R.render([os.path.join(WORK, f'part{n}')], os.path.join(OUT, f'quoteroom-tutorial-{n}-{slug}.mp4'), SUB.get, outro)
    R.render([os.path.join(WORK, f'part{n}') for n, *_ in PARTS], os.path.join(OUT, 'quoteroom-tutorial-full.mp4'), SUB.get,
             'You\'re all set. Welcome to QuoteRoom!')
