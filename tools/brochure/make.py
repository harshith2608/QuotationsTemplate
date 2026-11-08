"""The one-page brochure as a PDF (and a PNG preview), with Chrome in headless mode.

    python tools/brochure/make.py      → ad-videos/QuoteRoom-Brochure.pdf, ad-videos/QuoteRoom-Brochure.png
"""
import os
import subprocess

CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, '..', '..', 'ad-videos')
SRC = 'file://' + os.path.join(HERE, 'brochure.html')

os.makedirs(OUT, exist_ok=True)
subprocess.run([CHROME, '--headless=new', '--disable-gpu', '--no-pdf-header-footer',
                f'--print-to-pdf={os.path.join(OUT, "QuoteRoom-Brochure.pdf")}', SRC], check=True, capture_output=True)
subprocess.run([CHROME, '--headless=new', '--disable-gpu', '--hide-scrollbars', '--force-device-scale-factor=2',
                '--window-size=794,1123', f'--screenshot={os.path.join(OUT, "QuoteRoom-Brochure.png")}', SRC],
               check=True, capture_output=True)
print('done')
