"""Tutorial part 12: Your quotation PDF (Settings → Quotation PDFs and Units, then the Initial Quotation it makes).

Continues on the local tutorial app after part 10 (uses Vikram Reddy's kitchen quotation, awaiting confirmation).

    python tools/tutorials/part12_pdf_settings.py http://localhost:5093 <workdir> <admin password>
"""
import os
import sys

from playwright.sync_api import sync_playwright

from recorder import DPR, VIEW, Recorder

BASE, WORK, PASSWORD = sys.argv[1], sys.argv[2], sys.argv[3]
DESCRIPTIONS = ('Carcass: BWP ply, laminate finish · Shutters: 1mm laminate\n'
                'Carcass: BWP ply · Shutters: 1.5mm acrylic, soft-close hinges')
PAYMENT = '10% advance with order confirmation\n50% after design sign-off\n40% on delivery of materials to site'


def show(page, selector, block='start'):
    page.locator(selector).first.evaluate(f"el => el.scrollIntoView({{block: '{block}'}})")
    if block == 'start':
        page.evaluate('window.scrollBy(0, -76)')
    page.wait_for_timeout(250)


def open_menu_item(rec, page, label, caption):
    rec.tap(page.locator('.navbar-toggler'), caption)
    rec.tap(page.locator('#navbarMain a.nav-link', has_text=label).last, caption, wait=900)


def append(rec, locator, extra, caption, per_frame=3):
    """Type more at the end of a box without retyping what's already there."""
    base = locator.input_value()
    for i in range(per_frame, len(extra) + per_frame, per_frame):
        locator.fill(base + extra[:i])
        rec._snap(caption, 0.09)
    rec.items[-1]['hold'] = 0.8


def pdf_zoom(rec, url, caption, clip, hold=3.0):
    """Show part of a PDF page (clip = x0, y0, x1, y1 in points) zoomed to the phone's width, so it can be read."""
    import fitz
    from PIL import Image
    doc = fitz.open(stream=rec.page.request.get(url).body(), filetype='pdf')
    sw, sh = VIEW['width'] * DPR, VIEW['height'] * DPR
    rect = fitz.Rect(*clip)
    scale = sw / rect.width
    pix = doc[0].get_pixmap(matrix=fitz.Matrix(scale, scale), clip=rect)
    crop = Image.frombytes('RGB', (pix.width, pix.height), pix.samples)
    canvas = Image.new('RGB', (sw, sh), (82, 86, 89))
    canvas.paste(crop, (0, max(0, (sh - crop.height) // 2)))
    path = os.path.join(rec.dir, f'{len(rec.items):04d}-pdf.png')
    canvas.save(path)
    rec.image(path, caption, hold)


def card(page, title):
    return page.locator('.card', has=page.locator('.card-header', has_text=title)).first


def part12(page):
    rec = Recorder(page, os.path.join(WORK, 'part12'), 12, 'Your quotation PDF')
    page.goto(BASE + '/projects')
    rec.shot('Make the quotation PDF say things your way.', 2.0)
    open_menu_item(rec, page, 'Settings', 'Open the menu → Settings.')
    rec.tap(page.locator('.ki-settings-nav a', has_text='Quotation PDFs'), 'Tap Quotation PDFs.', wait=900)
    rec.shot('First, what your customer gets: by room, or by material.', 2.6)
    rec.shot('By room: each room, its items with sizes, and one amount. No rates shown.', 2.8)

    rec.scroll_to(page.locator('#room-descriptions'), 'Room descriptions: what a room is made of.', offset=90)
    rec.type(page.locator('textarea[name=room_descriptions]'), DESCRIPTIONS,
             'Room descriptions: what a room is made of. One per line.', per_frame=5)
    rec.shot('Room descriptions: what a room is made of. One per line.', 1.4)

    specs = page.locator('textarea[name=material_specs]')
    rec.scroll_to(card(page, 'Material Specifications'), 'Material Specifications: printed on every quotation.', offset=90)
    rec.shot('Material Specifications: printed on every quotation.', 2.0)
    rec.type(specs, 'Plywood: ', 'Type a point…', per_frame=2)
    rec.tap(card(page, 'Material Specifications').locator('.ki-var-bar button', has_text='Plywood details'),
            'Tap + Plywood details. Each quotation fills in its own plywood.', after_hold=1.8)
    append(rec, specs, ' for all carcass and shutters', 'Tap + Plywood details. Each quotation fills in its own plywood.')
    append(rec, specs, '\nAll shutters come with 1mm backing laminate', 'One point per line. The PDF numbers them.', per_frame=4)
    rec.shot('Also: customer name, materials used, quotation no. and date.', 2.4)

    rec.scroll_to(card(page, 'Payment Terms'), 'Payment Terms, Delivery Terms, Important Notes.', offset=90)
    rec.type(page.locator('textarea[name=payment_terms]'), PAYMENT, 'Payment Terms, Delivery Terms, Important Notes.', per_frame=5)
    rec.type(page.locator('textarea[name=delivery_terms]'), '45 to 60 working days from design sign-off',
             'Leave any box empty to leave it out of the PDF.', per_frame=4)
    rec.scroll_to(card(page, 'Terms & Conditions'), 'And your Terms & Conditions, at the end.', offset=90)
    rec.shot('And your Terms & Conditions, at the end.', 2.0)
    rec.tap(page.locator('button', has_text='Save Quotation Settings'), 'Tap Save.', wait=1200)

    rec.tap(page.locator('.ki-settings-nav a', has_text='Units'), 'Measure in mm or cm? Open Units.', wait=900)
    show(page, 'input[name=size_unit]', 'center')
    rec.shot('Sizes in ft & in, inches, cm or mm. Rates per sqft or per sq m.', 3.0)
    rec.shot('Your choice, for the whole team. No price ever changes.', 2.4)

    page.goto(BASE + '/projects?q=Vikram')
    view = BASE + page.locator('a[href^="/projects/"]', has_text='View').first.get_attribute('href')
    pid = view.rstrip('/').split('/')[-1]
    page.goto(view)
    rec.shot("Now Vikram's kitchen quotation.", 1.8)
    rec.tap(page.locator(f'a[href="/projects/{pid}/edit"]').first, 'Tap Edit.', wait=1500)
    btn = page.locator('[id^=room_desc_btn_]').first
    rec.scroll_to(btn, "On each room, pick what it's made of.", offset=240)
    rec.tap(btn, "On each room, pick what it's made of.", after_hold=1.0)
    rec.tap(page.locator('[id^=room_desc_] input[type=checkbox]').nth(1), 'Tick one or more descriptions.', after_hold=1.8)
    page.locator('body').click(position={'x': 5, 'y': 5})
    page.wait_for_timeout(300)
    ply = page.locator('input[name=plywood][value="18mm BWP"]')
    rec.scroll_to(ply, 'And the plywood for this quotation.', offset=300)
    rec.tap(ply, 'And the plywood for this quotation: 18mm BWP.', after_hold=1.4)
    rec.tap(page.locator('button[type=submit]', has_text='Quotation').locator('visible=true').last, 'Tap Update Quotation.', wait=1800)

    url = f'{BASE}/projects/{pid}/pdf/customer'
    rec.pdf(url, 'Open the Initial Quotation.', hold=1.8)
    pdf_zoom(rec, url, 'The room, with the description you ticked…', (40, 280, 300, 410), hold=3.0)
    pdf_zoom(rec, url, '…its items with sizes and No\'s, and one amount.', (250, 300, 552, 410), hold=2.6)
    pdf_zoom(rec, url, '…and your points, with the plywood details filled in.', (40, 420, 380, 600), hold=3.6)
    rec.shot('Set it once. Every quotation comes out your way.', 2.4)
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
        part12(page)
        browser.close()


if __name__ == '__main__':
    run()
