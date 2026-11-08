"""Forgot password: admins get a reset link at the business's email; staff ask their admin."""
import glob, os, re, tempfile, time
from email import policy
from email.parser import BytesParser
from werkzeug.security import check_password_hash, generate_password_hash
from app import create_app, db
from app.models import AppSetting, User
ok = lambda label, cond: print(('PASS ' if cond else 'FAIL ') + label)
for k in ['DEMO_MODE', 'MARKETING_SITE']: os.environ.pop(k, None)
box = tempfile.mkdtemp()
os.environ['MAIL_OUTBOX_DIR'] = box
app = create_app('development'); app.config['WTF_CSRF_ENABLED'] = False
with app.app_context():
    db.session.add(User(username='staff1', password_hash=generate_password_hash('staff-pass-123'), role='employee'))
    AppSetting.set('company_email', 'pola.harshith2000@gmail.com')
    db.session.commit()
c = app.test_client()
mails = lambda: sorted(glob.glob(os.path.join(box, '*.eml')))

ok('the sign-in page links to Forgot password?', 'href="/forgot-password"' in c.get('/login').text)
r = c.post('/forgot-password', data={'username': 'owner'})
got = mails()
ok('an admin: "we\'ve sent a reset link to po*************00@gmail.com", and the email goes there',
   "sent a password reset link to your email address" in r.text.replace('&#39;', "'")
   and 'po*************00@gmail.com' in r.text and len(got) == 1)
msg = BytesParser(policy=policy.default).parse(open(got[0], 'rb'))
link = re.search(r'https?://\S+/reset-password/\S+', msg.get_body(('plain',)).get_content()).group(0)
ok('…to the business\'s email, with a link (1 hour, once)', msg['To'] == 'pola.harshith2000@gmail.com' and '1 hour' in msg.get_body(('plain',)).get_content())
c.post('/forgot-password', data={'username': 'owner'})
ok('…asking again straight away doesn\'t send another (one every 2 minutes)', len(mails()) == 1)
r = c.post('/forgot-password', data={'username': 'staff1'})
r2 = c.post('/forgot-password', data={'username': 'nobody'})
ok('staff (or an unknown username): "ask your admin", no email', 'Only admins can reset' in r.text
   and 'Only admins can reset' in r2.text and len(mails()) == 1)
path = link.split('://', 1)[1].split('/', 1)[1]
r = c.post('/' + path, data={'password': 'short', 'password2': 'short'})
ok('the link: a short password is refused', 'At least 8' in r.text or 'at least 8' in r.text)
r = c.post('/' + path, data={'password': 'brand-new-pass', 'password2': 'brand-new-pass'})
with app.app_context():
    owner = User.query.filter_by(username='owner').first()
ok('…a new password saved, then back to sign in', r.status_code == 302 and '/login' in r.headers['Location']
   and check_password_hash(owner.password_hash, 'brand-new-pass'))
r = c.get('/' + path)
ok('…and the link works only once', r.status_code == 400 and 'expired' in r.text)
r = c.post('/login', data={'username': 'owner', 'password': 'brand-new-pass'})
ok('signing in with the new password works', r.status_code == 302)
ok('a made-up link is refused', c.get('/reset-password/not-a-real-token').status_code == 400)
with app.app_context():
    AppSetting.set('company_email', ''); AppSetting.set('password_reset_sent', ''); db.session.commit()
r = app.test_client().post('/forgot-password', data={'username': 'owner'})
ok('no email on the business: "message us", nothing sent', "can't email a reset link" in r.text.replace('&#39;', "'")
   and len(mails()) == 1)
from app.password_reset import mask
ok('the address is masked: first and last two letters', mask('pola.harshith2000@gmail.com') == 'po*************00@gmail.com'
   and mask('ab@x.in') == 'a*@x.in')
