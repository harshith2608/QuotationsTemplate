"""Tutorial parts 2–5 on the same local tutorial app (continues after part 1):
2 Rates & materials · 3 Your first quotation · 4 Send it & get it accepted · 5 Get paid.

    python tools/tutorials/parts2to5.py http://localhost:5093 <workdir> <admin password>
"""
import os
import re
import sys

from playwright.sync_api import sync_playwright

from recorder import DPR, VIEW, Recorder

BASE, WORK, PASSWORD = sys.argv[1], sys.argv[2], sys.argv[3]


def open_menu_item(rec, page, label, caption):
    rec.tap(page.locator('.navbar-toggler'), caption)
    rec.tap(page.locator('#navbarMain a.nav-link', has_text=label).last, caption, wait=900)


def part2(page):
    rec = Recorder(page, os.path.join(WORK, 'part2'), 2, 'Your rates & materials')
    page.goto(BASE + '/projects')
    rec.shot('Next, set your own rates.', 1.6)
    open_menu_item(rec, page, 'Rates', 'Open the menu → Rates.')
    rec.shot('Each material has a rate per sqft for Box Work and Frame Work.', 2.4)
    lam = page.locator('tr', has=page.locator('input[value="Laminates"]')).locator('input[type=number]').first
    rec.type(lam, '900', 'Type your own rate. Here Laminates Box Work is ₹900 per sqft.')
    rec.tap(page.locator('button[name=item_rates_submit][value=save]'), 'Tap Save.', wait=900)
    rec.scroll_to(page.locator('#mat_name'), 'Add any material you use, like Wallpaper or PU.')
    rec.type(page.locator('#mat_name'), 'Wallpaper', 'Add any material you use, like Wallpaper or PU.')
    rec.type(page.locator('#mat_rate'), '120', 'Its rate per sqft.')
    rec.tap(page.locator('button[name=material_add]'), 'Tap Add.', wait=900)
    rec.scroll_to(page.locator('#price-list'), 'Fittings are priced per piece, not by area.')
    rec.shot('Fittings are priced per piece: Magic Corner, tandem drawers, lights…', 2.4)
    new_row = page.locator('#price-list input[name=pl_name][placeholder="Add new item…"]').first
    rec.type(new_row, 'Soft-close Hinge', 'Add your own fittings with their price.')
    price = page.locator('#price-list input[name=pl_price][placeholder="0"]').first
    rec.type(price, '350', 'Add your own fittings with their price.')
    rec.tap(page.locator('button[name=price_list_submit]'), 'Tap Save Price List.', wait=900)
    rec.shot('Your rates are set. Every new quotation uses them.', 2.4)
    rec.save()


def add_measured(rec, page, room_key, name, l_ft, l_in, w_ft, w_in, combo, caption):
    rec.tap(page.locator(f'#room_card_{room_key} button', has_text='Add Item'), caption, wait=700)
    rec.type(page.locator('#modal_item_name'), name, caption)
    for sel, val in (('#modal_item_lft', l_ft), ('#modal_item_lin', l_in), ('#modal_item_wft', w_ft), ('#modal_item_win', w_in)):
        rec.type(page.locator(sel), val, 'Enter the length and width in feet and inches.', per_frame=1)
    page.locator('#modal_item_combo').select_option(combo)
    page.wait_for_timeout(300)
    rec.shot('Pick the material and work type. The area is worked out for you.', 2.0)
    rec.tap(page.locator('#itemModal .modal-footer button', has_text='Add Item'), 'Tap Add Item.', wait=700)


def part3(page):
    rec = Recorder(page, os.path.join(WORK, 'part3'), 3, 'Your first quotation')
    page.goto(BASE + '/projects')
    rec.tap(page.locator('a', has_text='New Quotation').first, 'Tap New Quotation.', wait=900)
    rec.type(page.locator('#customer_name'), 'Anita Rao', "Your customer's name and mobile number.")
    rec.type(page.locator('#mobile'), '9876543210', "Your customer's name and mobile number.")
    rec.type(page.locator('#address'), 'Flat 302, Jubilee Hills', 'Their address (optional).')
    rec.tap(page.locator('#no-rooms-hint button'), 'Add the first room.', wait=600)
    rec.type(page.locator('#room_name_room_1'), 'Kitchen', 'Name the room.')
    page.locator('#room_name_room_1').press('Escape')          # close the room-name suggestions
    add_measured(rec, page, 'room_1', 'Base Cabinet', '10', '0', '2', '9', 'Acrylic|Box Work', 'Add an item: Add Item.')
    add_measured(rec, page, 'room_1', 'Overhead Cabinet', '10', '0', '2', '6', 'Acrylic|Box Work', 'Add the next item.')
    rec.tap(page.locator('#room_card_room_1 button', has_text='Add Item'), 'Fittings like a Magic Corner are priced per piece.', wait=700)
    rec.tap(page.locator('label[for=modal_type_fixed]'), 'Choose Fixed price.')
    rec.type(page.locator('#modal_item_name'), 'Magic Corner', 'Pick it from your price list: the price fills in.')
    page.locator('#modal_item_name').dispatch_event('change')
    page.wait_for_timeout(400)
    rec.shot('Pick it from your price list: the price fills in.', 1.8)
    rec.tap(page.locator('#itemModal .modal-footer button', has_text='Add Item'), 'Tap Add Item.', wait=700)
    rec.shot('The Kitchen is done. Add the next room.', 1.8)
    rec.tap(page.locator('#add-room-btn-wrap button'), 'Add Another Room.', wait=600)
    rec.type(page.locator('#room_name_room_2'), 'Master Bedroom', 'Name the room.')
    page.locator('#room_name_room_2').press('Escape')
    add_measured(rec, page, 'room_2', 'Wardrobe', '8', '0', '7', '0', 'Laminates|Box Work', 'Add the wardrobe.')
    add_measured(rec, page, 'room_2', 'Loft', '8', '0', '2', '0', 'Laminates|Box Work', 'And the loft.')
    rec.scroll_to(page.locator('#discount_type_select'), 'Give a discount if you like.')
    page.locator('#discount_type_select').select_option('percentage')
    page.wait_for_timeout(300)
    rec.type(page.locator('#discount_value_input'), '5', 'Give a discount if you like: 5%.', per_frame=1)
    rec.scroll_to(page.locator('#final-total-display'), 'The totals add up as you go.')
    rec.shot('The total is worked out for you.', 2.2)
    rec.tap(page.locator('button', has_text='Save Quotation').last, 'Tap Save Quotation.', wait=1500)
    rec.shot('Saved! Your quotation, room by room.', 2.4)
    rec.save()
    return page.url


def part4(page, browser, quote_url):
    rec = Recorder(page, os.path.join(WORK, 'part4'), 4, 'Send it & get it accepted')
    page.goto(quote_url)
    rec.shot('Two PDFs, ready to send.', 1.8)
    pid = re.search(r'/projects/(\d+)', quote_url).group(1)
    rec.pdf(f'{BASE}/projects/{pid}/pdf/customer', 'Initial Quotation: amounts by material, no measurements.')
    rec.pdf(f'{BASE}/projects/{pid}/pdf', 'Full Quotation: every room, item and size.', pages=((0, 0.0), (1, 0.0)), hold=2.0)
    page.goto(quote_url)
    rec.scroll_to(page.locator('#approval'), 'Even better: let them accept online.')
    rec.tap(page.locator('#approval button', has_text='Create approval link'), 'Tap Create approval link.', wait=1000)
    # the box shows the public address in recordings; the customer browser opens the same link on the local copy
    link = page.locator('#approvalUrl').input_value().replace(Recorder.PUBLIC, BASE)
    rec.scroll_to(page.locator('#approval'), 'Send this link on WhatsApp.')
    rec.shot('Send the link on WhatsApp. Your customer needs no app or login.', 2.4)
    cust = browser.new_context(viewport=VIEW, device_scale_factor=DPR, is_mobile=True, has_touch=True).new_page()
    crec = Recorder(cust, rec.dir, 4, rec.title)
    crec.items = rec.items
    cust.goto(link)
    crec.shot("This is what your customer sees, in your brand.", 2.6)
    crec.scroll_to(cust.locator('#respond'), 'They tick the box and tap Accept.')
    crec.tap(cust.locator('#accAgree'), 'They tick the box and tap Accept.')
    crec.tap(cust.locator('#respond button[type=submit]').first, 'They tick the box and tap Accept.', wait=1200)
    cust.evaluate('window.scrollTo(0, 0)')
    crec.shot('Accepted!', 2.0)
    page.goto(quote_url)
    rec.shot('On your side: the quotation is now Confirmed, and you get a notification.', 3.0)
    rec.save()


def part5(page, quote_url):
    rec = Recorder(page, os.path.join(WORK, 'part5'), 5, 'Get paid')
    page.on('dialog', lambda d: d.accept())
    page.goto(quote_url)
    rec.scroll_to(page.locator('#payments'), 'Record payments as they come in.')
    rec.tap(page.locator('#payments button', has_text='Record Payment'), 'Tap Record Payment.', wait=700)
    rec.type(page.locator('#recordPaymentModal input[name=amount]'), '50000', 'Enter the amount, e.g. the advance.')
    rec.type(page.locator('#recordPaymentModal input[name=note]'), 'Advance via UPI', 'Add a note.')
    rec.tap(page.locator('#recordPaymentModal button[type=submit]'), 'Tap Save.', wait=1200)
    rec.scroll_to(page.locator('#payments'), 'Paid and balance update straight away.')
    rec.shot('Paid and balance update straight away.', 2.2)
    rec.scroll_to(page.locator('#invoice'), 'When the job is confirmed, make the invoice.')
    rec.tap(page.locator('#invoice button', has_text='Create invoice'), 'Tap Create invoice.', wait=700)
    rec.shot('With GST or without, room by room or by material.', 2.4)
    rec.tap(page.locator('#invoiceForm button', has_text='Issue invoice'), 'Tap Issue invoice.', wait=1500)
    rec.scroll_to(page.locator('#invoice'), 'Your invoice is ready to send.')
    rec.shot('Your invoice is ready: PDF, WhatsApp, or a link.', 2.2)
    pid = re.search(r'/projects/(\d+)', quote_url).group(1)
    inv_pdf = page.locator('#invoice a', has_text='PDF').first.get_attribute('href')
    rec.pdf(BASE + inv_pdf, 'A proper GST invoice, numbered for you.')
    page.goto(quote_url)
    rec.scroll_to(page.locator('#payments'), 'Something still due? Send a polite reminder.')
    rec.shot('Something still due? Send a reminder on WhatsApp in one tap.', 2.6)
    open_menu_item(rec, page, 'Balances', 'Open Balances to see everyone who still owes you.')
    rec.shot('Everyone who still owes you, biggest first.', 2.6)
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
        part2(page)
        quote_url = part3(page)
        part4(page, browser, quote_url)
        part5(page, quote_url)
        browser.close()


if __name__ == '__main__':
    run()
