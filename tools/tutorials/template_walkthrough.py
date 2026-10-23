"""Video: starting quotations (templates) in QuoteRoom (laptop, 1920x1080, presentation style: see walkthrough.py).

Recorded on a FRESH local business priced by item with the fictional sample in template_sample.json (its items and
two starting quotations, as the console's Load price list sets a firm up). The screenshots are also used by the
social media reel (tools/ad_video/reel_templates.py).

    python tools/tutorials/template_walkthrough.py http://localhost:5097 <workdir> <admin password>
    python tools/tutorials/template_walkthrough.py --render <workdir>
"""
import os
import sys

from recorder import OUT
from walkthrough import WIN, WIN_DPR, WalkRecorder, render

TITLE = 'Starting quotations'
SUBTITLE = 'Start every quotation already filled in. Type the sizes, and it is ready to send.'
OUTRO = 'Try it free for 7 days: quote-room.co.in'
LABEL = 'Starting quotations'
COMPANY, TAGLINE = 'Nest & Grain Interiors', 'Homes, made to measure'

IK = """([room, name]) => {
  const card = [...document.querySelectorAll('.room-card')].find(c => c.querySelector('input[id^=room_name_]').value === room);
  const ta = [...card.querySelectorAll('textarea.ki-name')].find(t => t.value === name);
  return ta.id.replace('item_name_', '');
}"""
QUICK = """([ik, vals]) => Object.entries(vals).forEach(([id, v]) => {
  const el = document.getElementById(id.replace('IK', ik)); el.value = v; el.dispatchEvent(new Event('input', {bubbles: true}));
})"""


def record(base, work, password):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_context(viewport=WIN, device_scale_factor=WIN_DPR).new_page()
        rec = WalkRecorder(page, os.path.join(work, 'templates'), LABEL, TITLE)
        page.on('dialog', lambda d: d.accept('3 BHK premium') if d.type == 'prompt' else d.accept())
        page.goto(base + '/login')
        page.fill('input[name=username]', 'admin')
        page.fill('input[name=password]', password)
        page.click('button[type=submit]')
        page.wait_for_timeout(800)
        # the business's name (set up before recording, through the real page)
        page.goto(base + '/admin/settings?tab=company')
        page.fill('[name=company_name]', COMPANY)
        page.fill('[name=company_tagline]', TAGLINE)
        if page.locator('#confirm_identity').count():
            page.check('#confirm_identity')
        page.get_by_role('button', name='Save Company Details').click()
        page.wait_for_timeout(600)

        ik = lambda room, name: page.evaluate(IK, [room, name])
        quick = lambda room, name, vals: page.evaluate(QUICK, [ik(room, name), vals])

        def size(room, name, l, w, caption, l_in='', w_in=''):
            k = ik(room, name)
            rec.type(page.locator(f'#boq_{k}_lft'), str(l), caption, per_frame=2, hold=0.1)
            if l_in:
                rec.type(page.locator(f'#boq_{k}_lin'), str(l_in), caption, per_frame=2, hold=0.1)
            rec.type(page.locator(f'#boq_{k}_wft'), str(w), caption, per_frame=2, hold=0.1)
            if w_in:
                rec.type(page.locator(f'#boq_{k}_win'), str(w_in), caption, per_frame=2, hold=0.1)
            page.wait_for_timeout(150)
            return k

        rec.slide('Starting quotations', 'Start every quotation already filled in', [
            'Your usual rooms, items, descriptions and rates',
            'You only type the sizes for this home'])

        # ── New Quotation: the starting quotations come first ──
        page.goto(base + '/projects/new')
        page.wait_for_timeout(500)
        rec.shot('New Quotation.', 1.0)
        rec.explain(page.locator('.ki-start-cards'), 'Your starting quotations', [
            'Made from your own quotations', 'One click and everything is filled in'], kicker='New Quotation')
        rec.tap(page.locator('.ki-start-cards a', has_text='2 BHK turnkey'), 'Pick "2 BHK turnkey".', wait=1200, after_hold=0.4)
        rec.explain(page.locator('#room_card_room_1'), 'Every line is ready', [
            'Description and rate from your list', 'Highlighted: waiting for its size'], kicker='2 BHK turnkey')

        rec.type(page.locator('#customer_name'), 'Rohan Kapoor', 'The customer\'s name and mobile.', per_frame=4, hold=0.1)
        rec.type(page.locator('#mobile'), '9876500011', 'The customer\'s name and mobile.', per_frame=5, hold=0.5)

        # ── Services: quantities ──
        k = ik('Services', 'False Ceiling')
        rec.scroll_to(page.locator(f'#item_row_{k}'), 'Type the quantity…', offset=160)
        rec.type(page.locator(f'#item_qty_{k}'), '650', 'Type the quantity…', per_frame=1, hold=0.3)
        k2 = ik('Services', 'Electrical Wiring')
        rec.type(page.locator(f'#item_qty_{k2}'), '45', 'Type the quantity…', per_frame=1, hold=0.3)
        quick('Services', 'Painting', {'item_qty_IK': 1850})
        rec.explain(page.locator(f'#item_row_{k}'), 'The amount works itself out', [
            '650 sqft × ₹120 = ₹78,000', 'Lump sums are already done'])

        # ── Living Room: sizes ──
        k = ik('Living Room', 'Safety Door')
        rec.scroll_to(page.locator(f'#item_row_{k}'), '…or the size.', offset=140)
        size('Living Room', 'Safety Door', 3, 7, '…or the size.')
        size('Living Room', 'TV Unit', 6, 7, '…or the size.', l_in='6')
        quick('Living Room', 'Shoe Rack', {'boq_IK_lft': 3, 'boq_IK_wft': 3})
        quick('Living Room', 'Wall Paneling', {'boq_IK_lft': 10, 'boq_IK_wft': 8})
        k = ik('Living Room', 'TV Unit')
        rec.explain([page.locator(f'#item_row_{k}'), page.locator(f'#item_descrow_{k}')], 'Size in, amount out', [
            '6 ft 6 in × 7 ft = 45.5 sqft', '× ₹1,400 = ₹63,700'])
        # not needed in this home: remove it
        k = ik('Living Room', 'Mandir')
        rec.tap(page.locator(f'#item_row_{k} .btn-remove-item'), 'Not needed here? Remove it.', after_hold=0.6)
        # something extra: Add line
        add = page.locator('#room_card_room_2 button', has_text='Add line')
        rec.tap(add, 'Something extra? Add line.', wait=500, after_hold=0.3)
        name = page.locator('#room_card_room_2 tbody tr.item-row').last.locator('textarea.ki-name')
        rec.type(name, 'crock', 'Type a few letters and pick it.', per_frame=2, hold=0.3)
        rec.tap(page.locator('.ki-ac-dropdown li', has_text='Crockery Unit').first, 'Type a few letters and pick it.', after_hold=0.4)
        new_ik = name.get_attribute('id').replace('item_name_', '')
        rec.type(page.locator(f'#boq_{new_ik}_lft'), '4', 'Its rate and description fill in.', per_frame=1, hold=0.1)
        rec.type(page.locator(f'#boq_{new_ik}_wft'), '7', 'Its rate and description fill in.', per_frame=1, hold=0.6)

        # ── the rest, quickly ──
        quick('Kitchen', 'Kitchen Base Units', {'boq_IK_lft': 11, 'boq_IK_wft': 3})
        quick('Kitchen', 'Kitchen Wall Units', {'boq_IK_lft': 11, 'boq_IK_wft': 2, 'boq_IK_win': 6})
        quick('Kitchen', 'Loft Shutters', {'boq_IK_lft': 11, 'boq_IK_wft': 1, 'boq_IK_win': 6})
        quick('Kitchen', 'Tall Unit', {'boq_IK_lft': 2, 'boq_IK_wft': 7})
        quick('Master Bedroom', 'Wardrobe', {'boq_IK_lft': 8, 'boq_IK_wft': 8})
        quick('Master Bedroom', 'Bed with Storage', {'boq_IK_lft': 6, 'boq_IK_lin': 6, 'boq_IK_wft': 6, 'boq_IK_win': 3})
        quick('Master Bedroom', 'Side Table', {'item_qty_IK': 2})
        page.wait_for_timeout(300)
        rec.scroll_to(page.locator('#room_card_room_4'), 'The other rooms, the same way.', offset=80)
        rec.shot('The other rooms, the same way.', 1.2)
        rec.scroll_to(page.locator('#room_card_room_5'), 'Bedroom 2 isn\'t part of this job: left empty.', offset=80)
        rec.explain(page.locator('#room_card_room_5'), 'Left without a size?', [
            'Removed when you save', 'The app asks first'])
        summary = page.locator('.card', has_text='Live Cost Summary').first
        rec.explain(summary, 'The total, as you go', ['Every line, then discount and total'])
        rec.tap(page.locator('button:visible', has_text='Save Quotation').last, 'Save Quotation.', wait=1800, after_hold=0.6)
        pid = page.url.rstrip('/').split('/')[-1]
        rec.shot('Saved: a quotation in a few minutes.', 1.2)
        rec.explain(page.locator('.card', has_text='Cost Summary').first, 'A total for every section',
                    ['Lines left empty were removed', 'Every amount worked out for you'])

        url = f'{base}/projects/{pid}/pdf/customer'
        rec.pdf_view(url, 'The PDF your customer gets.', 0, 0.0, hold=2.6)
        rec.pdf_view(url, 'Every line with its size, quantity, rate and amount.', 0, 1.0, hold=2.4)

        # ── make your own ──
        page.goto(f'{base}/projects/{pid}')
        page.wait_for_timeout(600)
        rec.slide('Make your own', 'Any quotation can be a starting quotation', [
            'Save as template: for the next similar home', 'Duplicate: a copy to change for one customer'])
        rec.explain([page.locator('a', has_text='Duplicate').first, page.get_by_role('button', name='Save as template')],
                    'Save as template · Duplicate', ['Name it, e.g. "3 BHK premium"', 'It appears on New Quotation'])
        rec.tap(page.get_by_role('button', name='Save as template'), 'Save as template: give it a name.', wait=900, after_hold=0.6)
        page.goto(base + '/templates')
        page.wait_for_timeout(500)
        rec.shot('Manage them: rename or delete.', 1.6)
        page.goto(base + '/projects/new')
        page.wait_for_timeout(500)
        rec.explain(page.locator('.ki-start-cards'), 'Ready for the next quotation', [
            'Your new one is here too', 'Start blank whenever you like'], kicker='New Quotation')
        rec.slide('Done', 'Quotations in minutes, not hours', [
            'Start from your usual quotation', 'Type the sizes, remove what isn\'t needed',
            'New to QuoteRoom? Share your old quotations: we set them up for you'])
        rec.save()
        browser.close()


if __name__ == '__main__':
    if sys.argv[1] == '--render':
        os.makedirs(os.path.join(OUT, 'tutorials'), exist_ok=True)
        render(os.path.join(sys.argv[2], 'templates'),
               os.path.join(OUT, 'tutorials', 'quoteroom-tutorial-14-starting-quotations.mp4'), SUBTITLE, OUTRO)
    else:
        record(*sys.argv[1:4])
