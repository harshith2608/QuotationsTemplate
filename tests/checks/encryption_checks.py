import os, subprocess, sys
from sqlalchemy import text
from cryptography.fernet import Fernet
from app import create_app, db, crypto
from app.models import AppSetting, Project
from app.seed import encrypt_existing_data
ok = lambda label, cond: print(('PASS ' if cond else 'FAIL ') + label)
assert crypto.enabled(), 'run with DATA_ENCRYPTION_KEY set'
app = create_app('development'); app.config['WTF_CSRF_ENABLED'] = False
raw = lambda sql: db.session.execute(text(sql)).scalars().all()

with app.app_context():
    checks = {
        'customer names': 'SELECT customer_name FROM projects', 'mobiles': 'SELECT mobile FROM projects',
        'emails': 'SELECT email FROM projects WHERE email IS NOT NULL', 'addresses': 'SELECT address FROM projects WHERE address IS NOT NULL',
        'quotation totals': 'SELECT grand_total FROM projects', 'payments': 'SELECT amount FROM payments',
        'payment notes': 'SELECT note FROM payments WHERE note IS NOT NULL',
        'material rates': 'SELECT rate_per_sqft FROM item_rates', 'fitting prices': 'SELECT unit_price FROM items WHERE unit_price IS NOT NULL',
        'price list': 'SELECT price FROM price_list_items',
        'bank account number': "SELECT value FROM app_settings WHERE key = 'account_number'",
    }
    for label, sql in checks.items():
        vals = raw(sql)
        ok(f'{label} encrypted in the database ({len(vals)} rows)', vals and all(str(v).startswith('enc1:') for v in vals))
    ok('names never stored in plain text', not any('Priya' in str(v) for v in raw('SELECT customer_name FROM projects')))
    ok('company branding stays plain (not secret)', raw("SELECT value FROM app_settings WHERE key = 'company_name'") == ['Demo Interiors'])
    ok('same value encrypts differently each time', crypto.encrypt('x') != crypto.encrypt('x'))
    ok('app reads decrypted values', any(p.customer_name == 'Priya Example' for p in Project.query.all())
       and AppSetting.get('account_number') == '000012345678')

c = app.test_client(); c.post('/login', data={'username': 'demo-admin', 'password': 'demo1234'})
t = c.get('/projects').text
ok('list page shows names', 'Priya Example' in t)
t = c.get('/projects?q=priya').text
ok('search by part of a name works', 'Priya Example' in t and 'Meera Test' not in t)
ok('search by part of a mobile works', 'Priya Example' in c.get('/projects?q=00000001').text)
ok('search with no match', 'Priya Example' not in c.get('/projects?q=zzzz').text)
ok('dashboard renders', c.get('/admin/dashboard').status_code == 200)
c.post('/admin/payment-settings', data={'razorpay_key_id': 'rzp_test_x', 'razorpay_key_secret': 'sekret-123',
                                         'webhook_secret': 'whsec-456', 'account_number': '999'})
with app.app_context():
    vals = raw("SELECT value FROM app_settings WHERE key IN ('razorpay_key_secret','webhook_secret')")
    ok('Razorpay secrets saved encrypted, read back plain', len(vals) == 2 and all(v.startswith('enc1:') for v in vals)
       and AppSetting.get('razorpay_key_secret') == 'sekret-123')

# Upgrading an older database: plain values keep working, then get encrypted
with app.app_context():
    pid = raw('SELECT id FROM projects ORDER BY id')[0]
    db.session.execute(text("UPDATE projects SET customer_name='Legacy Person', grand_total='1234.5' WHERE id=:i"), {'i': pid})
    db.session.execute(text("UPDATE app_settings SET value='plain-acct' WHERE key='account_number'"))
    db.session.commit(); db.session.expire_all()
    p = db.session.get(Project, pid)
    ok('old plain values still readable', p.customer_name == 'Legacy Person' and p.grand_total == 1234.5)
    line = encrypt_existing_data()
    ok(f'encrypt-data encrypts leftovers ({line})', 'projects (1)' in line and 'app_settings (1)' in line)
    db.session.expire_all(); p = db.session.get(Project, pid)
    ok('…and they read back the same', p.customer_name == 'Legacy Person' and p.grand_total == 1234.5
       and AppSetting.get('account_number') == 'plain-acct'
       and raw(f'SELECT customer_name FROM projects WHERE id={pid}')[0].startswith('enc1:'))
    ok('running it again changes nothing', encrypt_existing_data() == 'Encryption: all data already encrypted.')

    # Key rotation and wrong keys
    old = os.environ['DATA_ENCRYPTION_KEY']; new = Fernet.generate_key().decode()
    os.environ['DATA_ENCRYPTION_KEY'] = f'{new},{old}'; db.session.expire_all()
    ok('rotation: "new,old" still reads old data', db.session.get(Project, pid).customer_name == 'Legacy Person')
    ok('rotation: new writes use the new key', Fernet(new.encode()).decrypt(crypto.encrypt('hi')[5:].encode()) == b'hi')
    os.environ['DATA_ENCRYPTION_KEY'] = Fernet.generate_key().decode(); db.session.expire_all()
    try:
        db.session.get(Project, pid).customer_name; ok('wrong key → clear error', False)
    except crypto.EncryptionError as e:
        ok('wrong key → clear error', 'different key' in str(e))
    db.session.rollback()
    os.environ['DATA_ENCRYPTION_KEY'] = old

# Startup checks
code = ("import os; os.environ.update(FLASK_ENV='production', SECRET_KEY='x', DATABASE_URL='sqlite:///:memory:'); "
        "os.environ.pop('DATA_ENCRYPTION_KEY', None); from app import create_app; create_app('production')")
r = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True)
ok('production refuses to start without DATA_ENCRYPTION_KEY', r.returncode != 0 and 'DATA_ENCRYPTION_KEY' in r.stderr)
r = subprocess.run([sys.executable, '-c', "import os; os.environ['DATA_ENCRYPTION_KEY']='not-a-key'; "
                    "from app import create_app; create_app('development')"], capture_output=True, text=True)
ok('invalid key → refuses to start with a clear message', r.returncode != 0 and 'not a valid key' in r.stderr)

# Export for a customer's data request: decrypted CSVs, no password hashes or API secrets
import csv, tempfile
out = tempfile.mkdtemp(dir=os.environ.get('TEST_OUTPUT_DIR'))
r = app.test_cli_runner().invoke(args=['export-data', out])
proj = list(csv.DictReader(open(os.path.join(out, 'projects.csv'))))
users = open(os.path.join(out, 'users.csv')).read()
sets = {row['key']: row['value'] for row in csv.DictReader(open(os.path.join(out, 'app_settings.csv')))}
ok('export-data writes decrypted CSVs', r.exit_code == 0 and any(p['customer_name'] == 'Meera Test' for p in proj)
   and not any('enc1:' in v for p in proj for v in p.values()))
ok('export leaves out password hashes and API secrets, keeps bank details',
   'password_hash' not in users and 'razorpay_key_secret' not in sets and 'logo_png' not in sets
   and sets.get('account_number') == 'plain-acct')
