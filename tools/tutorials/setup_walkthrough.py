"""Walkthrough video: a new business sets up QuoteRoom with the setup guide, up to the first quotation (laptop,
1920x1080, presentation style: see walkthrough.py).

Covers company details, logo, units, rates (materials and work types, a new material, plywood, fittings &
accessories), the quotation PDF, how customers pay, and a first quotation using all of it.

Recorded on a FRESH local business (admin only, as a new trial gets), e.g. on port 5095:
    python tools/tutorials/setup_walkthrough.py http://localhost:5095 <workdir> <admin password>
    python tools/tutorials/setup_walkthrough.py --render <workdir>
"""
import os
import sys

from PIL import Image, ImageDraw, ImageFont

from landscape import DESK, DESK_DPR
from recorder import DPR, OUT, VIEW, Recorder
from walkthrough import WalkRecorder, render

TITLE = 'Set up, step by step'
SUBTITLE = 'From your first sign-in to your first quotation, step by step.'
OUTRO = 'Start your 7-day free trial: quote-room.co.in'
LABEL = 'Setup walkthrough'


def make_logo(path):
    img = Image.new('RGBA', (600, 600), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([20, 20, 580, 580], radius=120, fill=(15, 118, 110))
    f = ImageFont.truetype('/System/Library/Fonts/Avenir Next.ttc', 300, index=8)
    d.text((300, 290), 'SI', font=f, fill=(255, 255, 255), anchor='mm')
    d.rectangle([150, 470, 450, 492], fill=(234, 179, 8))
    img.save(path)
    return path


def done_next(rec, page, caption='Press "Done, next step".'):
    page.evaluate('window.scrollTo(0, 0)')
    rec.tap(page.locator('.ki-setup-banner button', has_text='Done').first, caption, wait=1000, after_hold=1.2)


def rate_row(page, name):
    return page.locator('#materials tr', has=page.locator(f'input[value="{name}"]'))


def record(base, work, password):
    from playwright.sync_api import sync_playwright
    logo = make_logo(os.path.join(work, 'sharma-logo.png'))
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_context(viewport=DESK, device_scale_factor=DESK_DPR).new_page()
        rec = WalkRecorder(page, os.path.join(work, 'walk'), LABEL, TITLE)

        rec.slide('Interiors & turnkey', 'From sign-in to your first quotation', [
            'Your details, units and rates',
            'Woodwork, false ceiling, painting, electrical, civil'])

        # ── sign in → setup guide ──
        page.goto(base + '/login')
        rec.shot('Open the link from your welcome message.', 1.4)
        rec.type(page.locator('input[name=username]'), 'admin', 'Sign in with the username and password we sent you.')
        rec.type(page.locator('input[name=password]'), password, 'Sign in with the username and password we sent you.', per_frame=4)
        rec.tap(page.locator('button[type=submit]'), 'Click Sign In.', wait=1200)
        rec.explain([page.locator('h4', has_text='Setup guide').locator('xpath=..'), page.locator('#step-logo')],
                    'Your setup guide', ['7 short steps, each opens the right page',
                                         'Back any time from the Admin menu'], kicker='Getting started')
        rec.tap(page.locator('a, button', has_text='Start:').first, 'Click Start.', wait=1000)

        # ── 1. company ──
        rec.slide('Step 1 of 7', 'Your company details', ['On every quotation, invoice and message'])
        rec.explain(page.locator('.ki-setup-banner'), 'This bar guides you', ['Fill in, save, then "Done, next step"'])
        for name, value, caption in (
                ('company_name', 'Sharma Interiors', 'Your company name, as it should appear on quotations.'),
                ('company_mobile', '+91 98480 12345', 'Phone, email and GSTIN.'),
                ('company_email', 'hello@sharmainteriors.example', 'Phone, email and GSTIN.'),
                ('company_gstin', '36ABCDE1234F1Z5', 'Phone, email and GSTIN.')):
            rec.type(page.locator(f'[name={name}]'), value, caption, per_frame=4, hold=0.4)
        rec.type(page.locator('[name=company_address]'), 'Plot 21, Madhapur, Hyderabad 500081', 'Your address.', per_frame=6, hold=0.4)
        rec.scroll_to(page.locator('#confirm_identity'), 'Tick "These details are correct" and save.')
        rec.tap(page.locator('#confirm_identity'), 'Tick "These details are correct" and save.', after_hold=0.4)
        rec.tap(page.get_by_role('button', name='Save Company Details'), 'Tick "These details are correct" and save.', wait=1000)
        done_next(rec, page)

        # ── 2. logo & colours ──
        rec.slide('Step 2 of 7', 'Logo & colours', ['On the app and every PDF'])
        page.locator('#logoInput').set_input_files(logo)
        page.wait_for_timeout(600)
        rec.scroll_to(page.locator('#logoBox'), 'Upload your logo.')
        rec.tap(page.locator('#confirm_logo'), 'Upload your logo.', after_hold=0.4)
        rec.scroll_to(page.locator('#presetGrid'), 'Pick your brand colours.')
        rec.tap(page.locator('[data-preset="Teal"]'), 'Pick your brand colours.', after_hold=1.0)
        rec.tap(page.get_by_role('button', name='Save Appearance').first, 'Save.', wait=1400)
        done_next(rec, page)

        # ── 3. units ──
        rec.slide('Step 3 of 7', 'Your unit of measurement', ['Measure the way your team already does'])
        rec.explain(page.locator('.card', has_text='Units of measurement').first, 'Sizes and areas',
                    ['Feet & inches, mm, cm or inches', 'Rates per sqft or per sq m'])
        rec.tap(page.get_by_role('button', name='Save Units'), 'We keep feet & inches and sqft here. Save.', wait=1000)
        done_next(rec, page)

        # ── 4. rates ──
        rec.slide('Step 4 of 7', 'Your rates', ['By area: size × your rate', 'Per piece or lump sum: quantity × price'])
        rec.explain(page.locator('#materials table'), 'Materials & work types',
                    ['A rate for each material', 'Box Work and Frame Work can differ'])
        for name, box, frame in (('Acrylic', '1450', '1250'), ('Laminates', '950', '800'), ('Veneer', '1100', '950')):
            inputs = rate_row(page, name).locator('input[type=number]')
            rec.type(inputs.nth(0), box, 'Type your own rates.', per_frame=4, hold=0.2)
            rec.type(inputs.nth(1), frame, 'Type your own rates.', per_frame=4, hold=0.2)
        rec.tap(page.locator('button[name=item_rates_submit][value=save]'), 'Save Materials & Rates.', wait=1200)

        # new materials: glass for the kitchen, then turnkey work priced by area
        add_form = page.locator('#mat_name').locator('xpath=ancestor::form[1]')
        rec.scroll_to(page.locator('#mat_name'), 'Add anything you sell by area.', offset=260)
        rec.explain(add_form, 'Add your own materials', ['Glass, PU, wallpaper…', 'Turnkey work too: false ceiling, painting, flooring'])
        for name, rate, caption, typed in (('Lacquered Glass', '650', 'Lacquered Glass: ₹650 per sqft.', True),
                                           ('False Ceiling', '110', 'False Ceiling: ₹110 per sqft.', True),
                                           ('Painting', '28', 'Painting: ₹28 per sqft.', False)):
            if typed:
                rec.type(page.locator('#mat_name'), name, caption, per_frame=4, hold=0.2)
                rec.type(page.locator('#mat_rate'), rate, caption, per_frame=3, hold=0.4)
            else:
                page.locator('#mat_name').fill(name)
                page.locator('#mat_rate').fill(rate)
                rec.shot(caption, 0.8)
            rec.tap(add_form.locator('button[type=submit]').last, caption, wait=1100, after_hold=0.4)
            rec.scroll_to(page.locator('#mat_name'), caption, offset=330, steps=2)
        rec.explain([rate_row(page, 'Lacquered Glass'), rate_row(page, 'Painting')], 'Added',
                    ['One rate per sqft', 'Ready on every new quotation'])

        # plywood
        rec.scroll_to(page.locator('#plywood'), 'Next: the plywood you offer.', offset=90)
        rec.explain(page.locator('#plywood table'), 'Plywood', ['Rates above are for your default board',
                                                                'Others: the difference per sqft'])
        rec.type(page.locator('input[name=ply_new_name]'), '18mm BWP Marine', 'Add a board: 18mm BWP Marine, +₹150 per sqft.', per_frame=4, hold=0.2)
        rec.type(page.locator('input[name=ply_new_adj]'), '150', 'Add a board: 18mm BWP Marine, +₹150 per sqft.', per_frame=3, hold=0.6)
        rec.tap(page.locator('button[name=plywood_submit]'), 'Save Plywood.', wait=1200)

        # price list: fittings, and turnkey items per point or lump sum
        rec.scroll_to(page.locator('#price-list'), 'Last: your price list.', offset=90)
        rec.explain(page.locator('#price-list table'), 'Fittings & per-piece work',
                    ['Magic Corner, drawers, hinges…', 'Electrical points, lump-sum work'])
        magic = page.locator('#price-list tr', has=page.locator('input[value="Magic Corner"]')).locator('input[name=pl_price]')
        rec.type(magic, '16500', 'Change any price to yours.', per_frame=5, hold=0.5)
        for i, (name, price, unit, caption) in enumerate((
                ('Electrical Point', '850', 'point', 'Electrical Point: ₹850 a point.'),
                ('Demolition & Debris Removal', '25000', 'lump sum', 'Demolition: ₹25,000 lump sum.'))):
            row = page.locator('#price-list input[name=pl_name][placeholder]').nth(0).locator('xpath=ancestor::tr[1]')
            rec.type(row.locator('input[name=pl_name]'), name, caption, per_frame=5, hold=0.2)
            row.locator('input[name=pl_price]').fill(price)
            row.locator('input[name=pl_unit]').fill(unit)
            page.locator('#price-list input[name=pl_name][placeholder]').nth(0).evaluate('e => e.removeAttribute("placeholder")')
            rec.shot(caption, 0.9)
        rec.tap(page.locator('button[name=price_list_submit]'), 'Save Price List.', wait=1200)
        done_next(rec, page)

        # ── 5. quotation PDF ──
        rec.slide('Step 5 of 7', 'Your quotation PDF', ['Your terms, your words'])
        rec.explain(page.locator('.card', has_text='Initial Quotation').first, 'What the customer gets',
                    ['By room or by material', 'Full Quotation with every rate'])
        terms = page.locator('textarea[name=payment_terms]')
        if terms.count():
            rec.scroll_to(terms, 'Your payment terms, one per line.', offset=220)
            rec.type(terms, '10% advance with order confirmation\n50% after design sign-off\n40% on delivery to site',
                     'Your payment terms, one per line. Delivery terms and notes the same way.', per_frame=12, hold=1.2)
        rec.tap(page.get_by_role('button', name='Save Quotation Settings'), 'Save.', wait=1200)
        done_next(rec, page)

        # ── 6. payments ──
        rec.slide('Step 6 of 7', 'How customers pay you', ['UPI and bank, on quotations and invoices'])
        rec.type(page.locator('[name=upi_id]'), 'sharmainteriors@okhdfcbank', 'Your UPI ID and bank details.', per_frame=6, hold=0.2)
        for name, value in (('account_name', 'Sharma Interiors'), ('bank_name', 'HDFC Bank'),
                            ('account_number', '50200012345678'), ('ifsc_code', 'HDFC0001234')):
            loc = page.locator(f'[name={name}]')
            if loc.count():
                loc.fill(value)
        rec.shot('Your UPI ID and bank details.', 1.0)
        rec.tap(page.locator('button[type=submit]', has_text='Save').last, 'Save. (Online payments with Razorpay are optional.)', wait=1200)
        done_next(rec, page)

        # ── 7. first quotation ──
        rec.slide('Step 7 of 7', 'Your first quotation', ['A kitchen, a living room and civil work'])
        if '/projects/new' not in page.url:
            page.goto(base + '/projects/new')
        rec.type(page.locator('#customer_name'), 'Kavya Menon', 'Customer name and mobile.', per_frame=4, hold=0.2)
        rec.type(page.locator('#mobile'), '9000012345', 'Customer name and mobile.', per_frame=5, hold=0.4)
        rec.explain(page.locator('.card', has_text='Plywood').first, 'Plywood for this quotation',
                    ['Your default is picked', 'Change it: board items re-price'])

        def add_room(n, name, caption):
            if n == 1:
                rec.tap(page.locator('button', has_text='Add First Room').first, caption, wait=600, after_hold=0.2)
            else:
                rec.tap(page.locator('#add-room-btn-wrap button'), caption, wait=600, after_hold=0.2)
            rec.type(page.locator(f'#room_name_room_{n}'), name, caption, per_frame=4, hold=0.3)
            page.locator(f'#room_name_room_{n}').press('Escape')

        def combo_for(text):
            opts = page.locator('#modal_item_combo option').all()
            for o in opts:
                if o.inner_text().strip().startswith(text):
                    return o.get_attribute('value')
            raise RuntimeError(f'no material {text}')

        def open_item(n, caption):
            rec.tap(page.locator(f'#room_card_room_{n} button', has_text='Add Item'), caption, wait=600, after_hold=0.2)

        def measured(n, name, l_ft, l_in, w_ft, w_in, combo, caption, explain=None):
            open_item(n, caption)
            rec.type(page.locator('#modal_item_name'), name, caption, per_frame=4, hold=0.2)
            for sel, val in (('#modal_item_lft', l_ft), ('#modal_item_lin', l_in), ('#modal_item_wft', w_ft), ('#modal_item_win', w_in)):
                page.locator(sel).fill(val)
            page.locator('#modal_item_combo').select_option(combo_for(combo))
            page.locator('#modal_item_combo').dispatch_event('change')
            page.wait_for_timeout(400)
            if explain:
                rec.explain(page.locator('#itemModal .modal-content'), *explain)
            else:
                rec.shot(caption, 1.0)
            rec.tap(page.locator('#itemModal .modal-footer button', has_text='Add Item'), caption, wait=600, after_hold=0.3)

        def fixed(n, name, qty, caption, explain=None):
            open_item(n, caption)
            rec.tap(page.locator('label[for=modal_type_fixed]'), caption, after_hold=0.2)
            rec.type(page.locator('#modal_item_name'), name[:5], caption, per_frame=2, hold=0.3)
            sug = page.locator('.ki-ac-dropdown li', has_text=name).first
            if sug.count():
                rec.tap(sug, caption, after_hold=0.3)
            else:
                page.locator('#modal_item_name').fill(name)
            page.locator('#modal_item_qty').fill(qty)
            page.locator('#modal_item_qty').dispatch_event('input')
            page.wait_for_timeout(300)
            if explain:
                rec.explain(page.locator('#itemModal .modal-content'), *explain)
            else:
                rec.shot(caption, 1.0)
            rec.tap(page.locator('#itemModal .modal-footer button', has_text='Add Item'), caption, wait=600, after_hold=0.3)

        add_room(1, 'Kitchen', 'Add a room: Kitchen.')
        measured(1, 'Base Cabinet', '10', '0', '2', '9', 'Acrylic – Box', 'Add each item with its size.',
                 ('A measured item', ['Size in your unit, then the material', 'Area and amount work themselves out']))
        measured(1, 'Overhead Cabinet', '10', '0', '2', '6', 'Laminates – Box', 'Add each item with its size.')
        measured(1, 'Back-splash', '10', '0', '2', '0', 'Lacquered Glass', 'Your new material: Lacquered Glass.')
        fixed(1, 'Magic Corner', '1', 'Fittings: Fixed price, pick from your list.',
              ('Fittings', ['Pick from your price list', 'Quantity × price']))

        add_room(2, 'Living Room', 'Next room: Living Room.')
        measured(2, 'False Ceiling', '14', '0', '12', '0', 'False Ceiling', 'False ceiling, by area.',
                 ('Turnkey work by area', ['False ceiling at your rate per sqft', 'Painting and flooring the same way']))
        measured(2, 'Wall Painting', '46', '0', '10', '0', 'Painting', 'Painting: 46 ft of wall, 10 ft high.')
        fixed(2, 'Electrical Point', '12', 'Electrical: 12 points.',
              ('Per point', ['12 points × ₹850', 'Any per-piece work: lights, fixtures']))

        add_room(3, 'Civil Work', 'Group work your way, e.g. Civil Work.')
        fixed(3, 'Demolition & Debris Removal', '1', 'Demolition: one lump sum.',
              ('Lump sum', ['Quantity 1 at the agreed amount', 'Rooms can be trades: Civil, Electrical…']))

        summary = page.locator('.card', has_text='Live Cost Summary').first
        rec.explain(summary, 'The total adds up as you go', ['Room by room, with an optional discount'])
        rec.tap(page.locator('button:visible', has_text='Save Quotation').last, 'Click Save Quotation.', wait=1600, after_hold=0.6)
        pid = page.url.rstrip('/').split('/')[-1]
        rec.pdf(f'{base}/projects/{pid}/pdf/customer', 'Your branded PDF, ready to send on WhatsApp.', hold=3.0)

        # ── the customer accepts online ──
        quote_url = f'{base}/projects/{pid}'
        page.goto(quote_url)
        rec.scroll_to(page.locator('#approval'), 'Or send a link your customer accepts online.', offset=200)
        rec.tap(page.locator('#approval button', has_text='Create approval link'), 'Click Create approval link…', wait=1000)
        link = page.locator('#approvalUrl').input_value().replace(Recorder.PUBLIC, base)
        rec.explain(page.locator('#approval'), 'Approval link', ['Send it on WhatsApp', 'Your customer accepts online'],
                    kicker='Getting a yes')
        cust = browser.new_context(viewport=VIEW, device_scale_factor=DPR, is_mobile=True, has_touch=True).new_page()
        crec = Recorder(cust, rec.dir, rec.chapter, rec.title)
        crec.items = rec.items
        cust.goto(link)
        crec.shot('Kavya opens it on her phone. No app, no login.', 2.2)
        crec.scroll_to(cust.get_by_text('Living Room').first, 'Every room and item, with sizes…', offset=160)
        crec.shot('Every room and item, with sizes…', 1.6)
        crec.scroll_to(cust.locator('#respond'), 'She ticks the box and taps Accept.', offset=200)
        crec.tap(cust.locator('#accAgree'), 'She ticks the box and taps Accept.', after_hold=0.3)
        crec.tap(cust.locator('#respond button[type=submit]').first, 'She ticks the box and taps Accept.', wait=1200, after_hold=0.4)
        cust.evaluate('window.scrollTo(0, 0)')
        crec.shot('Accepted!', 1.6)
        page.goto(quote_url)
        rec.shot('Back on your laptop: Confirmed, with a notification.', 2.6)

        rec.slide('You are set up', 'Next quotations take minutes', ['Measure, quote, send, get a yes'])
        rec.save()
        browser.close()


if __name__ == '__main__':
    if sys.argv[1] == '--render':
        os.makedirs(os.path.join(OUT, 'tutorials'), exist_ok=True)
        render(os.path.join(sys.argv[2], 'walk'), os.path.join(OUT, 'tutorials', 'quoteroom-setup-walkthrough.mp4'),
               SUBTITLE, OUTRO)
    else:
        record(*sys.argv[1:4])
