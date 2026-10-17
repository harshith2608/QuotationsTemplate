"""Tutorial part 9: Your team (add a staff login, reset a password, share a quotation, what staff see).

Continues on the local tutorial app after part 8. Staff passwords are throwaway test values for this local copy.

    python tools/tutorials/part9_team.py http://localhost:5093 <workdir> <admin password>
"""
import os
import secrets
import sys

from playwright.sync_api import sync_playwright

from recorder import DPR, VIEW, Recorder

BASE, WORK, PASSWORD = sys.argv[1], sys.argv[2], sys.argv[3]
STAFF = 'rahul'


def open_menu_item(rec, page, label, caption):
    rec.tap(page.locator('.navbar-toggler'), caption)
    rec.tap(page.locator('#navbarMain a.nav-link', has_text=label).last, caption, wait=900)


def user_row(page, name):
    return page.locator('tr', has=page.get_by_text(name, exact=True)).first


def part9(page, browser):
    rec = Recorder(page, os.path.join(WORK, 'part9'), 9, 'Your team')
    first_pw, new_pw = f'site-{secrets.token_hex(3)}', f'site-{secrets.token_hex(3)}'
    page.goto(BASE + '/projects')
    rec.shot('Give everyone in your team their own login.', 2.0)
    open_menu_item(rec, page, 'Users', 'Open the menu → Users.')
    rec.shot('One price for your whole team, however many logins.', 2.4)
    rec.tap(page.locator('button', has_text='Add User'), 'Tap Add User.', wait=700)
    m = page.locator('#createUserModal')
    rec.type(m.locator('[name=username]'), STAFF, 'A username for your site supervisor, Rahul.')
    rec.shot('Role: Employee (staff) or Admin (sees everything).', 1.8)
    rec.type(m.locator('[name=password]'), first_pw, 'And a password for him.', per_frame=3)
    rec.type(m.locator('[name=confirm_password]'), first_pw, 'And a password for him.', per_frame=3)
    rec.tap(m.locator('button[type=submit]'), 'Tap Create User.', wait=1200)
    rec.scroll_to(user_row(page, STAFF), 'Rahul can now log in on his phone.', offset=300)
    rec.shot('Rahul can now log in on his phone.', 2.2)
    rec.tap(user_row(page, STAFF).locator('button[title="Change Password"]'), 'Forgot his password? Set a new one.', wait=700)
    pm = page.locator('.modal.show')
    rec.type(pm.locator('[name=new_password]'), new_pw, 'Forgot his password? Set a new one.', per_frame=3)
    rec.type(pm.locator('[name=confirm_password]'), new_pw, 'Forgot his password? Set a new one.', per_frame=3)
    rec.tap(pm.locator('button[type=submit]'), 'Tap Update.', wait=1200)

    page.goto(BASE + '/projects?q=Vikram')
    rec.shot('Want Rahul to see a job? Share it with him.', 2.0)
    rec.tap(page.locator('button', has_text='Access').first, 'Tap Access on the quotation.', wait=900)
    sel = page.locator('#accessModal select').first
    rec.tap(sel, 'Choose Can view, or Can edit. Only admins can delete.', after_hold=0.4)
    sel.select_option('view')
    rec.shot('Choose Can view, or Can edit. Only admins can delete.', 2.2)
    rec.tap(page.locator('#accessModal button[type=submit]'), 'Tap Save Access.', wait=1200)
    rec.shot('Done. Rahul can now open this quotation.', 2.0)

    staff = browser.new_context(viewport=VIEW, device_scale_factor=DPR, is_mobile=True, has_touch=True).new_page()
    srec = Recorder(staff, rec.dir, rec.chapter, rec.title)
    srec.items = rec.items
    staff.goto(BASE + '/login')
    srec.shot("On Rahul's phone, he logs in…", 1.8)
    srec.type(staff.locator('input[name=username]'), STAFF, "On Rahul's phone, he logs in…")
    srec.type(staff.locator('input[name=password]'), new_pw, "On Rahul's phone, he logs in…", per_frame=3)
    srec.tap(staff.locator('button[type=submit]'), "On Rahul's phone, he logs in…", wait=1000)
    srec.shot('He sees only the jobs shared with him, and the ones he makes himself.', 3.0)
    srec.tap(staff.locator('a[href^="/projects/"]', has_text='View').first, 'He opens the job…', wait=1000)
    srec.shot('…with the rooms, sizes and PDFs he needs on site.', 2.4)
    srec.tap(staff.locator('.navbar-toggler'), 'Your costs, profit, reports and settings stay admin-only.', after_hold=2.8)
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
        part9(page, browser)
        browser.close()


if __name__ == '__main__':
    run()
