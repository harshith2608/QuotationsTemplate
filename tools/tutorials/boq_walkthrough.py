"""Video: a turnkey BOQ made in QuoteRoom (laptop, 1920x1080, presentation style: see walkthrough.py).

Recreates a real bill of quantities from a JSON file kept OUTSIDE the repository (it holds a customer's details):
    {"company", "tagline", "customer": {"name", "mobile", "address"}, "discount", "notes", "payment_terms",
     "rooms": [{"name", "items": [{"name", "type": "boq", "quantity", "unit", "unit_price", "description"}]}]}
The first lines are picked from the business's saved BOQ lines (the starter set it gets when BOQ lines are turned
on), with pauses that explain them; the rest are added quickly. Recorded on a FRESH local business with BOQ lines on
(the script sets the company, BOQ layout, terms and notes through the app's settings).

    python tools/tutorials/boq_walkthrough.py http://localhost:5096 <workdir> <admin password> <quote.json>
    python tools/tutorials/boq_walkthrough.py --render <workdir>
"""
import json
import os
import sys

from recorder import OUT
from walkthrough import WIN, WIN_DPR, WalkRecorder, render

TITLE = 'A turnkey BOQ in QuoteRoom'
SUBTITLE = 'Every line with its description, quantity, unit and rate. The total works itself out.'
OUTRO = 'Try it free for 7 days: quote-room.co.in'
LABEL = 'BOQ walkthrough'
# Lines added through the Add Item window, per section (index): (saved line to pick, keep its description,
# explanation, tick "Save as my default"). The rest of each line comes from the JSON; other lines are added quickly.
PICKS = {
    0: [('False Ceiling', False, ('Changed for this quotation', ["This quotation's own breakdown",
                                                                 'Your saved default stays as it is']), False),
        ('Electric Wiring', True, None, False)],
    1: [('Fan Fitting', True, ('One line per item', ['Pick it, type the quantity', 'Quantity × rate, worked out for you']), False),
        ('Switch Board Shifting', True, None, False),
        ('Profile Light Fitting', True, ('Running feet too', ['175 R.ft × ₹100: no hand calculation']), False)],
}


def record(base, work, password, data_path):
    from playwright.sync_api import sync_playwright
    data = json.load(open(data_path))
    rooms = data['rooms']
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_context(viewport=WIN, device_scale_factor=WIN_DPR).new_page()
        rec = WalkRecorder(page, os.path.join(work, 'boq'), LABEL, TITLE)
        page.goto(base + '/login')
        page.fill('input[name=username]', 'admin')
        page.fill('input[name=password]', password)
        page.click('button[type=submit]')
        page.wait_for_timeout(800)

        # The business: name, BOQ layout, its terms and notes (set up before recording, through the real pages)
        page.goto(base + '/admin/settings?tab=company')
        page.fill('[name=company_name]', data['company'])
        page.fill('[name=company_tagline]', data.get('tagline', ''))
        if page.locator('#confirm_identity').count():
            page.check('#confirm_identity')
        page.get_by_role('button', name='Save Company Details').click()
        page.wait_for_timeout(600)
        page.goto(base + '/admin/settings?tab=documents')
        page.check('#il_boq')
        page.fill('textarea[name=payment_terms]', data.get('payment_terms', ''))
        page.fill('textarea[name=important_notes]', data.get('notes', ''))
        page.fill('textarea[name=terms_conditions]', '')
        page.fill('textarea[name=material_specs]', '')
        page.get_by_role('button', name='Save Quotation Settings').click()
        page.wait_for_timeout(800)

        rec.slide('Interiors & turnkey', 'A real 2 BHK BOQ, line by line', [
            'Description, quantity, unit and rate on every line',
            'Your saved lines fill in by themselves'])
        page.goto(base + '/admin/rates#boq-lines')
        page.wait_for_timeout(500)
        rec.scroll_to(page.locator('#boq-lines'), 'Admin → Rates → BOQ Lines.', offset=80)
        rec.explain(page.locator('#boq-lines table'), 'Your BOQ lines', ['Ready-made: false ceiling, wiring, wardrobe…',
                                                                         'Edit rates and descriptions any time'],
                    kicker='Admin → Rates')
        page.goto(base + '/admin/settings?tab=documents')
        rec.explain(page.locator('#il_boq').locator('xpath=ancestor::div[contains(@class,"card")][1]'),
                    'The BOQ layout', ['Sections A, B, C: your rooms', 'Sr. No., Qty, Unit, Rate, Amount'],
                    kicker='Settings → Quotation PDFs')

        # ── a new quotation ──
        page.goto(base + '/projects/new')
        rec.shot('New Quotation.', 1.2)
        c = data['customer']
        rec.type(page.locator('#customer_name'), c['name'], 'Customer name, mobile and address.', per_frame=4, hold=0.2)
        rec.type(page.locator('#mobile'), c['mobile'], 'Customer name, mobile and address.', per_frame=5, hold=0.2)
        if c.get('address'):
            rec.type(page.locator('[name=address]'), c['address'], 'Customer name, mobile and address.', per_frame=5, hold=0.6)

        def add_room(n, name, caption):
            if n == 1:
                rec.tap(page.locator('button', has_text='Add First Room').first, caption, wait=600, after_hold=0.2)
            else:
                rec.tap(page.locator('#add-room-btn-wrap button'), caption, wait=600, after_hold=0.2)
            rec.type(page.locator(f'#room_name_room_{n}'), name, caption, per_frame=4, hold=0.4)
            page.locator(f'#room_name_room_{n}').press('Escape')

        def picked_line(n, it, pick, keep_desc, explain, tick=False):
            caption = f"Add a BOQ line: {pick}."         # `it` has the same name: picked, then its quantity etc.
            rec.tap(page.locator(f'#room_card_room_{n} button', has_text='Add Item'), caption, wait=600, after_hold=0.2)
            rec.tap(page.locator('label[for=modal_type_boq]'), caption, after_hold=0.3)
            rec.type(page.locator('#modal_item_name'), pick[:5], caption, per_frame=2, hold=0.4)
            rec.tap(page.locator('.ki-ac-dropdown li', has_text=pick).first, caption, after_hold=0.5)
            after_edit = explain and (explain[0].startswith('Changed') or 'feet' in explain[0])   # explained after edits
            if explain and not after_edit:
                rec.explain(page.locator('#itemModal .modal-content'), *explain)
                explain = None
            page.locator('#modal_boq_qty').fill(str(it['quantity']))
            page.locator('#modal_boq_qty').dispatch_event('input')
            if not keep_desc and it.get('description'):
                page.locator('#modal_item_desc').fill(it['description'])
                page.locator('#modal_item_desc').dispatch_event('input')
            if it['unit_price'] and float(page.input_value('#modal_boq_rate') or 0) != it['unit_price']:
                rec.type(page.locator('#modal_boq_rate'), str(it['unit_price']), caption, per_frame=3, hold=0.3)
                page.locator('#modal_boq_rate').dispatch_event('input')
            page.wait_for_timeout(250)
            if explain:
                rec.explain(page.locator('#itemModal .modal-content'), *explain)
                if tick:
                    rec.tap(page.locator('#modal_boq_default'), 'Tick "Save as my default" to keep it for next time.', after_hold=0.6)
            else:
                rec.shot(caption, 1.2)
            rec.tap(page.locator('#itemModal .modal-footer button', has_text='Add Item'), caption, wait=600, after_hold=0.5)

        def quick_lines(n, items, caption):
            page.evaluate("""([rk, items]) => items.forEach(i => _insertBoqRow(rk, i.name, i.quantity, i.unit,
                                                                                i.unit_price, i.description || ''))""",
                          [f'room_{n}', items])
            page.wait_for_timeout(400)

        for r_i, room in enumerate(rooms):
            n = r_i + 1
            label = f"Section {chr(64 + n)}: {room['name']}."
            add_room(n, room['name'], label)
            picks = {pk[0].lower(): pk for pk in PICKS.get(r_i, [])}
            pending, quick_added = [], False
            for it in room['items']:                       # in order: picked lines through the window, others quickly
                pk = picks.get(it['name'].lower())
                if pk is None:
                    pending.append(it)
                    continue
                if pending:
                    quick_lines(n, pending, ''); pending, quick_added = [], True
                picked_line(n, it, *pk)
            if pending:
                quick_lines(n, pending, ''); quick_added = True
            if quick_added:
                caption = '…and the rest of the lines, the same way.' if picks else label
                rec.scroll_to(page.locator(f'#room_card_room_{n} tbody tr.item-row').last, caption, offset=420)
                rec.shot(caption, 1.4)
            if r_i == 1:
                rec.explain(page.locator(f'#room_card_room_{n}'), 'A section of its own', ['Every line adds up by itself',
                                                                                          'Saved for your next quotation'])
        if data.get('discount'):
            page.locator('#discount_type_select').select_option('fixed')
            page.locator('#discount_type_select').dispatch_event('change')
            rec.type(page.locator('#discount_value_input'), str(data['discount']), 'A discount, if you give one.', per_frame=3, hold=0.3)
        summary = page.locator('.card', has_text='Live Cost Summary').first
        rec.explain(summary, 'The total adds up as you go', ['Every line, then discount and total'])
        rec.tap(page.locator('button:visible', has_text='Save Quotation').last, 'Click Save Quotation.', wait=1800, after_hold=0.6)
        pid = page.url.rstrip('/').split('/')[-1]
        url = f'{base}/projects/{pid}/pdf/customer'
        import fitz
        pages = fitz.open(stream=page.request.get(url).body(), filetype='pdf').page_count
        rec.pdf_view(url, 'The PDF your customer gets: a clean BOQ in your brand.', 0, 0.0, hold=3.0)
        rec.pdf_view(url, 'Every line with its description, quantity, unit and rate.', 0, 1.0, hold=2.6)
        for pg in range(1, pages):
            rec.pdf_view(url, 'Sections, numbered lines, then the totals and your terms.', pg, 0.0, hold=2.4)
            rec.pdf_view(url, 'Sections, numbered lines, then the totals and your terms.', pg, 1.0, hold=2.2)
        rec.slide('Done', 'Your BOQ, in minutes', ['Send the PDF on WhatsApp, or a link they accept online'])
        rec.save()
        browser.close()


if __name__ == '__main__':
    if sys.argv[1] == '--render':
        os.makedirs(os.path.join(OUT, 'tutorials'), exist_ok=True)
        render(os.path.join(sys.argv[2], 'boq'), os.path.join(OUT, 'tutorials', 'quoteroom-boq-walkthrough.mp4'),
               SUBTITLE, OUTRO)
    else:
        record(*sys.argv[1:5])
