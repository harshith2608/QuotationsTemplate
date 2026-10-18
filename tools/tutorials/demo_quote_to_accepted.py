"""Demo video for leads: a quotation made on the phone, the customer opens the link and accepts it (about 1 minute).

Sent with the first message to a lead, next to the live demo link. Recorded on the local tutorial app (any state
after part 2); adds one new quotation for a fictional customer.

    python tools/tutorials/demo_quote_to_accepted.py http://localhost:5093 <workdir> <admin password>
    python tools/tutorials/demo_quote_to_accepted.py --render <workdir>
"""
import os
import sys

from recorder import DPR, OUT, VIEW, Recorder, render

TITLE = 'Quote to accepted'
SUBTITLE = 'Make a quotation on your phone. Your customer accepts it online.'
OUTRO = 'Try it free for 7 days: quote-room.co.in'


def add_item(rec, page, room, name, l_ft, w_ft, w_in, combo, caption):
    rec.tap(page.locator(f'#room_card_{room} button', has_text='Add Item'), caption, wait=600, after_hold=0.5)
    rec.type(page.locator('#modal_item_name'), name, caption, per_frame=3)
    for sel, val in (('#modal_item_lft', l_ft), ('#modal_item_lin', '0'), ('#modal_item_wft', w_ft), ('#modal_item_win', w_in)):
        page.locator(sel).fill(val)
    page.locator('#modal_item_combo').select_option(combo)
    page.wait_for_timeout(300)
    rec.shot('Sizes in feet and inches. The area and price are worked out for you.', 2.0)
    rec.tap(page.locator('#itemModal .modal-footer button', has_text='Add Item'), caption, wait=600, after_hold=0.5)


def record(base, work, password):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_context(viewport=VIEW, device_scale_factor=DPR, is_mobile=True, has_touch=True).new_page()
        page.goto(base + '/login')
        page.fill('input[name=username]', 'admin')
        page.fill('input[name=password]', password)
        page.click('button[type=submit]')
        page.wait_for_timeout(800)

        rec = Recorder(page, os.path.join(work, 'demo'), 'Demo', TITLE)
        page.goto(base + '/projects')
        rec.shot('Your customer wants a price for their kitchen. On site, open QuoteRoom.', 2.4)
        rec.tap(page.locator('a', has_text='New Quotation').first, 'Tap New Quotation.', wait=900)
        rec.type(page.locator('#customer_name'), 'Kavya Menon', 'Customer name and mobile.', per_frame=3)
        rec.type(page.locator('#mobile'), '9000012345', 'Customer name and mobile.', per_frame=3)
        rec.tap(page.locator('#no-rooms-hint button'), 'Add a room.', wait=600, after_hold=0.5)
        rec.type(page.locator('#room_name_room_1'), 'Kitchen', 'Add a room.', per_frame=3)
        page.locator('#room_name_room_1').press('Escape')
        add_item(rec, page, 'room_1', 'Base Cabinet', '10', '2', '9', 'Acrylic|Box Work', 'Add each item with its size.')
        add_item(rec, page, 'room_1', 'Overhead Cabinet', '10', '2', '6', 'Acrylic|Box Work', 'Add each item with its size.')
        rec.scroll_to(page.locator('#final-total-display'), 'The total adds up as you go.')
        rec.shot('The total adds up as you go. Your rates, every time.', 2.2)
        rec.tap(page.locator('button', has_text='Save Quotation').last, 'Tap Save.', wait=1500, after_hold=1.0)
        quote_url = page.url
        pid = quote_url.rstrip('/').split('/')[-1]
        rec.pdf(f'{base}/projects/{pid}/pdf/customer', 'A clean PDF in your brand, ready in seconds.', hold=2.6)
        page.goto(quote_url)
        rec.scroll_to(page.locator('#approval'), 'Tap Create approval link…', offset=200)
        rec.tap(page.locator('#approval button', has_text='Create approval link'), 'Tap Create approval link…', wait=1000)
        link = page.locator('#approvalUrl').input_value().replace(Recorder.PUBLIC, base)
        rec.scroll_to(page.locator('#approval'), '…and send it on WhatsApp.', offset=200)
        rec.shot('…and send it on WhatsApp.', 2.0)

        cust = browser.new_context(viewport=VIEW, device_scale_factor=DPR, is_mobile=True, has_touch=True).new_page()
        crec = Recorder(cust, rec.dir, rec.chapter, rec.title)
        crec.items = rec.items
        cust.goto(link)
        crec.shot("Kavya opens it on her phone. No app, no login.", 2.6)
        crec.scroll_to(cust.locator('table').first, 'Every item with its size, and the total.', offset=160)
        crec.shot('Every item with its size, and the total.', 2.4)
        crec.scroll_to(cust.locator('#respond'), 'She ticks the box and taps Accept.', offset=200)
        crec.tap(cust.locator('#accAgree'), 'She ticks the box and taps Accept.', after_hold=0.5)
        crec.tap(cust.locator('#respond button[type=submit]').first, 'She ticks the box and taps Accept.', wait=1200, after_hold=0.6)
        cust.evaluate('window.scrollTo(0, 0)')
        crec.shot('Accepted!', 2.0)

        page.goto(quote_url)
        rec.shot('On your phone: Confirmed, with a notification. No chasing.', 3.0)
        rec.shot('From site visit to "yes" in minutes.', 2.4)
        rec.save()
        browser.close()


if __name__ == '__main__':
    if sys.argv[1] == '--render':
        os.makedirs(os.path.join(OUT, 'tutorials'), exist_ok=True)
        render([os.path.join(sys.argv[2], 'demo')], os.path.join(OUT, 'tutorials', 'quoteroom-demo-quote-to-accepted.mp4'),
               lambda _: SUBTITLE, OUTRO, style='pop')
    else:
        record(*sys.argv[1:4])
