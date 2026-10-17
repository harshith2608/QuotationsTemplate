"""Deliver Razorpay's "payment_link.paid" webhook to a LOCAL app, for a real Razorpay TEST payment.

Razorpay can't reach an app running on your own computer, so when recording tutorial 11 this script does what Razorpay
would: it reads the paid payment link from Razorpay's API (with the app's saved test keys), builds the same
payment_link.paid event and signs it with the app's saved webhook secret. Run it with the app's environment
(DATABASE_URL, DATA_ENCRYPTION_KEY, FLASK_APP):

    python tools/tutorials/replay_razorpay_webhook.py http://localhost:5093 <payment link short URL or plink_ id>
"""
import base64
import hashlib
import hmac
import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))

from app import create_app  # noqa: E402
from app.models import AppSetting, PaymentLink  # noqa: E402

BASE, LINK = sys.argv[1], sys.argv[2].strip()


def razorpay(path, key, secret):
    auth = base64.b64encode(f'{key}:{secret}'.encode()).decode()
    req = urllib.request.Request('https://api.razorpay.com/v1' + path, headers={'Authorization': f'Basic {auth}'})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def main():
    with create_app().app_context():
        key, secret = AppSetting.get('razorpay_key_id', ''), AppSetting.get('razorpay_key_secret', '')
        hook_secret = AppSetting.get('webhook_secret', '').strip()
        if not key.startswith('rzp_test_'):
            sys.exit('Only for Razorpay TEST keys.')
        link_ids = [pl.razorpay_link_id for pl in PaymentLink.query.order_by(PaymentLink.id.desc()).all()]
    plink = None
    for lid in ([LINK] if LINK.startswith('plink_') else link_ids):
        data = razorpay(f'/payment_links/{lid}', key, secret)
        if LINK.startswith('plink_') or data.get('short_url') == LINK:
            plink = data
            break
    if not plink:
        sys.exit('Payment link not found.')
    paid = [p for p in plink.get('payments') or [] if p.get('status') == 'captured']
    if not paid:
        sys.exit(f"No captured payment on {plink['id']} yet (status: {plink.get('status')}).")
    payment = razorpay(f"/payments/{paid[-1]['payment_id']}", key, secret)
    body = json.dumps({'entity': 'event', 'event': 'payment_link.paid', 'contains': ['payment_link', 'payment'],
                       'payload': {'payment_link': {'entity': plink}, 'payment': {'entity': payment}}}).encode()
    sig = hmac.new(hook_secret.encode(), body, hashlib.sha256).hexdigest()
    req = urllib.request.Request(BASE + '/webhook/razorpay', data=body, method='POST',
                                 headers={'Content-Type': 'application/json', 'X-Razorpay-Signature': sig})
    with urllib.request.urlopen(req, timeout=15) as resp:
        print(resp.status, resp.read().decode())


if __name__ == '__main__':
    main()
