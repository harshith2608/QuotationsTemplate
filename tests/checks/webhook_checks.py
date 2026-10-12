import hmac, hashlib, json, os
from app import create_app, db
from app.models import AppSetting, Payment, Project, Notification, PaymentLink
os.environ.pop('DEMO_MODE', None)
app = create_app('development'); c = app.test_client()
ok = lambda label, cond: print(('PASS ' if cond else 'FAIL ') + label)
def payload(project_id, pay_id, paise):
    return json.dumps({'event': 'payment_link.paid', 'payload': {
        'payment_link': {'entity': {'id': 'plink_test1', 'notes': {'project_id': str(project_id)}}},
        'payment': {'entity': {'id': pay_id, 'amount': paise}}}}).encode()
def post(body, secret=None, sig=None):
    if sig is None and secret:
        sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return c.post('/webhook/razorpay', data=body, headers={'X-Razorpay-Signature': sig or '', 'Content-Type': 'application/json'})
count = lambda pid: Payment.query.filter_by(project_id=pid).count()

with app.app_context():
    AppSetting.set('webhook_secret', ''); db.session.commit(); before = count(3)
r = post(payload(3, 'pay_FAKE', 99900000))
with app.app_context():
    ok('no secret configured → rejected, nothing recorded', r.status_code == 400 and count(3) == before)

with app.app_context():
    AppSetting.set('webhook_secret', 'whsec_test'); db.session.commit()
r = post(payload(3, 'pay_FORGED', 99900000), sig='deadbeef')
with app.app_context():
    ok('wrong signature → rejected', r.status_code == 400 and count(3) == before)

r = post(payload(3, 'pay_REAL1', 2500000), secret='whsec_test')
with app.app_context():
    p = Payment.query.filter_by(razorpay_payment_id='pay_REAL1').first()
    ok(f'valid signed webhook → payment recorded (was a crash before) [{r.status_code}]',
       r.status_code == 200 and p is not None and p.amount == 25000.0 and p.source == 'razorpay')
    ok('admin notification created', sum('25,000.00' in n.message for n in Notification.query.all()) == 1)
r = post(payload(3, 'pay_REAL1', 2500000), secret='whsec_test')
with app.app_context():
    ok('duplicate delivery ignored', r.get_json().get('status') == 'duplicate' and Payment.query.filter_by(razorpay_payment_id='pay_REAL1').count() == 1)
body = json.dumps({'event': 'payment.captured', 'payload': {}}).encode()
ok('other events acknowledged and ignored', post(body, secret='whsec_test').get_json().get('status') == 'ignored')

# ── Payment links: choose the amount; clear message when Razorpay's per-payment limit is hit ──
import io, urllib.error
from unittest import mock
sent = []
class _Resp(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *a): return False
def fake_urlopen(req, timeout=None):
    body = json.loads(req.data)
    sent.append(body)
    if body['amount'] > 5000000:          # pretend the account's limit is ₹50,000
        raise urllib.error.HTTPError(req.full_url, 400, 'Bad Request', {}, io.BytesIO(json.dumps(
            {'error': {'description': 'amount exceeds maximum amount allowed.'}}).encode()))
    return _Resp(json.dumps({'id': f'plink_{len(sent)}', 'short_url': f'https://rzp.io/i/x{len(sent)}'}).encode())

with app.app_context():
    AppSetting.set('razorpay_key_id', 'rzp_test_x'); AppSetting.set('razorpay_key_secret', 's'); db.session.commit()
    proj = db.session.get(Project, 1)
    due = round(proj.final_total - sum(p.amount for p in proj.payments), 2)
app.config['WTF_CSRF_ENABLED'] = False
uc = app.test_client(); uc.post('/login', data={'username': 'demo-admin', 'password': 'demo1234'})
page = uc.get('/projects/1').text
ok('payment link box prefilled with the balance', f'value="{due:.2f}"' in page and 'id="payLinkAmount"' in page)
with mock.patch('urllib.request.urlopen', fake_urlopen):
    r = uc.post('/projects/1/payment-link', json={'amount': '25000'})
    ok('link for a chosen part amount (advance)', r.status_code == 200 and r.json['amount'] == 25000
       and sent[-1]['amount'] == 2500000 and '(part payment)' in sent[-1]['description'])
    r = uc.post('/projects/1/payment-link', json={})
    ok('no amount → whole balance (as before)', r.status_code == 200 and abs(sent[-1]['amount'] - round(due * 100)) <= 1
       or (r.status_code == 400 and 'per-payment limit' in r.json['error']))
    r = uc.post('/projects/1/payment-link', json={'amount': str(due + 1)})
    ok('more than the balance is refused', r.status_code == 400 and 'more than the balance' in r.json['error'])
    r = uc.post('/projects/1/payment-link', json={'amount': 'abc'})
    ok('non-number refused politely', r.status_code == 400 and 'Enter the amount' in r.json['error'])
    if due > 50000:
        r = uc.post('/projects/1/payment-link', json={'amount': '76000'})
        ok('Razorpay limit → clear explanation, not the raw message', r.status_code == 400
           and 'per-payment limit' in r.json['error'] and 'smaller amount' in r.json['error'])
with app.app_context():
    links = PaymentLink.query.filter(PaymentLink.razorpay_link_id.like('plink_%')).all()
    ok('requested amount stored with the link', any(l.amount == 25000 for l in links))
