"""Video: Bring your old quotation (AI import) in QuoteRoom (laptop, 1920x1080, presentation style: see walkthrough.py).

Recorded on a FRESH local business ("Nest & Grain Interiors", nothing set up yet) with AI_IMPORT=1 and an Anthropic
key, uploading the fictional old quotation from import_sample_pdf.py (made in Excel, saved as PDF). The real AI
reads it. The screenshots are also used by the social media reel (tools/ad_video/reel_import.py).

    python tools/tutorials/import_sample_pdf.py <workdir>/old-quotation.pdf
    python tools/tutorials/import_walkthrough.py http://localhost:5140 <workdir> <admin password>
    python tools/tutorials/import_walkthrough.py --render <workdir>
"""
import os
import sys

from recorder import OUT
from walkthrough import WIN, WIN_DPR, WalkRecorder, render

TITLE = 'Bring your old quotation'
SUBTITLE = 'Upload one quotation you have sent before. Your items, rates, terms and the quotation itself are set up for you.'
OUTRO = 'Try it free for 7 days: quote-room.co.in'
LABEL = 'Bring your old quotation'
COMPANY, TAGLINE = 'Nest & Grain Interiors', 'Homes, made to measure'


def record(base, work, password):
    from playwright.sync_api import sync_playwright
    old_pdf = os.path.join(work, 'old-quotation.pdf')
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_context(viewport=WIN, device_scale_factor=WIN_DPR).new_page()
        rec = WalkRecorder(page, os.path.join(work, 'import'), LABEL, TITLE)
        page.on('dialog', lambda d: d.accept())
        page.goto(base + '/login')
        page.fill('input[name=username]', 'admin')
        page.fill('input[name=password]', password)
        page.click('button[type=submit]')
        page.wait_for_timeout(800)
        page.goto(base + '/admin/settings?tab=company')            # the business's name (set before recording)
        page.fill('[name=company_name]', COMPANY)
        page.fill('[name=company_tagline]', TAGLINE)
        if page.locator('#confirm_identity').count():
            page.check('#confirm_identity')
        page.get_by_role('button', name='Save Company Details').click()
        page.wait_for_timeout(600)

        rec.slide('Bring your old quotation', 'Set up your app in a minute', [
            'Upload a quotation you have already sent', 'Your items, rates and terms are set up for you'])

        # ── the old quotation: made in Excel, saved as PDF ──
        rec._pdf_cache = ('old', open(old_pdf, 'rb').read())
        rec.pdf_view('old', 'Your old quotation: made in Excel, saved as PDF.', 0, 0.0, hold=2.4)
        rec.pdf_view('old', 'Items, rates, payment terms, terms & conditions…', 0, 1.0, hold=2.2)

        # ── a new business: the setup guide offers the quick way ──
        page.goto(base + '/admin/setup')
        page.wait_for_timeout(500)
        card = page.locator('.card', has_text='bring your old quotation').first
        rec.explain(card, 'The quick way', ['Upload a quotation you have sent before', 'PDF or Excel'],
                    kicker='Setup guide')
        rec.tap(card.locator('a', has_text='Upload a quotation'), 'Upload a quotation.', wait=700, after_hold=0.4)

        page.set_input_files('#importFile', old_pdf)
        page.wait_for_timeout(300)
        rec.explain(page.locator('#importForm'), 'Choose the file', ['A PDF from Word, Excel or your billing software',
                                                                     'Or the Excel file itself'])
        rec._snap('Read my quotation.', 0.8, tap=rec._centre(page.locator('#importGo')))
        page.click('#importGo', no_wait_after=True)
        page.wait_for_timeout(500)
        path = os.path.join(rec.dir, f'{len(rec.items):04d}.png')      # the page is submitting: a plain screenshot
        page.screenshot(path=path)
        rec.items.append({'png': path, 'hold': 1.4, 'caption': 'Reading your quotation…', 'tap': None})
        page.wait_for_selector('#reviewForm', timeout=120000)
        page.wait_for_timeout(600)

        # ── check what was read ──
        rec.explain(page.locator('#sumOk'), 'Every line, read for you', [
            'Adds up to the same total as your quotation', 'Nothing is saved until you say so'], kicker='Check')
        first = page.locator('#reviewForm .card').nth(1)
        rec.explain(first, 'Edit anything', ['Item, description, unit, quantity, rate', 'Untick what you don\'t want'])
        rec.scroll_to(page.locator('#payTerms'), 'Payment terms and notes, too.', offset=120)
        rec.explain(page.locator('#payTerms').locator('xpath=ancestor::div[contains(@class,"card")][1]'),
                    'Your terms, as you wrote them', ['Payment terms', 'Terms & conditions'])
        rec.tap(page.locator('#setUpGo'), 'Looks right, set up my app.', wait=2500, after_hold=0.6)
        pid = page.url.rstrip('/').split('/')[-1]

        # ── what you get ──
        rec.explain(page.locator('.alert-success').first, 'Your app is set up', [
            'Your items with their rates', 'A starting quotation for jobs like it', 'Your quotation, rebuilt'],
            kicker='Done in a minute')
        url = f'{base}/projects/{pid}/pdf/customer'
        rec.pdf_view(url, 'Your quotation, rebuilt in QuoteRoom.', 0, 0.0, hold=2.6)
        rec.pdf_view(url, 'Same items, same rates, same total.', 0, 1.0, hold=2.4)

        page.goto(base + '/admin/rates')
        page.wait_for_timeout(600)
        rec.explain(page.locator('#boq-lines'), 'Your items and rates', [
            'Saved for every quotation', 'Change a rate any time'], kicker='Rates')
        page.goto(base + '/admin/settings?tab=documents')
        page.wait_for_timeout(600)
        pay = page.locator('[name=payment_terms]').locator('xpath=ancestor::div[contains(@class,"card")][1]')
        rec.explain(pay, 'Your payment terms', ['On every quotation PDF'], kicker='Settings')

        # ── the next quotation starts from it ──
        page.goto(base + '/projects/new')
        page.wait_for_timeout(600)
        rec.explain(page.locator('.ki-start-cards'), 'Saved as a starting quotation', [
            'Your next 3 BHK starts filled in', 'Type the sizes and send'], kicker='New Quotation')
        rec.tap(page.locator('.ki-start-cards a').first, 'Pick it.', wait=1200, after_hold=0.4)
        rec.explain(page.locator('#room_card_room_1'), 'Every line ready', [
            'Your items, descriptions and rates', 'Just type this home\'s sizes'])
        rec.slide('Done', 'From your old quotation to QuoteRoom', [
            'Upload one quotation (PDF or Excel)', 'Check the lines, set up your app',
            'Your next quotation starts filled in'])
        rec.save()
        browser.close()


if __name__ == '__main__':
    if sys.argv[1] == '--render':
        os.makedirs(os.path.join(OUT, 'tutorials'), exist_ok=True)
        render(os.path.join(sys.argv[2], 'import'),
               os.path.join(OUT, 'tutorials', 'quoteroom-tutorial-15-bring-your-old-quotation.mp4'), SUBTITLE, OUTRO)
    else:
        record(*sys.argv[1:4])
