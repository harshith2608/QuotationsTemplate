"""Laptop screens for the reel 'Where is every job right now?' (tools/ad_video/reel_jobs.py): the dashboard's
pipeline by stage, the list filtered to the jobs on site, a job moved to Ongoing with a note, its history, and the bell.

Recorded on a local copy with the fictional demo data, renamed "Nest & Grain Interiors", plus four more jobs so the
pipeline looks like a working firm's. Every name and number is made up.

    flask seed-demo && python tools/tutorials/jobs_reel_screens.py --setup        (in the app's environment)
    python tools/tutorials/jobs_reel_screens.py http://localhost:5180 <workdir> <admin password>
        → <workdir>/jobs/<name>.png and marks.json (where each tap and close-up is, in screenshot pixels)
"""
import json
import os
import sys
from datetime import datetime, timedelta

from recorder import Recorder
from revisions_reel_screens import Screens
from walkthrough import WIN, WIN_DPR

MOVE = 'Farhan Example'          # the job moved to Ongoing in the reel

# customer, mobile, address, days ago, rooms, stage flow [(stage, days after, note)]
JOBS = [
    (MOVE, '9000000011', 'Flat 803, Sample Towers, Hyderabad', 6,
     [('Kitchen', [('Base Cabinet', 11, 2.75, 'Acrylic', 'Box Work'), ('Overhead Cabinet', 11, 2.5, 'Acrylic', 'Box Work')])],
     [('confirmed', 2, 'Advance received, material ordered')]),
    ('Lakshmi Sample', '9000000012', 'Villa 21, Placeholder Enclave, Hyderabad', 18,
     [('Living Room', [('TV Unit', 10, 7, 'Veneer', 'Frame Work')]),
      ('Master Bedroom', [('Wardrobe', 9, 7, 'Laminates', 'Box Work')])],
     [('confirmed', 1, None), ('ongoing', 6, 'Carpenters on site')]),
    ('Deepak Test', '9000000013', 'Flat 12B, Mock Residency, Hyderabad', 4,
     [('Kids Room', [('Wardrobe', 6, 7, 'Laminates', 'Box Work'), ('Study Table', 4, 2.5, 'Laminates', 'Frame Work')])],
     [('confirmed', 1, 'Token advance paid')]),
    ('Nisha Placeholder', '9000000014', 'House 4, Example Colony, Hyderabad', 1,
     [('Dining Room', [('Crockery Unit', 6, 7, 'Acrylic', 'Frame Work')])], []),
]


def setup():
    """Rename the business and add the extra jobs. Run after flask seed-demo."""
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
    from app import create_app, db
    from app.models import AppSetting, Notification, Project, ProjectStageChange, User
    from app.projects import _save_project_data
    app = create_app()
    with app.app_context():
        AppSetting.set('company_name', 'Nest & Grain Interiors')
        admin = User.query.filter_by(username='demo-admin').first()
        now = datetime.utcnow()
        for customer, mobile, address, days_ago, rooms, flow in JOBS:
            created = now - timedelta(days=days_ago)
            p = Project(customer_name=customer, mobile=mobile, address=address, created_by=admin.id,
                        discount_type='none', discount_value=0, status='complete', created_at=created, updated_at=created)
            db.session.add(p)
            db.session.flush()
            p.grand_total = _save_project_data(p, [{'name': r, 'items': [
                {'name': n, 'length': l, 'width': w, 'wood_type': wood, 'work_type': work} for n, l, w, wood, work in items]}
                for r, items in rooms])
            for to_stage, after, note in flow:
                when = created + timedelta(days=after)
                db.session.add(ProjectStageChange(project_id=p.id, from_stage=p.stage, to_stage=to_stage,
                                                  changed_by=admin.id, changed_at=when, note=note))
                p.stage, p.stage_changed_at = to_stage, when
        db.session.flush()
        # what the bell shows, worded as the app words them (app/share.py, app/projects.py)
        by = {p.customer_name: p for p in Project.query.all()}
        deepak, nisha, farhan = by['Deepak Test'], by['Nisha Placeholder'], by[MOVE]
        for title, message, p, hours in [
                (f'Payment received – {MOVE}', f'₹25,000.00 received from {MOVE} (Quotation #{farhan.id}) via Razorpay.\n'
                 f'Total Paid: ₹25,000.00  |  Balance: ₹{farhan.final_total - 25000:,.2f}', farhan, 1),
                (f'Changes requested on quotation #{nisha.id}', 'Nisha Placeholder asked for changes: '
                 'Can the crockery unit have glass shutters?', nisha, 5),
                (f'Quotation #{deepak.id} accepted', f'Deepak Test accepted the quotation for ₹{deepak.final_total:,.2f} online.',
                 deepak, 26)]:
            db.session.add(Notification(title=title, message=message, project_id=p.id, created_at=now - timedelta(hours=hours)))
        db.session.commit()
        print('jobs', Project.query.count())


def record(base, work, password):
    from playwright.sync_api import sync_playwright
    out = os.path.join(work, 'jobs')
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_context(viewport=WIN, device_scale_factor=WIN_DPR).new_page()
        rec = Screens(page, out, 0, '')
        page.goto(base + '/login')
        page.fill('input[name=username]', 'demo-admin')
        page.fill('input[name=password]', password)
        page.click('button[type=submit]')
        page.wait_for_timeout(800)

        # ── one screen: the pipeline ──
        page.goto(base + '/admin/dashboard')
        pipeline = page.locator('.card', has_text='Quotation Pipeline').first
        rec.top(pipeline)
        rec.snap('pipeline', box=pipeline)

        # ── the list, then only the jobs on site ──
        page.goto(base + '/projects')
        stages = page.locator('.ki-stage-filter')
        ongoing = stages.locator('a', has_text='Ongoing')
        rec.snap('list', tap=ongoing, box=stages)
        ongoing.click()
        page.wait_for_timeout(900)
        rec.snap('list_ongoing', box=page.locator('main, .container').first)

        # ── move a job to Ongoing, with a note ──
        page.goto(base + f'/projects?q={MOVE.split()[0]}')
        page.locator('a[href^="/projects/"]', has_text=MOVE).first.click()
        page.wait_for_timeout(1000)
        card = page.locator('.card', has_text='Project Stage').first
        rec.top(card)
        rec.snap('job', box=card)
        page.locator('#stageSelect').select_option('ongoing')
        page.fill('#stageNote', 'Carpenters on site, kitchen first')
        btn = page.get_by_role('button', name='Update stage')
        rec.snap('job_move', tap=btn, box=card)
        btn.click()
        page.wait_for_timeout(1200)
        card = page.locator('.card', has_text='Project Stage').first
        rec.top(card)
        rec.snap('job_moved', box=card)
        rec.snap('job_history', box=page.locator('.ki-stage-history'))

        # ── the bell ──
        page.evaluate('window.scrollTo(0, 0)')
        bell = page.locator('.ki-nav-bell:visible').first
        rec.snap('bell_tap', tap=bell)
        bell.click()
        page.wait_for_timeout(1000)
        rec.snap('bell', box=page.locator('main, .container').first)

        page.goto(base + '/projects')
        rec.snap('list_after', box=page.locator('.ki-stage-filter'))
        json.dump(Screens.marks, open(os.path.join(out, 'marks.json'), 'w'), indent=1)
        browser.close()


if __name__ == '__main__':
    if sys.argv[1] == '--setup':
        setup()
    else:
        record(*sys.argv[1:4])
