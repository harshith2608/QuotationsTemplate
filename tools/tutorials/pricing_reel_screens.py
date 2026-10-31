"""Laptop screens for the reel 'Price your way' (tools/ad_video/reel_pricing.py): Settings → How do you price your
work?, then a quotation priced BY MATERIAL (sizes, material & work at a rate per area, fittings) and one priced BY ITEM
(each line with its own rate, unit and description; the customer's PDF as a bill of quantities).

Recorded on a local copy with the fictional demo data, renamed "Nest & Grain Interiors", plus two new quotations
(Sneha Example: by material; Rohan Example: by item). Every name and number is made up.

    flask seed-demo && python tools/tutorials/pricing_reel_screens.py --setup        (in the app's environment)
    python tools/tutorials/pricing_reel_screens.py http://localhost:5160 <workdir> <admin password>
        → <workdir>/pricing/<name>.png and marks.json (where each click and close-up is, in screenshot pixels)
"""
import json
import os
import sys

from recorder import Recorder
from revisions_reel_screens import Screens
from walkthrough import WIN, WIN_DPR

MATERIAL_ROOMS = [
    {'name': 'Master Bedroom', 'items': [
        {'name': 'Wardrobe', 'length': 8, 'width': 7, 'wood_type': 'Laminates', 'work_type': 'Box Work'},
        {'name': 'Loft', 'length': 8, 'width': 2, 'wood_type': 'Laminates', 'work_type': 'Box Work'},
        {'name': 'Dressing Table', 'length': 3, 'width': 6, 'wood_type': 'Acrylic', 'work_type': 'Frame Work'}]},
    {'name': 'Kitchen', 'items': [
        {'name': 'Base Cabinet', 'length': 10, 'width': 2.75, 'wood_type': 'Acrylic', 'work_type': 'Box Work'},
        {'name': 'Overhead Cabinet', 'length': 10, 'width': 2.5, 'wood_type': 'Acrylic', 'work_type': 'Box Work'},
        {'type': 'fixed', 'name': 'Magic Corner', 'quantity': 1, 'unit_price': 18000},
        {'type': 'fixed', 'name': 'Tandem Drawer', 'quantity': 4, 'unit_price': 4500}]}]
line = lambda name, qty, unit, rate, desc: {'type': 'boq', 'name': name, 'quantity': qty, 'unit': unit,
                                            'unit_price': rate, 'description': desc}
ITEM_ROOMS = [
    {'name': 'Living Room', 'items': [
        line('TV Unit', 42, 'sqft', 1650, 'Laminate finish, profile handles, back panel'),
        line('Side Table', 2, 'nos', 15000, 'Solid wood top, powder-coated legs')]},
    {'name': 'Master Bedroom', 'items': [
        line('Wardrobe', 56, 'sqft', 1950, 'BWP ply, laminate outside, soft-close hinges'),
        line('Bed with Storage', 1, 'nos', 42000, 'Hydraulic lift, upholstered headboard')]},
    {'name': 'Services', 'items': [
        line('False Ceiling', 650, 'sqft', 120, 'Gypsum, with cove lighting'),
        line('Electrical Points', 45, 'point', 650, 'New points, wire and switches'),
        line('3D Design', 1, 'lump sum', 50000, 'Every room, with two rounds of changes')]}]


def setup():
    """Rename the business and add the two quotations (by item needs BOQ lines on while saving). Ends priced by
    material, so the recording can switch it. Run after flask seed-demo."""
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
    from app import billing, boq, create_app, db
    from app.models import AppSetting, Project, User
    from app.projects import _save_project_data
    app = create_app()
    with app.app_context():
        AppSetting.set('company_name', 'Nest & Grain Interiors')
        admin = User.query.filter_by(username='demo-admin').first()
        for customer, mobile, rooms, item in (('Sneha Example', '9000000006', MATERIAL_ROOMS, False),
                                              ('Rohan Example', '9000000007', ITEM_ROOMS, True)):
            boq.set_enabled(item)
            p = Project(customer_name=customer, mobile=mobile, address='Flat 402, Sample Heights, Bengaluru',
                        created_by=admin.id, discount_type='none', discount_value=0, status='complete')
            db.session.add(p)
            db.session.flush()
            p.grand_total = _save_project_data(p, rooms)
            db.session.commit()
            billing.record_revision(p, admin)
            db.session.commit()
            print(customer, p.id, p.final_total)
        boq.set_enabled(False)
        db.session.commit()


class PdfScreens(Screens):
    def pdf(self, name, url, frac=0.0, width=0.62):
        """The customer's PDF page across the laptop screen (as a PDF viewer shows it)."""
        import fitz
        from PIL import Image
        doc = fitz.open(stream=self.page.request.get(url).body(), filetype='pdf')
        sw, sh = int(WIN['width'] * WIN_DPR), int(WIN['height'] * WIN_DPR)
        pg = doc[0]
        k = (sw * width) / pg.rect.width
        pix = pg.get_pixmap(matrix=fitz.Matrix(k, k))
        full = Image.frombytes('RGB', (pix.width, pix.height), pix.samples)
        top = int(max(0, full.height - (sh - 40)) * frac)
        canvas = Image.new('RGB', (sw, sh), (82, 86, 89))
        canvas.paste(full.crop((0, top, full.width, min(full.height, top + sh - 40))), ((sw - full.width) // 2, 20))
        canvas.save(os.path.join(self.dir, f'{name}.png'))


def record(base, work, password):
    from playwright.sync_api import sync_playwright
    out = os.path.join(work, 'pricing')
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_context(viewport=WIN, device_scale_factor=WIN_DPR).new_page()
        page.on('dialog', lambda d: d.accept())
        rec = PdfScreens(page, out, 0, '')
        page.goto(base + '/login')
        page.fill('input[name=username]', 'demo-admin')
        page.fill('input[name=password]', password)
        page.click('button[type=submit]')
        page.wait_for_timeout(800)
        pid = {}
        for name in ('Sneha', 'Rohan'):
            page.goto(base + '/projects?q=' + name)
            pid[name] = page.locator('a[href^="/projects/"]', has_text='View').first.get_attribute('href')

        # ── the choice ──
        page.goto(base + '/admin/settings?tab=pricing')
        card = page.locator('.card', has_text='How do you price your work?').first
        rec.top(card)
        rec.snap('settings_material', box=card)

        # ── by material ──
        page.goto(base + pid['Sneha'] + '/edit')
        page.wait_for_timeout(1200)
        rec.top(page.locator('#room_card_room_1'), offset=70)
        rec.snap('mat_edit', box=page.locator('#room_card_room_1'))
        rec.top(page.locator('#room_card_room_2'), offset=70)
        rec.snap('mat_fittings', box=page.locator('#room_card_room_2'))
        rec.pdf('mat_pdf', base + pid['Sneha'] + '/pdf/customer', frac=0.0)
        rec.pdf('mat_pdf2', base + pid['Sneha'] + '/pdf/customer', frac=0.6)

        # ── switch to by item ──
        page.goto(base + '/admin/settings?tab=pricing')
        card = page.locator('.card', has_text='How do you price your work?').first
        rec.top(card)
        opt = page.locator('label[for=pm_item]')
        rec.snap('settings_click', tap=opt, box=card)
        opt.click()
        page.wait_for_timeout(300)
        save = page.locator('button[type=submit]', has_text='Save').last
        rec.snap('settings_save', tap=save, box=card)
        save.click()
        page.wait_for_timeout(1000)
        card = page.locator('.card', has_text='How do you price your work?').first
        rec.top(card)
        rec.snap('settings_item', box=card)

        # ── by item ──
        page.goto(base + pid['Rohan'] + '/edit')
        page.wait_for_timeout(1200)
        rec.top(page.locator('#room_card_room_1'), offset=70)
        rec.snap('item_edit', box=page.locator('#room_card_room_1'))
        rec.top(page.locator('#room_card_room_3'), offset=70)
        rec.snap('item_edit3', box=page.locator('#room_card_room_3'))
        rec.pdf('item_pdf', base + pid['Rohan'] + '/pdf/customer', frac=0.0)
        rec.pdf('item_pdf2', base + pid['Rohan'] + '/pdf/customer', frac=0.6)
        json.dump(Screens.marks, open(os.path.join(out, 'marks.json'), 'w'), indent=1)
        browser.close()


if __name__ == '__main__':
    if sys.argv[1] == '--setup':
        setup()
    else:
        record(*sys.argv[1:4])
