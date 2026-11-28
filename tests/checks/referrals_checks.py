"""Partner program (app/referrals.py): applying from the app, approval and codes, signing up with a code, earnings from
the referred business's payments, leaving one out, payouts; the console's pages (run as the console)."""
import os, re, subprocess, sys
from datetime import date, datetime, timedelta
from cryptography.fernet import Fernet
from sqlalchemy import text
os.environ.pop('CONSOLE_VAULT_KEY', None)          # as on QA: payout details sealed with DATA_ENCRYPTION_KEY
os.environ.update(TENANT_MODE='1', TENANT_BASE_DOMAIN='quote-room.test',
                  MARKETING_SITE_URL='https://www.quote-room.test')
for k in ['DEMO_MODE', 'MARKETING_SITE', 'CONSOLE_MODE']: os.environ.pop(k, None)
from app import create_app, db, referrals, platform_switch, subscription
import json

ok = lambda label, cond: print(('PASS ' if cond else 'FAIL ') + label)
app = create_app('development'); app.config['WTF_CSRF_ENABLED'] = False
runner = app.test_cli_runner()
for slug in ('sharmaint', 'newbiz', 'freshco'):
    r = runner.invoke(args=['trial', 'create', slug, '--admin-password', 'pass-word-123'])
    ok(f'trial {slug} made', r.exit_code == 0)

today = date.today()
with app.app_context():
    from app.console import CONSOLE_DDL
    with db.engine.begin() as conn_:
        for ddl in CONSOLE_DDL:
            conn_.execute(text(ddl))
    platform_switch.set_value(referrals.KEY, json.dumps({'on': True, 'pct': 30, 'earn_months': 12, 'min_months': 2,
                                                          'payout_min': 1000, 'trial_days': 14}))
    platform_switch.forget(referrals.KEY)
    subscription.ensure_table()
    pay = lambda slug, rupees, paid_at, start, end, oid: db.session.execute(text(
        "INSERT INTO public.platform_payments (slug, plan, amount_paise, order_id, status, paid_at, plan_start, plan_end) "
        "VALUES (:s, '1m', :a, :o, 'paid', :at, :ps, :pe)"), {'s': slug, 'a': rupees * 100, 'o': oid, 'at': paid_at,
                                                             'ps': start, 'pe': end})
    pay('sharmaint', 599, datetime.utcnow() - timedelta(days=100), today - timedelta(days=100), today + timedelta(days=20), 'o1')
    pay('freshco', 599, datetime.utcnow() - timedelta(days=10), today - timedelta(days=10), today + timedelta(days=20), 'o2')
    db.session.commit()
    ok('settings read from the console (on, 30%, 12 months, 2 months, ₹1,000, 14 days)', referrals.settings() == dict(
        referrals.DEFAULTS, on=True))
    ok('eligible after 2+ months on a paid plan', referrals.eligibility('sharmaint')[0])
    e = referrals.eligibility('freshco')
    ok('not yet after 10 days: says how long to go', not e[0] and 'more month' in e[1])
    ok('a trial that never paid: not eligible', not referrals.eligibility('newbiz')[0])

S, F = 'http://sharmaint.quote-room.test', 'http://freshco.quote-room.test'
cs, cf = app.test_client(), app.test_client()
cs.post('/login', base_url=S, data={'username': 'admin', 'password': 'pass-word-123'})
cf.post('/login', base_url=F, data={'username': 'admin', 'password': 'pass-word-123'})
ok('Admin menu has Partner program', '/refer' in cs.get('/projects', base_url=S).text)
t = cs.get('/refer', base_url=S).text
ok('the page explains it (the trial earns nothing) and shows the application form', 'How it works' in t and 'only once it' in t and 'The trial earns nothing' in t
   and 'name="pan"' in t and 'action" value="apply"' in t)
ok('…a business not eligible yet sees why, and no form', 'more month' in cf.get('/refer', base_url=F).text
   and 'value="apply"' not in cf.get('/refer', base_url=F).text)
form = {'action': 'apply', 'name': 'Suresh Sharma', 'phone': '9876500001', 'city': 'Hyderabad', 'business': 'Sharma Interiors',
        'email': 's@sharma.example', 'upi': 'suresh@okhdfc', 'pan': '', 'agree': '1'}
r = cs.post('/refer', base_url=S, data=form)
ok('PAN is needed', 'Enter your PAN' in r.text)
r = cs.post('/refer', base_url=S, data=dict(form, pan='abcde1234f'), follow_redirects=True)
ok('applied: waiting for approval, can\'t start yet', 'Application received' in r.text and 'once it\'s approved' in r.text)
with app.app_context():
    p = referrals.get('sharmaint')
    ok('saved as applied, payout details sealed (not readable in the table)', p['status'] == 'applied'
       and 'suresh@okhdfc' not in (p['payout'] or '') and referrals.payout_details(p)['pan'] == 'ABCDE1234F')
    p = referrals.approve('sharmaint')
    code = p['code']
    ok(f'approved with a QR + 4 digit code ({code})', re.fullmatch(r'QR\d{4}', code) is not None)
    try:
        referrals.approve('freshco', code)
        taken = False
    except referrals.ReferralError:
        taken = True
    ok('…another business can\'t take the same code', taken)
t = cs.get('/refer', base_url=S).text
ok('the approved page: code, link with the code, WhatsApp share, earnings', code in t
   and f'https://www.quote-room.test/free-trial?ref={code}' in t and 'wa.me' in t and 'Your earnings' in t)
ok('…says plainly how long: 30% of every payment, for 12 months from its first payment', '30%' in t
   and 'for 12 months from its first payment' in t)

with app.app_context():
    ok('the code works for a sign-up (any case, spaces)', referrals.partner_for_signup(code.lower()[:2] + ' ' + code[2:], '9000000001'))
    ok('…not with the partner\'s own number (says why)', referrals.partner_for_signup(code, '+91 98765 00001') is None
       and 'self-referral' in referrals.check_signup(code, '+91 98765 00001')[1])
    ok('…not an unknown code', referrals.partner_for_signup('QR0000', '9000000001') is None)
    p = referrals.get('sharmaint')
    ok('newbiz linked to the partner', referrals.link('newbiz', p, 'New Biz Interiors', 7))
    ok('…a business keeps its first partner', not referrals.link('newbiz', p, 'again'))
    ok('…a partner can\'t refer itself', not referrals.link('sharmaint', p))
    refs = referrals.referrals('sharmaint')
    ok('referrals: newbiz on its free trial', [(r['business'], r['state']) for r in refs] == [('New Biz Interiors', 'trial')])
    # newbiz pays: ₹1,000 now, ₹3,000 later; a payment 13 months after its first is past the earning period
    first = datetime.utcnow() - timedelta(days=5)
    pay('newbiz', 1000, first, today - timedelta(days=5), today + timedelta(days=25), 'n1')
    db.session.commit()
    ok('sync records the payment once', referrals.sync() == 1 and referrals.sync() == 0)
    tot = referrals.totals('sharmaint')
    ok('30% of ₹1,000 = ₹300 owed; below ₹1,000 so not due yet', tot['balance'] == 30000 and tot['this_month'] in (0, 30000)
       and not referrals.due())
    pay('newbiz', 3000, datetime.utcnow(), today, today + timedelta(days=60), 'n2')
    pay('newbiz', 2000, first + timedelta(days=400), today, today + timedelta(days=60), 'n3')
    db.session.commit()
    referrals.sync()
    es = {e['payment_id']: e for e in referrals.earnings('sharmaint')}
    ok('₹3,000 earns ₹900; the one 13 months on is outside the 12 months',
       sorted(e['earned_paise'] for e in es.values()) == [0, 30000, 90000]
       and [e['status'] for e in es.values() if e['earned_paise'] == 0] == ['outside'])
    ok('₹1,200 owed: due for payout now', referrals.totals('sharmaint')['balance'] == 120000
       and [p_['slug'] for p_, _ in referrals.due()] == ['sharmaint'])
    big = next(e for e in es.values() if e['earned_paise'] == 90000)
    referrals.exclude(big['id'], 'Sign-up from the same office.')
    ok('leave a payment out (misuse): not counted, with the reason', referrals.totals('sharmaint')['balance'] == 30000
       and any(e['reason'] == 'Sign-up from the same office.' for e in referrals.earnings('sharmaint')))
    referrals.include(big['id'])
    ok('…count it again', referrals.totals('sharmaint')['balance'] == 120000)
    # the partner's own earning period (here 1 month) replaces the default 12
    referrals.update('sharmaint', None, None, 1)
    pay('newbiz', 1500, first + timedelta(days=40), today, today + timedelta(days=60), 'n5')
    db.session.commit()
    referrals.sync()
    late = next(e for e in referrals.earnings('sharmaint') if e['amount_paise'] == 150000)
    ok('a partner\'s own months: a payment 40 days after the first is outside their 1 month (says so)',
       late['status'] == 'outside' and 'the 1 month you earn' in (late['reason'] or '') and referrals.months_of(referrals.get('sharmaint')) == 1)
    referrals.update('sharmaint', None, None, None)
    ok('…back to the default', referrals.months_of(referrals.get('sharmaint')) == 12)
    referrals.mark_paid('sharmaint', '1,200', 'UTR123', today)
    t_ = referrals.totals('sharmaint')
    ok('payout recorded: nothing owed, ₹1,200 paid', t_['balance'] == 0 and t_['paid'] == 120000 and not referrals.due())
    ok('referrals: newbiz now paying', referrals.referrals('sharmaint')[0]['state'] == 'paying')
    # the partner's own plan lapses: new payments don't count
    db.session.execute(text("UPDATE public.platform_payments SET plan_end = :d WHERE slug = 'sharmaint'"),
                       {'d': today - timedelta(days=1)})
    pay('newbiz', 500, datetime.utcnow(), today, today + timedelta(days=30), 'n4')
    db.session.commit()
    referrals.sync()
    ok('partner\'s plan lapsed: the payment doesn\'t count (says why)',
       any(e['status'] == 'inactive' and e['amount_paise'] == 50000 for e in referrals.earnings('sharmaint'))
       and referrals.partner_for_signup(code, '9000000002') is None)
t = cs.get('/refer', base_url=S).text
ok('partner page: paused banner, referrals, payments and payout listed', 'Earning is paused' in t and 'New Biz Interiors' in t
   and 'UTR123' in t and 'After the earning period' in t)

# The website: the Partner code box (from the console's copy of the rules), ?ref= fills it, a bad code is refused
os.environ.update(MARKETING_SITE='1', AUTO_TRIALS='1', SIGNUP_URL='https://ops.quote-room.test', SIGNUP_SECRET='s3cret')
os.environ.pop('TENANT_MODE')
site = create_app('development'); site.config['WTF_CSRF_ENABLED'] = False
with site.app_context():
    from app.models import AppSetting
    db.create_all()
    AppSetting.set(referrals.KEY, json.dumps({'on': True, 'trial_days': 14})); db.session.commit()
sc = site.test_client()
ft = sc.get(f'/free-trial?ref={code}').text
ok('website: the trial form has the Partner code box, filled from ?ref=', 'name="ref_code"' in ft and f'value="{code}"' in ft
   and '14-day free trial' in ft)
r = sc.post('/trial-request', data={'name': 'Ravi', 'company_name': 'Ravi Kitchens', 'phone': '9000011111', 'city': 'Pune',
                                    'email': 'r@ravi.example', 'business_type': 'kitchens', 'ref_code': 'no!'},
            headers={'Accept': 'application/json'})
ok('…a code that isn\'t one is refused', r.status_code == 400 and 'ref_code' in r.get_json()['errors'])
r = sc.post('/trial-request', data={'name': 'Ravi', 'company_name': 'Ravi Kitchens', 'phone': '9000011111', 'city': 'Pune',
                                    'email': 'r@ravi.example', 'business_type': 'kitchens', 'ref_code': code.lower()},
            headers={'Accept': 'application/json'})
with site.app_context():
    from app.models import Lead
    lead = Lead.query.order_by(Lead.id.desc()).first()
    ok('…a good one is kept with the request for the console', r.status_code == 200 and lead
       and AppSetting.get(referrals.LEAD_REF_KEY.format(lead.id)) == code)
ok('website: two buttons, Free trial / Buy a plan; the plans in a dialog', 'name="buy_mode"' in ft and '>Buy a plan<' in ft
   and 'data-plan-dialog' in ft and 'data-pick-plan="1y"' in ft and 'Choose a plan' in ft)
r2 = sc.post('/trial-request', data={'name': 'Mohan', 'company_name': 'Mohan Interiors', 'phone': '9000022222', 'city': 'Pune',
                                     'email': 'm@mohan.example', 'business_type': 'kitchens', 'ref_code': code, 'plan': '1y'},
             headers={'Accept': 'application/json'})
with site.app_context():
    lead2 = Lead.query.order_by(Lead.id.desc()).first()
    ok('…choosing a plan goes on to pay, with the code kept', r2.status_code == 200 and 'plan=1y' in (r2.get_json().get('pay_url') or '')
       and AppSetting.get(referrals.LEAD_REF_KEY.format(lead2.id)) == code)
terms = sc.get('/terms').text
ok('Terms: the Partner program section with the misuse clause', 'id="refer-earn"' in terms and 'leave out any payment' in terms)

# The console (its own app): rules, applications, partner page, actions
code_ = r'''
import os, sys, time, json
from werkzeug.security import generate_password_hash
os.environ.update(CONSOLE_MODE='1', CONSOLE_PASSWORD_HASH=generate_password_hash('console-pass-123', method='pbkdf2:sha256'),
                  CONSOLE_TOTP_SECRET='JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP')
for k in ['TENANT_MODE', 'MARKETING_SITE', 'DEMO_MODE']: os.environ.pop(k, None)
from app import create_app
from app.console import totp_code
app = create_app('development'); app.config['WTF_CSRF_ENABLED'] = False
c = app.test_client()
c.post('/login', data={'password': 'console-pass-123', 'code': totp_code('JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP', int(time.time() // 30))})
ok = lambda label, cond: print(('PASS ' if cond else 'FAIL ') + label)
t = c.get('/partners').text
ok('console: Partner program page with partners and the rules', 'Sharma Interiors' in t and 'name="earn_months"' in t
   and 'name="before_gst"' in t and 'Partner program' in c.get('/').text)
d = c.get('/partners/sharmaint').text
ok('console: partner page shows UPI, PAN, payments, payouts and Leave out', 'suresh@okhdfc' in d and 'ABCDE1234F' in d
   and 'UTR123' in d and 'Leave out' in d)
c.post('/partners', data={'on': '1', 'pct': '25', 'earn_months': '6', 'min_months': '3', 'payout_min': '500', 'trial_days': '21'})
from app import db, referrals, platform_switch
with app.app_context():
    platform_switch.forget(referrals.KEY)
    s = referrals.settings()
ok('console: rules saved', s['pct'] == 25 and s['earn_months'] == 6 and s['min_months'] == 3 and s['payout_min'] == 500
   and s['trial_days'] == 21 and s['on'])
r = c.post('/partners', data={'on': '1', 'pct': '250', 'earn_months': '6', 'min_months': '3', 'payout_min': '500', 'trial_days': '21'},
           follow_redirects=True)
ok('console: a % over 100 refused', 'from 0 to 100' in r.text)
c.post('/partners/sharmaint/update', data={'code': 'QR7777', 'pct': '40', 'months': '24'})
with app.app_context():
    p = referrals.get('sharmaint')
ok('console: code, % and months changed', p['code'] == 'QR7777' and p['pct'] == 40 and p['earn_months'] == 24
   and '24 months' in c.get('/partners/sharmaint').text)
c.post('/partners/sharmaint/stop', data={'note': 'Spam messages.'})
c.post('/partners/waiver', data={'slug': 'newbiz', 'on': '1'})
c.post('/partners/waiver', data={'slug': 'nobody', 'on': '1'})
with app.app_context():
    ok('console: waive the months for a paying business (it can apply now); an unknown app refused',
       referrals.waived('newbiz') and referrals.eligibility('newbiz')[0] and not referrals.waived('nobody')
       and 'newbiz' in c.get('/partners').text)
c.post('/partners/waiver', data={'slug': 'newbiz'})
with app.app_context():
    ok('console: waiver removed', not referrals.waived('newbiz'))
c.post('/partners/sharmaint/link', data={'business_slug': 'freshco', 'business': 'Fresh Co'})
with app.app_context():
    ok('console: a business linked by hand (its earlier payment counted at once)',
       any(r['slug'] == 'freshco' for r in referrals.referrals('sharmaint'))
       and any(e['slug'] == 'freshco' for e in referrals.earnings('sharmaint')))
r = c.post('/partners/sharmaint/link', data={'business_slug': 'freshco'}, follow_redirects=True)
ok('console: …not twice', 'already linked' in r.text)
with app.app_context():
    ok('why a code didn\'t count: the partner is stopped', 'who is stopped' in referrals.check_signup('QR7777', '9000000009')[1])
# "Your app is ready": address, username and trial end (or the plan), never the password
import tempfile, glob, email as _em
from datetime import date as _d
_box = tempfile.mkdtemp(); os.environ['MAIL_OUTBOX_DIR'] = _box
from app.console import _app_ready_email
with app.app_context(), app.test_request_context():
    _app_ready_email({'name': 'Ravi Kumar', 'email': 'ravi@new.example'}, {'slug': 'newbiz', 'ends_on': _d(2026, 12, 10)},
                     'New Biz Interiors', 'ravi', None, 5)
    _app_ready_email({'name': 'Mohan', 'email': 'mohan@new.example'}, {'slug': 'freshco', 'ends_on': None},
                     'Fresh Co', 'mohan', '1y', 6)
_mails = [_em.message_from_bytes(open(f, 'rb').read()) for f in sorted(glob.glob(_box + '/*.eml'))]
_txt = lambda m: next(p_ for p_ in m.walk() if p_.get_content_type() == 'text/plain').get_payload(decode=True).decode()
_t1 = next(m for m in _mails if m['To'] == 'ravi@new.example')
_t2 = next(m for m in _mails if m['To'] == 'mohan@new.example')
ok('"Your app is ready" email: the app\'s sign-in link, the username and the trial end; no password',
   'Your QuoteRoom app is ready' in _t1['Subject'] and 'newbiz.quote-room.test/login?u=ravi' in _txt(_t1)
   and 'Username: ravi' in _txt(_t1) and '10 Dec 2026' in _txt(_t1) and 'the one you chose' in _txt(_t1))
ok('…buying a plan: says which, and that the receipt follows', '12-month plan' in _txt(_t2) and 'receipt' in _txt(_t2))
os.environ.pop('MAIL_OUTBOX_DIR')
with app.app_context():
    ok('console: stopped (code stops working)', referrals.get('sharmaint')['status'] == 'stopped'
       and referrals.partner_for_signup('QR7777', '9000000003') is None)
'''
env = dict(os.environ)
env.pop('MARKETING_SITE', None)
out = subprocess.run([sys.executable, '-c', code_], env=env, capture_output=True, text=True, timeout=300)
print(out.stdout.strip())
if out.returncode != 0 or 'Traceback' in out.stderr:
    print('FAIL console part crashed: ' + out.stderr[-1500:])
