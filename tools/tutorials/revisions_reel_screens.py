"""Laptop screens for the reel 'Customer changed their mind?' (tools/ad_video/reel_revisions.py): a quotation is
changed (Rev 2, the loft removed), the customer's link shows it, then Rev 1 is restored and accepted.

Recorded on a local copy with the fictional demo data, renamed "Nest & Grain Interiors", plus one new quotation
(Sneha Example's master bedroom: wardrobe, loft, dressing table). Every name and number is made up.

    flask seed-demo && python tools/tutorials/revisions_reel_screens.py --setup        (in the app's environment)
    python tools/tutorials/revisions_reel_screens.py http://localhost:5150 <workdir> <admin password>
        → <workdir>/revisions/<name>.png and marks.json (where each tap and close-up is, in screenshot pixels)
"""
import json
import os
import sys

from recorder import Recorder
from walkthrough import WIN, WIN_DPR

CUSTOMER = 'Sneha Example'


def setup():
    """Add Sneha's quotation (revision 1) and rename the business. Run after flask seed-demo."""
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
    from app import billing, create_app, db
    from app.models import AppSetting, Project, User
    from app.projects import _save_project_data
    app = create_app()
    with app.app_context():
        AppSetting.set('company_name', 'Nest & Grain Interiors')
        admin = User.query.filter_by(username='demo-admin').first()
        p = Project(customer_name=CUSTOMER, mobile='9000000006', address='Flat 402, Sample Heights, Bengaluru',
                    created_by=admin.id, discount_type='none', discount_value=0, status='complete')
        db.session.add(p)
        db.session.flush()
        rooms = [{'name': 'Master Bedroom', 'items': [
            {'name': 'Wardrobe', 'length': 8, 'width': 7, 'wood_type': 'Laminates', 'work_type': 'Box Work'},
            {'name': 'Loft', 'length': 8, 'width': 2, 'wood_type': 'Laminates', 'work_type': 'Box Work'},
            {'name': 'Dressing Table', 'length': 3, 'width': 6, 'wood_type': 'Acrylic', 'work_type': 'Frame Work'}]}]
        p.grand_total = _save_project_data(p, rooms)
        db.session.commit()
        billing.record_revision(p, admin)
        db.session.commit()
        print('quotation', p.id, p.final_total)


class Screens(Recorder):
    """Named screenshots, with where the click goes and the part to show close up, instead of a timeline."""
    marks = {}

    def snap(self, name, tap=None, box=None):
        self.page.wait_for_timeout(300)
        self._mask_local()
        self.page.screenshot(path=os.path.join(self.dir, f'{name}.png'))
        m = self.marks.setdefault(name, {})
        if tap is not None:
            b = tap.bounding_box()
            m['tap'] = ((b['x'] + b['width'] / 2) * WIN_DPR, (b['y'] + b['height'] / 2) * WIN_DPR)
        if box is not None:
            b = box.bounding_box()
            m['box'] = (b['x'] * WIN_DPR, b['y'] * WIN_DPR, (b['x'] + b['width']) * WIN_DPR,
                        (b['y'] + b['height']) * WIN_DPR)

    def top(self, locator, offset=90):
        """Scroll so the element sits near the top of the screen."""
        self.page.evaluate('document.activeElement && document.activeElement.blur()')
        locator.scroll_into_view_if_needed()
        box = locator.bounding_box()
        self.page.evaluate(f'window.scrollBy(0, {box["y"] - offset})')
        self.page.wait_for_timeout(300)


def ask(cust, link, note):
    cust.goto(link)
    cust.locator('#respond summary').click()
    cust.fill('#respond textarea[name=note]', note)
    cust.locator('#respond button', has_text='Send my changes').click()
    cust.wait_for_timeout(1000)


def record(base, work, password):
    from playwright.sync_api import sync_playwright
    out = os.path.join(work, 'revisions')
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = lambda: browser.new_context(viewport=WIN, device_scale_factor=WIN_DPR)
        page = ctx().new_page()
        page.on('dialog', lambda d: d.accept())
        rec = Screens(page, out, 0, '')
        page.goto(base + '/login')
        page.fill('input[name=username]', 'demo-admin')
        page.fill('input[name=password]', password)
        page.click('button[type=submit]')
        page.wait_for_timeout(800)
        page.goto(base + '/projects?q=Sneha')
        quote = base + page.locator('a[href^="/projects/"]', has_text='View').first.get_attribute('href')
        page.goto(quote)
        rec.snap('quote')
        page.locator('#approval button', has_text='Create approval link').click()
        page.wait_for_timeout(1000)
        link = page.locator('#approvalUrl').input_value().replace(Recorder.PUBLIC, base)

        cust = ctx().new_page()
        crec = Screens(cust, out, 0, '')
        cust.goto(link)
        crec.snap('cust_first')
        ask(cust, link, 'Can we drop the loft to save some money?')

        # ── Rev 2: the loft removed ──
        page.goto(quote)
        rec.top(page.locator('#approval'))
        rec.snap('request', box=page.locator('#approval'))
        page.evaluate('window.scrollTo(0, 0)')
        page.locator('a', has_text='Edit').first.click()
        page.wait_for_timeout(1200)
        page.wait_for_selector('tr[id^="item_row_"]')
        loft_id = page.evaluate("""[...document.querySelectorAll('tr[id^="item_row_"]')]
            .find(tr => [...tr.querySelectorAll('textarea')].some(i => i.value === 'Loft')).id""")
        loft = page.locator('#' + loft_id)
        rec.top(loft, offset=260)
        rec.snap('edit_loft', tap=loft.locator('.btn-remove-item'), box=loft)
        loft.locator('.btn-remove-item').click()
        page.wait_for_timeout(500)
        upd = page.locator('button', has_text='Update Quotation').first      # the laptop one (.last is the phone bar)
        upd.scroll_into_view_if_needed()
        rec.snap('edit_update', tap=upd, box=upd)
        upd.click()
        page.wait_for_timeout(1500)
        rec.snap('saved', box=page.locator('.alert').first)
        rec.top(page.locator('#revisions'))
        rec.snap('revisions2', box=page.locator('#revisions'))

        cust.goto(link)
        crec.snap('cust_rev2')
        ask(cust, link, 'Actually, please keep the loft after all!')

        # ── back to Rev 1 ──
        page.goto(quote)
        rec.top(page.locator('#revisions'))
        rev1 = page.locator('#revisions a', has_text='Rev 1')
        rec.snap('revisions_tap1', tap=rev1, box=page.locator('#revisions'))
        rev1.click()
        page.wait_for_timeout(1000)
        restore = page.locator('#restore button', has_text='Restore revision 1')
        rec.snap('rev1')
        rec.top(restore, offset=380)
        rec.snap('rev1_restore', tap=restore, box=page.locator('#restore'))
        restore.click()
        page.wait_for_timeout(1500)
        rec.snap('restored', box=page.locator('.alert').first)
        rec.top(page.locator('#revisions'))
        rec.snap('revisions3', box=page.locator('#revisions'))

        cust.goto(link)
        crec.snap('cust_rev3')
        crec.top(cust.locator('#respond'))
        cust.locator('#accAgree').check()
        crec.snap('cust_accept', tap=cust.locator('#respond button[type=submit]').first, box=cust.locator('#respond'))
        cust.locator('#respond button[type=submit]').first.click()
        cust.wait_for_timeout(1200)
        cust.evaluate('window.scrollTo(0, 0)')
        crec.snap('cust_accepted')
        page.goto(quote)
        rec.snap('confirmed')
        rec.top(page.locator('#approval'))
        rec.snap('confirmed_approval', box=page.locator('#approval'))
        json.dump(Screens.marks, open(os.path.join(out, 'marks.json'), 'w'), indent=1)
        browser.close()


if __name__ == '__main__':
    if sys.argv[1] == '--setup':
        setup()
    else:
        record(*sys.argv[1:4])
