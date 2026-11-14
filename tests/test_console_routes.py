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
