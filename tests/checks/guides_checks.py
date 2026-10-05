import io, os, smtplib, urllib.error, urllib.request
from unittest import mock
from app import create_app, db
from app.models import AppSetting
for k in ['DEMO_MODE']: os.environ.pop(k, None)
app = create_app('development'); app.config['WTF_CSRF_ENABLED'] = False
c = app.test_client(); c.post('/login', data={'username': 'demo-admin', 'password': 'demo1234'})
ok = lambda label, cond: print(('PASS ' if cond else 'FAIL ') + label)
def setk(**kv):
    with app.app_context():
        for k, v in kv.items(): AppSetting.set(k, v)
        db.session.commit()

# ── Payment settings guide ──
setk(razorpay_key_id='', razorpay_key_secret='', webhook_secret='')
t = c.get('/admin/payment-settings').text
ok('guide open when not configured', '<details class="ki-guide mt-3 border-top pt-3" open>' in t and 'Setup incomplete' in t)
ok('8 steps incl. webhook URL + success@razorpay', t.count('<h6>') == 8 and 'http://localhost/webhook/razorpay' in t and 'success@razorpay' in t)
ok('test button disabled without keys', 'btn-sm disabled>' in t.replace('" disabled>', ' disabled>'))
r = c.post('/admin/payment-settings/test', follow_redirects=True)
ok('test without keys → helpful warning', 'Save your Razorpay Key ID and Key Secret first' in r.text)

setk(razorpay_key_id='rzp_test_ABC', razorpay_key_secret='sec', webhook_secret='wh')
t = c.get('/admin/payment-settings').text
ok('ready: TEST badge, guide collapsed', 'TEST mode' in t and 'Ready to take payments' in t and '<details class="ki-guide mt-3 border-top pt-3" >' in t)
class FakeResp:
    def __enter__(self): return self
    def __exit__(self, *a): return False
with mock.patch('urllib.request.urlopen', return_value=FakeResp()) as m:
    r = c.post('/admin/payment-settings/test', follow_redirects=True)
    sent = m.call_args[0][0]
ok('keys valid → success message', 'Connected to Razorpay in TEST mode' in r.text and sent.full_url.startswith('https://api.razorpay.com/v1/payment_links'))
err = urllib.error.HTTPError('u', 401, 'Unauthorized', {}, io.BytesIO(b''))
with mock.patch('urllib.request.urlopen', side_effect=err):
    r = c.post('/admin/payment-settings/test', follow_redirects=True)
ok('bad keys → clear message', 'Razorpay rejected these keys' in r.text)
setk(razorpay_key_id='rzp_live_XYZ')
ok('live keys → LIVE badge', 'LIVE mode' in c.get('/admin/payment-settings').text)

# ── Email guide ──
setk(smtp_host='', smtp_user='', smtp_pass='', admin_email='')
t = c.get('/admin/settings?tab=email').text
ok('email guide open + quick-fill buttons', 'Not set up yet' in t and 'Create an App Password' in t
   and 'data-smtp="smtp.gmail.com"' in t and 'myaccount.google.com/apppasswords' in t)
r = c.post('/admin/settings/test-email', follow_redirects=True)
ok('test without settings → warning', 'Fill in SMTP host, username, password and admin email first.' in r.text)

setk(smtp_host='smtp.gmail.com', smtp_port='587', smtp_user='me@gmail.com', smtp_pass='app-pass', admin_email='owner@example.com')
ok('ready: test button names recipient', 'Send test email to owner@example.com' in c.get('/admin/settings?tab=email').text)
with mock.patch('smtplib.SMTP') as smtp:
    r = c.post('/admin/settings/test-email', follow_redirects=True)
    inst = smtp.return_value.__enter__.return_value
ok('587 uses STARTTLS and sends', inst.starttls.called and inst.send_message.called and 'Test email sent to owner@example.com' in r.text)
with mock.patch('smtplib.SMTP') as smtp:
    smtp.return_value.__enter__.return_value.login.side_effect = smtplib.SMTPAuthenticationError(535, b'bad')
    r = c.post('/admin/settings/test-email', follow_redirects=True)
ok('bad password → App Password hint', 'use an App Password' in r.text)
setk(smtp_port='465')
with mock.patch('smtplib.SMTP_SSL') as ssl_smtp, mock.patch('smtplib.SMTP') as plain:
    r = c.post('/admin/settings/test-email', follow_redirects=True)
ok('465 uses SSL', ssl_smtp.called and not plain.called and 'Test email sent' in r.text)

# ── Demo mode blocks the test buttons ──
os.environ['DEMO_MODE'] = '1'
d = create_app('development'); d.config['WTF_CSRF_ENABLED'] = False
dc = d.test_client(); dc.get('/demo')
r1 = dc.post('/admin/settings/test-email', follow_redirects=True); r2 = dc.post('/admin/payment-settings/test', follow_redirects=True)
ok('demo blocks test email / test connection', 'disabled in the demo' in r1.text and 'disabled in the demo' in r2.text)
os.environ.pop('DEMO_MODE')
