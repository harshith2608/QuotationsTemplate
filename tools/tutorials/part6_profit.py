"""Tutorial part 6: Know your profit (costs → profit on a quotation → Reports).

Continues on the local tutorial app after parts 1–5 (Anita Rao's quotation confirmed and invoiced). First adds two
quotations awaiting confirmation (not recorded) so Reports has open quotations to project from.

    python tools/tutorials/part6_profit.py http://localhost:5093 <workdir> <admin password>
"""
import os
import sys

from playwright.sync_api import sync_playwright

from recorder import DPR, VIEW, Recorder

BASE, WORK, PASSWORD = sys.argv[1], sys.argv[2], sys.argv[3]

# What things cost Sharma Interiors (round numbers, so the profit is easy to follow)
COSTS = [('Acrylic – Box Work', '750'), ('Laminates – Box Work', '560')]
FITTING_COSTS = [('Magic Corner', '11500')]

OPEN_QUOTES = [   # (customer, mobile, room, [(item, l_ft, w_ft, w_in, combo)])
    ('Vikram Reddy', '9848022338', 'Kitchen', [('Base Cabinet', '12', '2', '9', 'Acrylic|Box Work'),
                                               ('Overhead Cabinet', '12', '2', '6', 'Acrylic|Box Work')]),
    ('Meena Iyer', '9849011223', 'Master Bedroom', [('Wardrobe', '10', '7', '0', 'Laminates|Box Work'),
                                                    ('Loft', '10', '2', '0', 'Laminates|Box Work')]),
]


def add_open_quote(page, customer, mobile, room, items):
    """A quotation awaiting confirmation, made through the app (not recorded)."""
    page.goto(BASE + '/projects/new')
    page.fill('#customer_name', customer)
    page.fill('#mobile', mobile)
    page.click('#no-rooms-hint button')
    page.fill('#room_name_room_1', room)
    page.locator('#room_name_room_1').press('Escape')
    for name, l_ft, w_ft, w_in, combo in items:
        page.locator('#room_card_room_1 button', has_text='Add Item').click()
        page.wait_for_timeout(400)
        page.fill('#modal_item_name', name)
        for sel, val in (('#modal_item_lft', l_ft), ('#modal_item_lin', '0'), ('#modal_item_wft', w_ft), ('#modal_item_win', w_in)):
            page.fill(sel, val)
        page.locator('#modal_item_combo').select_option(combo)
        page.locator('#itemModal .modal-footer button', has_text='Add Item').click()
        page.wait_for_timeout(400)
    page.locator('button', has_text='Save Quotation').last.click()
    page.wait_for_timeout(1200)


def open_menu_item(rec, page, label, caption):
    rec.tap(page.locator('.navbar-toggler'), caption)
    rec.tap(page.locator('#navbarMain a.nav-link', has_text=label).last, caption, wait=900)


def slide_right(rec, page, nth, caption, steps=8):
    """Slide a wide table sideways (as a finger would) so its last columns, like profit, come into view."""
    for i in range(1, steps + 1):
        page.evaluate("([n, f]) => { const el = document.querySelectorAll('.table-responsive')[n];"
                      " el.scrollLeft = (el.scrollWidth - el.clientWidth) * f; }", [nth, i / steps])
        page.wait_for_timeout(40)
        rec._snap(caption, 0.06)


def cost_input(page, label):
    return page.locator('tr', has=page.locator('td', has_text=label)).locator('input[type=number]').first


def part6(page, quote_url):
    rec = Recorder(page, os.path.join(WORK, 'part6'), 6, 'Know your profit')
    page.goto(quote_url)
    rec.shot('How much do you actually make on this job?', 2.0)
    rec.scroll_to(page.locator('#profit'), 'Add your costs once and every quotation shows its profit.')
    rec.shot('Add your costs once and every quotation shows its profit.', 2.2)
    open_menu_item(rec, page, 'Costs & Profit', 'Open the menu → Costs & Profit.')
    rec.shot('Enter what each material costs you. Only admins ever see this.', 2.6)
    for label, value in COSTS:
        rec.type(cost_input(page, label), value, f'{label.split(" –")[0]} costs you ₹{int(value):,} per sqft.', per_frame=1)
    rec.scroll_to(page.locator('td', has_text=FITTING_COSTS[0][0]).first, 'Fittings too: what each piece costs you.')
    for label, value in FITTING_COSTS:
        rec.type(cost_input(page, label), value, f'A {label} costs you ₹{int(value):,}.', per_frame=1)
    rec.tap(page.get_by_role('button', name='Save costs'), 'Tap Save costs.', wait=1200)
    page.evaluate('window.scrollTo(0, 0)')
    rec.scroll_to(page.locator('table').first, 'Your margin on each material, at a glance.', offset=120)
    rec.shot('Your margin on each material, at a glance.', 2.6)
    page.goto(quote_url)
    rec.scroll_to(page.locator('#profit'), 'Back on the quotation: your profit on this job.')
    rec.shot('Your profit on this job, before GST: price before GST minus your costs.', 3.4)
    open_menu_item(rec, page, 'Reports', 'Open the menu → Reports for the whole business.')
    rec.shot('This financial year: work won, collected, invoiced and your profit.', 3.0)
    rec.scroll_to(page.get_by_text('Projected for', exact=False).first, 'Where the year is heading.', offset=110)
    rec.shot('Projected to 31 March, from your pace and your open quotations.', 3.0)
    rec.scroll_to(page.get_by_text('month by month', exact=False).first, 'Month by month…', offset=110)
    rec.scroll_to(page.locator('.table-responsive').nth(0), 'Month by month…', offset=330)
    slide_right(rec, page, 0, 'Month by month: won, collected, invoiced and profit.')
    rec.shot('Month by month: won, collected, invoiced and profit.', 2.6)
    rec.scroll_to(page.get_by_text('By financial year', exact=False).first, '…and year by year, as your business grows.', offset=110)
    slide_right(rec, page, 1, '…and year by year, as your business grows.')
    rec.shot('…and year by year, as your business grows.', 2.8)
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
        page.goto(BASE + '/projects')
        quote_url = BASE + page.locator('a[href^="/projects/"]', has_text='View').last.get_attribute('href')
        if page.get_by_text('Vikram Reddy').count() == 0:
            for q in OPEN_QUOTES:
                add_open_quote(page, *q)
        part6(page, quote_url)
        browser.close()


if __name__ == '__main__':
    run()
