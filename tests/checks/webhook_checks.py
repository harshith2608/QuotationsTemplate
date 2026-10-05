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
    ok('admin notification created', Notification.query.filter(Notification.message.contains('25,000.00')).count() == 1)
r = post(payload(3, 'pay_REAL1', 2500000), secret='whsec_test')
with app.app_context():
    ok('duplicate delivery ignored', r.get_json().get('status') == 'duplicate' and Payment.query.filter_by(razorpay_payment_id='pay_REAL1').count() == 1)
body = json.dumps({'event': 'payment.captured', 'payload': {}}).encode()
ok('other events acknowledged and ignored', post(body, secret='whsec_test').get_json().get('status') == 'ignored')
