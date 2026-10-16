"""Tutorial part 7: Change a quotation (customer asks for a change → edit → Rev 2 → they change their mind →
restore Rev 1 → they accept).

Continues on the local tutorial app after part 6 (uses Meena Iyer's wardrobe quotation, awaiting confirmation).

    python tools/tutorials/part7_revisions.py http://localhost:5093 <workdir> <admin password>
"""
import os
import sys

from playwright.sync_api import sync_playwright

from recorder import DPR, VIEW, Recorder

BASE, WORK, PASSWORD = sys.argv[1], sys.argv[2], sys.argv[3]


def customer_page(browser, rec):
    """A second phone: the customer's. Its frames go into the same video."""
    page = browser.new_context(viewport=VIEW, device_scale_factor=DPR, is_mobile=True, has_touch=True).new_page()
    crec = Recorder(page, rec.dir, rec.chapter, rec.title)
    crec.items = rec.items
    return page, crec


def ask_for_changes(cust, crec, link, note, caption):
    cust.goto(link)
    crec.scroll_to(cust.locator('#respond'), caption)
    crec.tap(cust.locator('#respond summary'), caption, wait=500)
    crec.type(cust.locator('#respond textarea[name=note]'), note, caption, per_frame=3)
    crec.tap(cust.locator('#respond button', has_text='Send my changes'), caption, wait=1200)


def part7(page, browser):
    rec = Recorder(page, os.path.join(WORK, 'part7'), 7, 'Change a quotation')
    page.on('dialog', lambda d: d.accept())
    page.goto(BASE + '/projects?search=Meena')
    quote_url = BASE + page.locator('a[href^="/projects/"]', has_text='View').first.get_attribute('href')
    page.goto(quote_url)
    rec.shot("Meena's wardrobe quotation, waiting for her answer.", 2.2)
    rec.scroll_to(page.locator('#approval'), 'Send her the approval link.')
    rec.tap(page.locator('#approval button', has_text='Create approval link'), 'Send her the approval link.', wait=1000)
    link = page.locator('#approvalUrl').input_value().replace(Recorder.PUBLIC, BASE)
    rec.shot('Send her the approval link on WhatsApp.', 1.8)

    cust, crec = customer_page(browser, rec)
    cust.goto(link)
    crec.shot('She opens it on her phone…', 2.0)
    ask_for_changes(cust, crec, link, 'Can we drop the loft to save some money?', '…and asks for a change.')
    crec.shot('…and asks for a change.', 1.8)

    page.goto(quote_url)
    rec.scroll_to(page.locator('#approval'), 'Her request shows on the quotation, and you get a notification.')
    rec.shot('Her request shows on the quotation, and you get a notification.', 2.6)
    page.evaluate('window.scrollTo(0, 0)')
    rec.tap(page.locator('a', has_text='Edit').first, 'Tap Edit.', wait=1200)
    loft = page.locator('tr[id^="item_row_"]').filter(has=page.locator('input[value="Loft"]')).first
    rec.scroll_to(loft, 'Remove the loft.')
    rec.tap(loft.locator('.btn-remove-item'), 'Remove the loft.', wait=600)
    rec.tap(page.locator('button', has_text='Update Quotation').last, 'Tap Update Quotation.', wait=1500)
    rec.shot('Saved as revision 2.', 2.0)
    rec.scroll_to(page.locator('#revisions'), 'Every version is kept, with exactly what changed.')
    rec.shot('Every version is kept, with exactly what changed.', 2.8)

    cust.goto(link)
    crec.shot('Her link shows the new version straight away.', 2.2)
    ask_for_changes(cust, crec, link, 'Actually, please keep the loft after all!', 'A day later, she changes her mind.')
    crec.shot('A day later, she changes her mind.', 1.8)

    page.goto(quote_url)
    rec.scroll_to(page.locator('#revisions'), "No need to add the loft again: open revision 1.")
    rec.tap(page.locator('#revisions a', has_text='Rev 1'), "No need to add the loft again: open revision 1.", wait=1000)
    rec.shot('Revision 1, exactly as it was.', 2.0)
    rec.tap(page.locator('#restore button', has_text='Restore revision 1'), 'Tap Restore revision 1.', wait=1500)
    rec.shot('Restored! The quotation is back to revision 1, saved as revision 3.', 2.6)
    rec.scroll_to(page.locator('#revisions'), 'Revision 2 is still there too. Nothing is lost.')
    rec.shot('Revision 2 is still there too. Nothing is lost.', 2.6)

    cust.goto(link)
    crec.shot('Her link now shows the loft again.', 2.0)
    crec.scroll_to(cust.locator('#respond'), 'She ticks the box and taps Accept.')
    crec.tap(cust.locator('#accAgree'), 'She ticks the box and taps Accept.')
    crec.tap(cust.locator('#respond button[type=submit]').first, 'She ticks the box and taps Accept.', wait=1200)
    cust.evaluate('window.scrollTo(0, 0)')
    crec.shot('Accepted!', 1.8)
    page.goto(quote_url)
    rec.shot('Confirmed, for the version she accepted.', 3.0)
    rec.save()


def run():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_context(viewport=VIEW, device_scale_factor=DPR, is_mobile=True, has_touch=True).new_page()
        page.goto(BASE + '/login')
        page.fill('input[name=username]', 'admin')
        page.fill('input[name=password]', PASSWORD)
        page.click('button[type=submit]')
        page.wait_for_timeout(800)
        part7(page, browser)
        browser.close()


if __name__ == '__main__':
    run()
