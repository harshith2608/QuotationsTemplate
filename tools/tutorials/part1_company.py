"""Tutorial part 1: log in, add company details, logo and colours.

Run against the local tutorial app (fictional business, fresh database), e.g. on port 5093:
    python tools/tutorials/part1_company.py http://localhost:5093 <workdir> <admin password>
"""
import os
import sys

from PIL import Image, ImageDraw, ImageFont
from playwright.sync_api import sync_playwright

from recorder import DPR, VIEW, Recorder

BASE, WORK, PASSWORD = sys.argv[1], sys.argv[2], sys.argv[3]


def make_logo(path):
    """A simple logo for the fictional 'Sharma Interiors'."""
    img = Image.new('RGBA', (600, 600), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([20, 20, 580, 580], radius=120, fill=(15, 118, 110))
    f = ImageFont.truetype('/System/Library/Fonts/Avenir Next.ttc', 300, index=8)
    d.text((300, 290), 'SI', font=f, fill=(255, 255, 255), anchor='mm')
    d.rectangle([150, 470, 450, 492], fill=(234, 179, 8))
    img.save(path)
    return path


def run():
    logo = make_logo(os.path.join(WORK, 'sharma-logo.png'))
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_context(viewport=VIEW, device_scale_factor=DPR, is_mobile=True, has_touch=True).new_page()
        rec = Recorder(page, os.path.join(WORK, 'part1'), 1, 'Your company details')
        page.goto(BASE + '/login')
        rec.shot('Open the link from your welcome message.', 2.0)
        rec.type(page.locator('input[name=username]'), 'admin', 'Log in with the username and password we sent you.')
        rec.type(page.locator('input[name=password]'), PASSWORD, 'Log in with the username and password we sent you.', per_frame=4)
        rec.tap(page.locator('button[type=submit]'), 'Tap Sign In.')
        rec.shot('This is your app. Let\'s add your company details first.', 2.2)
        rec.tap(page.locator('.navbar-toggler'), 'Open the menu (top right).')
        rec.tap(page.locator('#navbarMain a.nav-link', has_text='Settings').last, 'Tap Settings.', wait=800)
        rec.shot('The Company tab is where your business details go.', 2.0)
        for name, value, caption in (
                ('company_name', 'Sharma Interiors', 'Your company name, exactly as it should appear on quotations.'),
                ('company_tagline', 'Modular kitchens · Wardrobes', 'A short tagline (optional).'),
                ('company_mobile', '+91 98480 12345', 'Your phone number.'),
                ('company_email', 'hello@sharmainteriors.example', 'Your email.'),
                ('company_gstin', '36ABCDE1234F1Z5', 'Your GSTIN, only if you want GST tax invoices.')):
            rec.type(page.locator(f'[name={name}]'), value, caption)
        rec.type(page.locator('[name=company_address]'), 'Plot 21, Madhapur, Hyderabad 500081', 'Your address.')
        rec.type(page.locator('[name=signatory_name]'), 'Ravi Sharma', 'Who signs your quotations.')
        rec.type(page.locator('[name=signatory_title]'), 'Proprietor', 'Who signs your quotations.')
        rec.scroll_to(page.locator('#confirm_identity'), 'Check your company name and GSTIN carefully.')
        rec.shot('Check your company name and GSTIN carefully: they lock once saved.', 2.4)
        rec.tap(page.locator('#confirm_identity'), 'Tick "These details are correct".')
        rec.tap(page.get_by_role('button', name='Save Company Details'), 'Tap Save Company Details.', wait=900)
        page.evaluate('window.scrollTo(0, 0)')
        rec.shot('Saved! Next: your logo and colours.', 1.8)
        rec.tap(page.locator('.ki-settings-nav a', has_text='Appearance'), 'Open the Appearance tab.', wait=900)
        page.locator('#logoInput').set_input_files(logo)
        page.wait_for_timeout(600)
        rec.scroll_to(page.locator('#logoBox'), 'Upload your logo.')
        rec.shot('Upload your logo (PNG or JPG).', 1.8)
        rec.tap(page.locator('#confirm_logo'), 'Tick "This is my company\'s logo".')
        rec.scroll_to(page.locator('#presetGrid'), 'Pick your brand colours.')
        rec.tap(page.locator('[data-preset="Teal"]'), 'Pick your brand colours.', after_hold=1.6)
        rec.tap(page.get_by_role('button', name='Save Appearance').first, 'Tap Save Appearance.', wait=1200)
        page.evaluate('window.scrollTo(0, 0)')
        rec.shot('Done! Your name, logo and colours are now on the app and every PDF.', 3.0)
        rec.save()
        browser.close()


if __name__ == '__main__':
    run()
