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
from recorder import OUT
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

        rec.slide('What we will do', 'From sign-in to your first quotation', [
            'Your company details, logo and colours',
            'Your unit of measurement',
            'Your rates: materials, plywood, fittings & accessories',
            'Your quotation PDF and how customers pay you',
            'Then a real quotation, using all of it'])

        # ── sign in → setup guide ──
        page.goto(base + '/login')
        rec.shot('Open the link from your welcome message.', 2.0)
        rec.type(page.locator('input[name=username]'), 'admin', 'Sign in with the username and password we sent you.')
        rec.type(page.locator('input[name=password]'), password, 'Sign in with the username and password we sent you.', per_frame=4)
        rec.tap(page.locator('button[type=submit]'), 'Click Sign In.', wait=1200)
        rec.explain([page.locator('h4', has_text='Setup guide').locator('xpath=..'), page.locator('#step-logo')],
                    'Your setup guide', [
                        'Opens by itself the first time you sign in',
                        'Seven short steps; each one opens the right page',
                        'Come back any time: Admin menu, Setup guide'], kicker='Getting started')
        rec.tap(page.locator('a, button', has_text='Start:').first, 'Click Start.', wait=1000)

        # ── 1. company ──
        rec.slide('Step 1 of 7', 'Your company details', [
            'Printed on every quotation, invoice and WhatsApp message',
            'Name and GSTIN lock once saved, so check them'], hold=5.5)
        rec.explain(page.locator('.ki-setup-banner'), 'This bar guides you', [
            'Which step you are on',
            'Fill in the page, save, then "Done, next step"'])
        for name, value, caption in (
                ('company_name', 'Sharma Interiors', 'Your company name, as it should appear on quotations.'),
                ('company_mobile', '+91 98480 12345', 'Your phone number.'),
                ('company_email', 'hello@sharmainteriors.example', 'Your email.'),
                ('company_gstin', '36ABCDE1234F1Z5', 'Your GSTIN, only if you give GST invoices.')):
            rec.type(page.locator(f'[name={name}]'), value, caption, per_frame=3)
        rec.type(page.locator('[name=company_address]'), 'Plot 21, Madhapur, Hyderabad 500081', 'Your address.', per_frame=4)
        rec.scroll_to(page.locator('#confirm_identity'), 'Tick "These details are correct" and save.')
        rec.tap(page.locator('#confirm_identity'), 'Tick "These details are correct" and save.', after_hold=0.6)
        rec.tap(page.get_by_role('button', name='Save Company Details'), 'Tick "These details are correct" and save.', wait=1000)
        done_next(rec, page)

        # ── 2. logo & colours ──
        rec.slide('Step 2 of 7', 'Logo & colours', ['Your logo and colours on the app and on every PDF'], hold=4.0)
        page.locator('#logoInput').set_input_files(logo)
        page.wait_for_timeout(600)
        rec.scroll_to(page.locator('#logoBox'), 'Upload your logo (PNG or JPG).')
        rec.shot('Upload your logo (PNG or JPG).', 1.6)
        rec.tap(page.locator('#confirm_logo'), 'Tick "This is my company\'s logo".', after_hold=0.6)
        rec.scroll_to(page.locator('#presetGrid'), 'Pick your brand colours.')
        rec.tap(page.locator('[data-preset="Teal"]'), 'Pick your brand colours.', after_hold=1.4)
        rec.tap(page.get_by_role('button', name='Save Appearance').first, 'Save.', wait=1400)
        done_next(rec, page)

        # ── 3. units ──
        rec.slide('Step 3 of 7', 'Your unit of measurement', ['Measure the way your team already does'], hold=4.0)
        rec.explain(page.locator('.card', has_text='Units of measurement').first, 'Sizes and areas', [
            'Feet & inches, mm, cm or inches',
            'Rates per sqft or per sq m',
            'Change it later and nothing is lost: sizes are only shown differently'])
        rec.tap(page.get_by_role('button', name='Save Units'), 'We keep feet & inches and sqft here. Save.', wait=1000)
        done_next(rec, page)

        # ── 4. rates ──
        rec.slide('Step 4 of 7', 'Your rates', [
            'Every measured item: area × your rate',
            'The rate depends on the material and the work type',
            'Fittings & accessories: quantity × price',
            'Set them once; every quotation uses them'])
        rec.explain(page.locator('#materials table'), 'Materials & work types', [
            'One row per material: Acrylic, Laminates, Veneer…',
            'Box Work and Frame Work can have different rates',
            '"On plywood": the material is priced on the plywood you choose'])
        for name, box, frame in (('Acrylic', '1450', '1250'), ('Laminates', '950', '800'), ('Veneer', '1100', '950')):
            inputs = rate_row(page, name).locator('input[type=number]')
            rec.type(inputs.nth(0), box, f'Type your own rates: {name}.', per_frame=4, hold=0.4)
            rec.type(inputs.nth(1), frame, f'Type your own rates: {name}.', per_frame=4, hold=0.4)
        rec.tap(page.locator('button[name=item_rates_submit][value=save]'), 'Save Materials & Rates.', wait=1200)

        # a new material
        rec.scroll_to(page.locator('#mat_name'), 'Need something else? Add your own material.', offset=260)
        rec.explain(page.locator('#mat_name').locator('xpath=ancestor::form[1]'), 'Add your own material', [
            'Glass, PU, Duco, Wallpaper, Mirror… anything you sell by area',
            'One rate, or separate Box Work and Frame Work rates',
            'Tick "Priced on plywood" if it is built on a board'])
        rec.type(page.locator('#mat_name'), 'Lacquered Glass', 'Example: Lacquered Glass for a kitchen back-splash.', per_frame=3)
        rec.type(page.locator('#mat_rate'), '650', 'One rate: ₹650 per sqft.', per_frame=3)
        rec.tap(page.locator('#mat_name').locator('xpath=ancestor::form[1]').locator('button[type=submit]').last,
                'Click Add.', wait=1200)
        rec.explain(rate_row(page, 'Lacquered Glass'), 'Added', [
            'Ready to pick on every new quotation',
            'Hide a material you stop offering: old quotations keep it'])

        # plywood
        rec.scroll_to(page.locator('#plywood'), 'Next: the plywood you offer.', offset=90)
        rec.explain(page.locator('#plywood table'), 'Plywood', [
            'Your rates above are for the default plywood',
            'For other boards, enter the difference per sqft, e.g. +150',
            'Each quotation picks its plywood; the customer sees the final rate'])
        new_ply = page.locator('input[name=ply_new_name]')
        rec.type(new_ply, '18mm BWP Marine', 'Add a board you offer: 18mm BWP Marine…', per_frame=3)
        rec.type(page.locator('input[name=ply_new_adj]'), '150', '…₹150 per sqft more than the default.', per_frame=3)
        if page.locator('input[name=ply_new_details]').count():
            rec.type(page.locator('input[name=ply_new_details]'), 'Century Club Prime, 15-year warranty',
                     'Details for your Material Specifications (optional).', per_frame=5)
        rec.tap(page.locator('button[name=plywood_submit]'), 'Save Plywood.', wait=1200)

        # fittings & accessories
        rec.scroll_to(page.locator('#price-list'), 'Last: fittings & accessories.', offset=90)
        rec.explain(page.locator('#price-list table'), 'Fittings & accessories', [
            'Priced per piece, not by area',
            'Magic Corner, tandem drawers, hinges, profile lights…',
            'On a quotation, pick one and its price fills in'])
        magic = page.locator('#price-list tr', has=page.locator('input[value="Magic Corner"]')).locator('input[name=pl_price]')
        rec.type(magic, '16500', 'Change any price to yours.', per_frame=5)
        new_row = page.locator('#price-list input[name=pl_name][placeholder]').first
        rec.type(new_row, 'Soft-close Hinge', 'Add your own: Soft-close Hinge…', per_frame=3)
        new_tr = new_row.locator('xpath=ancestor::tr[1]')
        rec.type(new_tr.locator('input[name=pl_price]'), '180', '…₹180 a piece.', per_frame=3)
        rec.tap(page.locator('button[name=price_list_submit]'), 'Save Price List.', wait=1200)
        done_next(rec, page)

        # ── 5. quotation PDF ──
        rec.slide('Step 5 of 7', 'Your quotation PDF', [
            'What your customer receives',
            'Your terms, your words'], hold=4.5)
        rec.explain(page.locator('.card', has_text='Initial Quotation').first, 'Two quotations', [
            'Initial Quotation for the customer: by room or by material',
            'Full Quotation with every rate and amount, when you need it'])
        terms = page.locator('textarea[name=payment_terms]')
        if terms.count():
            rec.scroll_to(terms, 'Your payment terms, one per line.', offset=220)
            rec.type(terms, '10% advance with order confirmation\n50% after design sign-off\n40% on delivery to site',
                     'Your payment terms, one per line.', per_frame=8)
            rec.explain(terms.locator('xpath=ancestor::*[contains(@class,"card")][1]'), 'Terms and notes', [
                'Payment terms, delivery terms, notes, terms & conditions',
                'Leave a box empty to leave it out',
                'Insert adds details that change per quotation, like the plywood'])
        rec.tap(page.get_by_role('button', name='Save Quotation Settings'), 'Save.', wait=1200)
        done_next(rec, page)

        # ── 6. payments ──
        rec.slide('Step 6 of 7', 'How customers pay you', ['Printed on your quotations and invoices'], hold=4.0)
        rec.type(page.locator('[name=upi_id]'), 'sharmainteriors@okhdfcbank', 'Your UPI ID…', per_frame=4)
        for name, value in (('account_name', 'Sharma Interiors'), ('bank_name', 'HDFC Bank'),
                            ('account_number', '50200012345678'), ('ifsc_code', 'HDFC0001234')):
            loc = page.locator(f'[name={name}]')
            if loc.count():
                rec.type(loc, value, '…and your bank details.', per_frame=4, hold=0.3)
        rec.explain([page.locator('[name=upi_id]').locator('xpath=ancestor::*[contains(@class,"card")][1]'),
                     page.locator('[name=ifsc_code]').locator('xpath=ancestor::*[contains(@class,"card")][1]')], 'Getting paid', [
            'Customers pay you directly: UPI or bank transfer',
            'Online card and UPI payments with Razorpay are optional'])
        rec.tap(page.locator('button[type=submit]', has_text='Save').last, 'Save.', wait=1200)
        done_next(rec, page)

        # ── 7. first quotation ──
        rec.slide('Step 7 of 7', 'Your first quotation', [
            'A kitchen with cabinets, a glass back-splash and fittings',
            'Your rates fill in by themselves'], hold=5.0)
        if '/projects/new' not in page.url:
            page.goto(base + '/projects/new')
        rec.type(page.locator('#customer_name'), 'Kavya Menon', 'Customer name and mobile.', per_frame=3)
        rec.type(page.locator('#mobile'), '9000012345', 'Customer name and mobile.', per_frame=4)
        rec.explain(page.locator('.card', has_text='Plywood').first, 'Plywood for this quotation', [
            'Your default is picked',
            'Choose BWP Marine and every board item is re-priced'])
        rec.tap(page.locator('#no-rooms-hint button, button', has_text='Add First Room').first, 'Add a room.', wait=600)
        rec.type(page.locator('#room_name_room_1'), 'Kitchen', 'Add a room: Kitchen.', per_frame=3)
        page.locator('#room_name_room_1').press('Escape')

        def measured(name, l_ft, l_in, w_ft, w_in, combo, caption, explain=None):
            rec.tap(page.locator('#room_card_room_1 button', has_text='Add Item'), caption, wait=600, after_hold=0.4)
            rec.type(page.locator('#modal_item_name'), name, caption, per_frame=3)
            for sel, val in (('#modal_item_lft', l_ft), ('#modal_item_lin', l_in), ('#modal_item_wft', w_ft), ('#modal_item_win', w_in)):
                page.locator(sel).fill(val)
            page.locator('#modal_item_combo').select_option(label=combo) if not '|' in combo else page.locator('#modal_item_combo').select_option(combo)
            page.wait_for_timeout(400)
            if explain:
                rec.explain(page.locator('#itemModal .modal-content'), *explain)
            else:
                rec.shot(caption, 1.6)
            rec.tap(page.locator('#itemModal .modal-footer button', has_text='Add Item'), caption, wait=600, after_hold=0.6)

        measured('Base Cabinet', '10', '0', '2', '9', 'Acrylic|Box Work', 'Add each item with its size.',
                 ('A measured item', ['Length and width in your unit',
                                      'Pick the material and work type',
                                      'The area and the amount work themselves out']))
        measured('Overhead Cabinet', '10', '0', '2', '6', 'Laminates|Box Work', 'Add each item with its size.')
        combos = page.locator('#modal_item_combo option').all_inner_texts()
        glass = next((c for c in combos if 'Lacquered Glass' in c), 'Lacquered Glass')
        measured('Back-splash', '10', '0', '2', '0', glass, 'Your new material is there: Lacquered Glass.',
                 ('Your new material', ['Lacquered Glass, at the rate you set', 'Not on plywood: one rate per sqft']))

        def fixed(name, qty, caption, explain=None):
            rec.tap(page.locator('#room_card_room_1 button', has_text='Add Item'), caption, wait=600, after_hold=0.3)
            rec.tap(page.locator('label[for=modal_type_fixed]'), caption, after_hold=0.4)
            rec.type(page.locator('#modal_item_name'), name[:6], caption, per_frame=2)
            sug = page.locator('.ki-ac-dropdown li', has_text=name).first
            if sug.count():
                rec.tap(sug, caption, after_hold=0.5)
            else:
                page.locator('#modal_item_name').fill(name)
            page.locator('#modal_item_qty').fill(qty)
            page.locator('#modal_item_qty').dispatch_event('input')
            page.wait_for_timeout(300)
            if explain:
                rec.explain(page.locator('#itemModal .modal-content'), *explain)
            else:
                rec.shot(caption, 1.6)
            rec.tap(page.locator('#itemModal .modal-footer button', has_text='Add Item'), caption, wait=600, after_hold=0.6)

        fixed('Magic Corner', '1', 'Fittings: choose Fixed price.',
              ('Fittings & accessories', ['"Fixed price", then pick from your price list', 'The price fills in; quantity × price']))
        fixed('Soft-close Hinge', '16', 'Soft-close hinges: 16 pieces.')
        rec.explain(page.locator('#room_card_room_1'), 'The whole kitchen', [
            'Cabinets by area, glass at its own rate, fittings per piece',
            'Edit or remove any item before you save'])
        summary = page.locator('.card', has_text='Live Cost Summary').first
        rec.explain(summary, 'The total adds up as you go', [
            'Room by room, with an optional discount',
            'Your rates, every time: no calculator'])
        rec.tap(page.locator('button:visible', has_text='Save Quotation').last, 'Click Save Quotation.', wait=1600, after_hold=1.0)
        pid = page.url.rstrip('/').split('/')[-1]
        rec.pdf(f'{base}/projects/{pid}/pdf/customer', 'Your branded PDF, ready to send on WhatsApp.', hold=3.4)

        rec.slide('You are set up', 'Next quotations take minutes', [
            'Your details, logo, rates and terms are saved',
            'Rooms and items, and the total works itself out',
            'Send the PDF or a link your customer accepts online',
            'The setup guide stays in the Admin menu'])
        rec.save()
        browser.close()


if __name__ == '__main__':
    if sys.argv[1] == '--render':
        os.makedirs(os.path.join(OUT, 'tutorials'), exist_ok=True)
        render(os.path.join(sys.argv[2], 'walk'), os.path.join(OUT, 'tutorials', 'quoteroom-setup-walkthrough.mp4'),
               SUBTITLE, OUTRO)
    else:
        record(*sys.argv[1:4])
