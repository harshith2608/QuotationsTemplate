"""Tutorial part 10: Send by email (Gmail settings → test email → email a quotation and an invoice, PDF attached).

Continues on the local tutorial app after part 9. Recorded against a PRACTICE mail server on this Mac: the tutorial
app is started with a sitecustomize that sends smtp.gmail.com to 127.0.0.1:2525, where a local server (STARTTLS +
login, like Gmail) saves each message. Nothing is sent to the internet. The addresses are fictional (.example).

    python tools/tutorials/part10_email.py http://localhost:5093 <workdir> <admin password> <practice app password file> <mailbox dir>
"""
import glob
import html
import os
import re
import sys
from email import policy
from email.parser import BytesParser

from playwright.sync_api import sync_playwright

from recorder import DPR, VIEW, Recorder

BASE, WORK, PASSWORD, APP_PW_FILE, MAILBOX = sys.argv[1:6]
BUSINESS_EMAIL = 'hello@sharmainteriors.example'
CUSTOMER_EMAIL = 'meena.iyer@example.com'
INVOICE_EMAIL = 'anita.rao@example.com'


def open_menu_item(rec, page, label, caption):
    rec.tap(page.locator('.navbar-toggler'), caption)
    rec.tap(page.locator('#navbarMain a.nav-link', has_text=label).last, caption, wait=900)


def latest_mail():
    files = sorted(glob.glob(os.path.join(MAILBOX, '*.eml')))
    return BytesParser(policy=policy.default).parse(open(files[-1], 'rb')) if files else None


def mail_screen(page, msg, path):
    """A plain phone mail view of the message the practice server received (no real mail app's branding)."""
    body = msg.get_body(preferencelist=('plain',)).get_content()
    body = re.sub(r'https?://(localhost|127\.0\.0\.1):\d+', Recorder.PUBLIC, body)
    atts = [(a.get_filename(), len(a.get_content())) for a in msg.iter_attachments()]
    chips = ''.join(f'<div class="att"><span class="pdf">PDF</span><div><b>{html.escape(n)}</b><br>'
                    f'<small>{s // 1024} KB</small></div></div>' for n, s in atts)
    sender = html.escape(str(msg['From']))
    page.set_content(f'''<html><head><meta name="viewport" content="width=device-width">
    <style>
      body {{ margin: 0; font: 15px/1.45 -apple-system, system-ui, sans-serif; color: #1c1c1e; background: #fff; }}
      .bar {{ background: #f2f2f7; padding: 14px 16px; font-weight: 600; border-bottom: 1px solid #d1d1d6; }}
      .wrap {{ padding: 16px; }}
      h1 {{ font-size: 20px; margin: 0 0 12px; }}
      .from {{ display: flex; gap: 10px; align-items: center; margin-bottom: 14px; }}
      .av {{ width: 40px; height: 40px; border-radius: 50%; background: #0f766e; color: #fff; display: flex;
             align-items: center; justify-content: center; font-weight: 700; }}
      .meta small {{ color: #6e6e73; }}
      pre {{ white-space: pre-wrap; font: inherit; margin: 0 0 16px; }}
      .att {{ display: flex; gap: 10px; align-items: center; border: 1px solid #d1d1d6; border-radius: 12px; padding: 10px 12px; margin-bottom: 8px; }}
      .pdf {{ background: #e5484d; color: #fff; font-weight: 700; font-size: 12px; border-radius: 6px; padding: 8px 6px; }}
    </style></head><body>
    <div class="bar">‹ Inbox</div>
    <div class="wrap">
      <h1>{html.escape(str(msg['Subject']))}</h1>
      <div class="from"><div class="av">SI</div><div class="meta"><b>{sender}</b><br><small>to {html.escape(str(msg['To']))}</small></div></div>
      <pre>{html.escape(body)}</pre>
      {chips}
    </div></body></html>''')
    page.wait_for_timeout(200)
    page.screenshot(path=path)
    return [a for a in msg.iter_attachments()]


def show_mail(rec, viewer, caption, hold=3.0, pdf_caption=None):
    msg = latest_mail()
    n = len(rec.items)
    atts = mail_screen(viewer, msg, os.path.join(rec.dir, f'{n:04d}-mail.png'))
    rec.image(os.path.join(rec.dir, f'{n:04d}-mail.png'), caption, hold)
    if pdf_caption and atts:
        import fitz
        from PIL import Image
        doc = fitz.open(stream=atts[0].get_content(), filetype='pdf')
        sw, sh = VIEW['width'] * DPR, VIEW['height'] * DPR
        pix = doc[0].get_pixmap(matrix=fitz.Matrix(sw / doc[0].rect.width, sw / doc[0].rect.width))
        full = Image.frombytes('RGB', (pix.width, pix.height), pix.samples)
        canvas = Image.new('RGB', (sw, sh), (82, 86, 89))
        canvas.paste(full.crop((0, 0, sw, min(full.height, sh))), (0, 0))
        p = os.path.join(rec.dir, f'{n:04d}-mailpdf.png')
        canvas.save(p)
        rec.image(p, pdf_caption, 2.4)


def part10(page, viewer):
    rec = Recorder(page, os.path.join(WORK, 'part10'), 10, 'Send by email')
    app_pw = open(APP_PW_FILE).read().strip()
    page.goto(BASE + '/projects')
    rec.shot('Send quotations and invoices from your own email.', 2.2)
    open_menu_item(rec, page, 'Settings', 'Open the menu → Settings.')
    rec.tap(page.locator('.ki-settings-nav a', has_text='Email'), 'Open the Email tab.', wait=900)
    rec.scroll_to(page.locator('details.ki-guide'), 'Using Gmail? Follow the 4 steps on this page.', offset=150)
    rec.shot('Using Gmail? Follow the 4 steps on this page.', 3.0)
    rec.shot('In your Google account: turn on 2-Step Verification, then create an App Password.', 3.4)
    rec.scroll_to(page.locator('button', has_text='Use Gmail settings'), 'Tap Use Gmail settings.', offset=200)
    rec.tap(page.locator('button', has_text='Use Gmail settings'), 'Tap Use Gmail settings: the server is filled in.')
    rec.type(page.locator('#smtp_user'), BUSINESS_EMAIL, 'Your email address.', per_frame=3)
    rec.type(page.locator('#smtp_pass'), app_pw, 'Paste the 16-letter App Password (not your normal password).', per_frame=4)
    rec.type(page.locator('#admin_email'), BUSINESS_EMAIL, 'Where you want test emails and payment alerts.', per_frame=3)
    rec.tap(page.locator('button', has_text='Save Email Settings'), 'Tap Save Email Settings.', wait=1200)
    page.evaluate('window.scrollTo(0, 0)')
    rec.tap(page.locator('button', has_text='Send test email'), 'Tap Send test email.', wait=2500)
    rec.shot('Sent! Check your inbox.', 2.0)
    show_mail(rec, viewer, 'It works: the test email is in your inbox.', 2.4)

    page.goto(BASE + '/projects?q=Meena')
    page.goto(BASE + page.locator('a[href^="/projects/"]', has_text='View').first.get_attribute('href'))
    rec.shot("Now email Meena her quotation.", 1.8)
    rec.tap(page.locator('button[data-bs-target="#emailQuoteModal"]'), 'Tap Email.', wait=700)
    rec.type(page.locator('#eqTo'), CUSTOMER_EMAIL, "Her email address.", per_frame=3)
    rec.tap(page.locator('label[for=eqFull]'), 'Attach the Initial or the Full Quotation.')
    rec.shot('The link to view and accept it online goes in too.', 2.2)
    rec.tap(page.locator('#emailQuoteModal button[type=submit]'), 'Tap Send.', wait=2500)
    rec.shot('Sent, from your own email address.', 2.0)
    show_mail(rec, viewer, 'What Meena receives: your message, the link…', 3.4, pdf_caption='…and the PDF, in your brand.')

    page.goto(BASE + '/projects?q=Anita')
    page.goto(BASE + page.locator('a[href^="/projects/"]', has_text='View').first.get_attribute('href'))
    page.once('dialog', lambda d: d.accept(INVOICE_EMAIL))
    rec.scroll_to(page.locator('#invoice'), 'Invoices too: tap Email on the invoice.')
    rec.tap(page.locator('#invoice button', has_text='Email').first, 'Invoices too: tap Email and enter the address.', wait=2500)
    page.evaluate('window.scrollTo(0, 0)')
    rec.shot('Invoice sent, PDF attached.', 2.0)
    show_mail(rec, viewer, 'The GST invoice, in their inbox.', 2.8)
    rec.save()


def run():
    for f in glob.glob(os.path.join(MAILBOX, '*.eml')):
        os.remove(f)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = dict(viewport=VIEW, device_scale_factor=DPR, is_mobile=True, has_touch=True)
        page = browser.new_context(**ctx).new_page()
        viewer = browser.new_context(**ctx).new_page()
        page.goto(BASE + '/login')
        page.fill('input[name=username]', 'admin')
        page.fill('input[name=password]', PASSWORD)
        page.click('button[type=submit]')
        page.wait_for_timeout(800)
        part10(page, viewer)
        browser.close()


if __name__ == '__main__':
    run()
