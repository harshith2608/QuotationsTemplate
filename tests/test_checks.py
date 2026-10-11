"""
Runs every script in tests/checks/ against its own fresh database.

    python -m pytest tests -q

Each check script prints one line per check, starting with PASS or FAIL.
A script passes when it prints at least one PASS, no FAIL and no traceback.

SQLite is used by default. The multi-tenant (trials) checks need Postgres and
are skipped unless these are set to two EMPTY throwaway databases:
    TEST_PG_URL         trials database
    TEST_PG_TARGET_URL  "dedicated" database used by `trial convert`
Never point these at a real database: the checks create and delete data.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

TEST_KEY = 'q8b1iX0Hn6Jx7m0lF3Yp9cG2sV5tR4wK1zA0eD6uB3o='   # test-only Fernet key; data is encrypted in every test
ROOT = Path(__file__).resolve().parent.parent
CHECKS = Path(__file__).resolve().parent / 'checks'

# check module → how its database is prepared
SETUP = {
    'demo_checks': 'seed', 'fixed_checks': 'seed', 'guides_checks': 'seed', 'landing_checks': 'seed',
    'legal_checks': 'seed', 'plan_checks': 'seed', 'settings_checks': 'seed', 'smoke_checks': 'seed',
    'stage_checks': 'seed', 'totals_checks': 'seed', 'webhook_checks': 'seed',
    'encryption_checks': 'seed', 'leads_checks': 'seed', 'lock_checks': 'bootstrap', 'tenant_checks': 'postgres',
}

# env vars from the developer's shell/.env that would change app behaviour
SCRUB = ('DATA_ENCRYPTION_KEY', 'TARGET_DATA_ENCRYPTION_KEY', 'DEMO_MODE', 'MARKETING_SITE', 'TENANT_MODE', 'TENANT_BASE_DOMAIN', 'LOCK_COMPANY_DETAILS',
         'SUPPORT_WHATSAPP', 'CRON_SECRET', 'FLASK_ENV', 'FLASK_CONFIG')


def _env(database_url, **extra):
    env = {k: v for k, v in os.environ.items()
           if k not in SCRUB and not k.startswith(('COMPANY_', 'BRAND_', 'MARKETING_', 'SIGNATORY_',
                                                    'ADMIN_', 'MAIL_', 'RAZORPAY_', 'PLAN_'))}
    env.update(DATABASE_URL=database_url, FLASK_APP='run.py', PYTHONPATH=str(ROOT),
               SECRET_KEY='test-secret-key', DATA_ENCRYPTION_KEY=TEST_KEY, **extra)
    return env


def _flask(env, *args):
    r = subprocess.run([sys.executable, '-m', 'flask', *args], cwd=ROOT, env=env,
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, f'flask {" ".join(args)} failed:\n{r.stdout}\n{r.stderr}'


def test_every_check_script_is_registered():
    found = {p.stem for p in CHECKS.glob('*_checks.py')}
    assert found == set(SETUP), f'add new check scripts to SETUP: {sorted(found ^ set(SETUP))}'


@pytest.mark.parametrize('module', sorted(SETUP))
def test_checks(module, tmp_path):
    kind = SETUP[module]
    if kind == 'postgres':
        url, target = os.environ.get('TEST_PG_URL'), os.environ.get('TEST_PG_TARGET_URL')
        if not (url and target):
            pytest.skip('set TEST_PG_URL and TEST_PG_TARGET_URL to run the Postgres trials checks')
        env = _env(url, TEST_PG_TARGET_URL=target)
        _flask(_env(target), 'db', 'upgrade')
    else:
        env = _env(f'sqlite:///{tmp_path / "test.db"}', TEST_OUTPUT_DIR=str(tmp_path))
        _flask(env, 'db', 'upgrade')
        if kind == 'seed':
            _flask(env, 'seed-demo')
        else:
            env.update(ADMIN_USERNAME='owner', ADMIN_PASSWORD='owner-pass-123')
            _flask(env, 'bootstrap')

    r = subprocess.run([sys.executable, str(CHECKS / f'{module}.py')], cwd=ROOT, env=env,
                       capture_output=True, text=True, timeout=600)
    out = r.stdout + r.stderr
    lines = out.splitlines()
    fails = [l for l in lines if l.startswith('FAIL')]
    assert r.returncode == 0 and 'Traceback' not in out, out
    assert not fails, '\n'.join(fails)
    assert any(l.startswith('PASS') for l in lines), out
