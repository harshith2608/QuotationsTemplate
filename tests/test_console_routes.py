"""The console's public pages are served by the right functions (no Postgres needed, unlike console_checks).

A helper put between a route's decorator and its function silently takes over the page (12 Nov 2026: /start, the
trial set-up page, answered with an empty page for two days). These run in a separate process with the console on.
"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SCRIPT = r'''
from app import create_app
app = create_app('development')
rules = {r.rule: r.endpoint for r in app.url_map.iter_rules()}
want = {'/start': 'console.start_trial', '/start/check': 'console.start_check', '/start/pay': 'console.start_pay',
        '/start/paid': 'console.start_paid'}
bad = {p: rules.get(p) for p, e in want.items() if rules.get(p) != e}
helpers = sorted(r.rule for r in app.url_map.iter_rules() if app.view_functions[r.endpoint].__name__.startswith('_'))
print('BAD', bad) if bad else None
print('HELPERS', helpers) if helpers else None
print('OK')
'''


def test_console_public_routes(tmp_path):
    env = {k: v for k, v in os.environ.items() if k not in ('TENANT_MODE', 'MARKETING_SITE', 'DEMO_MODE')}
    env.update(CONSOLE_MODE='1', DATABASE_URL=f'sqlite:///{tmp_path / "c.db"}', SECRET_KEY='test', PYTHONPATH=str(ROOT))
    r = subprocess.run([sys.executable, '-c', SCRIPT], cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
    out = r.stdout + r.stderr
    assert r.returncode == 0 and 'OK' in out, out
    assert 'BAD' not in out and 'HELPERS' not in out, out


RENDER = r"""
from datetime import datetime
from app import create_app
from flask import render_template, session
app = create_app('development')
u = dict(users=3, admins=1, staff=2, quotations=12, quotes_7d=2, quotes_30d=9, drafts=1, won=4, templates=2, links=5,
         responses=1, invoices=None, payments=0, saved_lines=40, fittings=7, photos=3, material_lists=0,
         last_seen_at=datetime.utcnow(), company_name='Sharma Interiors', company_set=True, logo_set=False, setup_tour='')
rows = [dict(kind='trial', slug='sharma', badge=('running', 'b-active'), url='#', href='/trials/sharma', u=u, error=None),
        dict(kind='customer', slug='kundu', badge=('1 month', 'b-active'), url='#', href='/customers/kundu', u=None,
             error='could not connect', name='Kundu Designs')]
with app.test_request_context('/usage'):
    session['console_at'] = 1
    html = render_template('console/usage.html', rows=rows, totals={k: 1 for k in u}, trials=1, customers=1)
assert 'Sharma Interiors' in html and 'could not connect' in html and '(1+2)' in html and '>Usage<' in html, html[:500]
print('OK')
"""


def test_console_usage_page_renders(tmp_path):
    env = {k: v for k, v in os.environ.items() if k not in ('TENANT_MODE', 'MARKETING_SITE', 'DEMO_MODE')}
    env.update(CONSOLE_MODE='1', DATABASE_URL=f'sqlite:///{tmp_path / "c.db"}', SECRET_KEY='test', PYTHONPATH=str(ROOT))
    r = subprocess.run([sys.executable, '-c', RENDER], cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
    out = r.stdout + r.stderr
    assert r.returncode == 0 and 'OK' in out, out
