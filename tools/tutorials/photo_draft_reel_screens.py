"""Laptop screens for the reel 'Your site notes → a quotation' (tools/ad_video/reel_photo_draft.py): photos of two
handwritten notebook pages are chosen on Draft from photos of site notes, the real AI drafts the quotation from them
(every room, the business's own lines and rates), the three kitchen sizes the notes didn't have are typed, and it's
saved with its total.

Recorded on a local copy with the fictional demo data, renamed "Nest & Grain Interiors", pricing by item with made-up
rates for the lines in the notes. Needs ANTHROPIC_API_KEY and AI_PHOTOS=1 on the app (one real draft: two photos).

    flask seed-demo && python tools/tutorials/photo_draft_reel_screens.py --setup        (in the app's environment)
    python tools/tutorials/photo_draft_reel_screens.py http://localhost:5192 <workdir> <admin password> <page1> <page2>
        → <workdir>/photodraft/<name>.png and marks.json (taps, close-ups and how long the draft took)
"""
import json
import os
import sys
import time

from recorder import Recorder
from revisions_reel_screens import Screens
from walkthrough import WIN, WIN_DPR

CUSTOMER, MOBILE = 'Ravi Example', '9000000021'
# the lines the notes use, with made-up rates: (name, unit, rate, group)
LINES = [('TV Unit', 'sqft', 1400, 'Living Room'), ('Display Unit', 'sqft', 1500, 'Living Room'),
         ('Bed Box', 'sqft', 1300, 'Bedrooms'), ('Head Panel', 'sqft', 900, 'Bedrooms'),
         ('Wardrobe', 'sqft', 1600, 'Bedrooms'), ('Loft', 'sqft', 1100, 'Bedrooms'),
         ('Dressing Table', 'sqft', 1500, 'Bedrooms'), ('Base Cabinet', 'sqft', 1700, 'Kitchen'),
         ('Overhead Cabinet', 'sqft', 1500, 'Kitchen'), ('Pantry Unit', 'sqft', 1800, 'Kitchen'),
         ('Rolling Shutter', 'nos', 9500, 'Kitchen'), ('Sink', 'nos', 6500, 'Kitchen')]
KITCHEN_AREAS = {'Base Cabinet': 27.5, 'Overhead Cabinet': 22, 'Pantry Unit': 14}      # typed in the reel (made up)


def setup():
    """Rename the business, price by item with the notes' lines. Run after flask seed-demo."""
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
    from app import boq, create_app, db
    from app.models import AppSetting, BoqItem
    app = create_app()
    with app.app_context():
        AppSetting.set('company_name', 'Nest & Grain Interiors')
        boq.set_pricing('item')
        for name, unit, rate, group in LINES:
            b = BoqItem.query.filter_by(name=name).first() or BoqItem(name=name)
            b.unit, b.rate, b.category = unit, rate, group
            db.session.add(b)
        db.session.commit()
        print('set up: by item,', len(LINES), 'lines')


def record(base, work, password, photos):
    from playwright.sync_api import sync_playwright
    out = os.path.join(work, 'photodraft')
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_context(viewport=WIN, device_scale_factor=WIN_DPR).new_page()
        page.on('dialog', lambda d: d.accept())
        rec = Screens(page, out, 0, '')
        page.goto(base + '/login')
        page.fill('input[name=username]', 'demo-admin')
        page.fill('input[name=password]', password)
        page.click('button[type=submit]')
        page.wait_for_timeout(800)

        page.goto(base + '/projects/draft')
        rec.snap('draft', box=page.locator('#draftForm'))
        page.set_input_files('#draftPhotos', photos)
        page.wait_for_function('document.querySelectorAll("#photoPreview img").length === %d' % len(photos), timeout=20000)
        go = page.locator('#draftGo')
        rec.snap('chosen', tap=go, box=page.locator('#photoPreview'))
        # the button as it looks while drafting (the page's own submit handler, shown before the page is busy)
        page.evaluate("""() => { const b = document.getElementById('draftGo'); b.dataset.html = b.innerHTML;
            b.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Drafting your quotation…'; }""")
        rec.snap('drafting', box=go)
        page.evaluate("() => { const b = document.getElementById('draftGo'); b.innerHTML = b.dataset.html; }")
        started = time.time()
        go.click()
        page.wait_for_selector('.room-card', timeout=90000)
        took = time.time() - started
        page.wait_for_timeout(1200)
        rec.marks['took'] = round(took, 1)
        alert = page.locator('.alert', has_text='Drafted from').first
        rec.snap('result', box=alert)

        cards = page.locator('.room-card')
        rooms = []
        for i in range(cards.count()):
            card = cards.nth(i)
            rec.top(card, offset=70)
            name = card.locator('input').first.input_value()
            rooms.append(name)
            rec.snap(f'room{i}', box=card)
        rec.marks['rooms'] = rooms

        # the kitchen: the sizes the notes didn't have, typed
        kitchen = next((cards.nth(i) for i, n in enumerate(rooms) if 'kitchen' in n.lower()), None)
        if kitchen is not None:
            rec.top(kitchen, offset=70)
            rec.snap('kitchen_waiting', box=kitchen)
            waiting = kitchen.evaluate("""card => [...card.querySelectorAll('tr.item-row.ki-needs-qty')].map(tr =>
                [tr.querySelector('input[id^="item_qty_"]').id, tr.querySelector('textarea.ki-name').value])""")
            for qty_id, name in waiting:                     # found first: a row stops waiting once it's typed
                area = next((v for k, v in KITCHEN_AREAS.items() if k.lower() in name.lower()), None)
                if area is not None:
                    q = page.locator('#' + qty_id)
                    q.click()
                    q.type(str(area), delay=60)
            page.evaluate('document.activeElement && document.activeElement.blur()')
            rec.top(kitchen, offset=70)
            rec.snap('kitchen_done', box=kitchen)

        rec.top(page.locator('#customer_name'), offset=160)
        page.fill('#customer_name', CUSTOMER)
        page.fill('#mobile', MOBILE)
        save = page.locator('button[type=submit]', has_text='Save').first
        rec.snap('customer', tap=save, box=page.locator('#customer_name'))
        save.click()
        page.wait_for_url('**/projects/*', timeout=30000)
        page.wait_for_timeout(1200)
        rec.snap('saved')
        total = page.locator('text=Grand Total').first
        if total.count():
            rec.top(total, offset=300)
            rec.snap('total', box=total.locator('xpath=ancestor::*[contains(@class,"card")][1]'))
        json.dump(rec.marks, open(os.path.join(out, 'marks.json'), 'w'), indent=1)
        print('took', rec.marks['took'], 's; rooms', rooms)
        browser.close()


if __name__ == '__main__':
    if sys.argv[1] == '--setup':
        setup()
    else:
        record(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4:])
