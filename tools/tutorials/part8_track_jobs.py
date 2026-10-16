"""Tutorial part 8: Track every job (stages, filter by stage, search, notifications).

Continues on the local tutorial app after part 7 (Anita Rao and Meena Iyer confirmed, Vikram Reddy awaiting).

    python tools/tutorials/part8_track_jobs.py http://localhost:5093 <workdir> <admin password>
"""
import os
import sys

from playwright.sync_api import sync_playwright

from recorder import DPR, VIEW, Recorder

BASE, WORK, PASSWORD = sys.argv[1], sys.argv[2], sys.argv[3]


def open_quote(page, name):
    page.goto(BASE + f'/projects?q={name}')
    return BASE + page.locator('a[href^="/projects/"]', has_text='View').first.get_attribute('href')


def move_stage(rec, page, stage, label, note, caption):
    rec.scroll_to(page.locator('#stageSelect'), caption, offset=260)
    rec.tap(page.locator('#stageSelect'), caption, after_hold=0.4)
    page.locator('#stageSelect').select_option(stage)
    rec.shot(f'Move it to {label}.', 1.2)
    rec.type(page.locator('#stageNote'), note, 'Add a note for your team (optional).', per_frame=3)
    rec.tap(page.get_by_role('button', name='Update stage'), 'Tap Update stage.', wait=1200)


def part8(page):
    rec = Recorder(page, os.path.join(WORK, 'part8'), 8, 'Track every job')
    page.goto(BASE + '/projects')
    rec.shot('Every quotation, with its stage, in one list.', 2.4)
    rec.tap(page.locator('.ki-stage-filter a', has_text='Confirmed'), 'Tap a stage to see only those jobs.', wait=900)
    rec.shot('Only the confirmed jobs.', 1.8)
    rec.tap(page.locator('.ki-stage-filter a', has_text='Awaiting confirmation'), 'Or the ones still waiting for an answer.', wait=900)
    rec.shot('Or the ones still waiting for an answer.', 1.8)
    page.goto(BASE + '/projects')
    rec.type(page.locator('input[name=q]'), 'Anita', 'Search by customer name or mobile number.', per_frame=1)
    rec.tap(page.locator('button', has_text='Search'), 'Search by customer name or mobile number.', wait=900)
    rec.tap(page.locator('a[href^="/projects/"]', has_text='View').first, 'Open the job.', wait=1000)
    rec.shot("Anita's job is confirmed. Work starts on site.", 2.0)
    move_stage(rec, page, 'ongoing', 'Ongoing', 'Site work started, carpenters on site', 'Work has started? Move it to Ongoing.')
    rec.scroll_to(page.locator('#stageSelect'), 'Each step is saved with who, when and the note.', offset=420)
    rec.shot('Each step is saved with who, when and the note.', 2.6)
    move_stage(rec, page, 'completed', 'Completed', 'Handed over, customer happy', 'Job finished? Move it to Completed.')
    rec.scroll_to(page.locator('#stageSelect'), 'Done!', offset=420)
    rec.shot('Done! The whole history of the job, in one place.', 2.4)

    page.goto(open_quote(page, 'Vikram'))
    move_stage(rec, page, 'on_hold', 'On hold', 'Customer travelling, call back after Diwali', 'Customer asked you to wait? Put it On hold.')
    rec.scroll_to(page.locator('#stageSelect'), 'Nothing gets forgotten.', offset=420)
    rec.shot('Nothing gets forgotten. Cancelled jobs can be marked too.', 2.4)

    page.evaluate('window.scrollTo(0, 0)')
    rec.tap(page.locator('.ki-nav-bell').first, 'The bell shows what happened while you were busy.', wait=1000)
    rec.shot('Accepted quotations and change requests, as they happen.', 2.8)
    page.goto(BASE + '/projects')
    rec.shot('Every job, always up to date.', 2.6)
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
        part8(page)
        browser.close()


if __name__ == '__main__':
    run()
