"""Choose a plan / Renew inside the app (shared trials app, admins): Razorpay Checkout with the platform's account.
See app/subscription.py."""
from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, send_file, url_for
from flask_login import current_user, login_required

from . import subscription, tenancy
from .decorators import admin_required
from .plan import load_status

plan_bp = Blueprint('plan', __name__)


def _guard():
    if not subscription.enabled() or not tenancy.current_slug():
        abort(404)


@plan_bp.route('/plan')
@login_required
@admin_required
def plan_page():
    _guard()
    from . import ai_tools, plan as plan_mod
    status = load_status()
    from . import pricing
    data = pricing.load()
    return render_template('plan/plan.html', title='Your plan', status=status, prices=pricing.prices(data),
                           offered=pricing.offered(data), pricing=pricing, pricing_data=data,
                           ai_pool=ai_tools.pool(), ai_allowance={k: ai_tools.allowance(k) for k in ai_tools.ALLOWANCE},
                           addon=plan_mod.ADDON, addon_uses=plan_mod.ADDON_USES, ai_on=any(ai_tools.available(f) for f in ai_tools.FEATURES),
                           payments=subscription.history(tenancy.current_slug()),
                           autopay=subscription.current_subscription(tenancy.current_slug()),
                           key_id=subscription._env('PLATFORM_RAZORPAY_KEY_ID'))


@plan_bp.route('/plan/order', methods=['POST'])
@login_required
@admin_required
def order():
    _guard()
    from . import ai_tools, plan as plan_mod
    from .branding import get_brand
    plan = (request.get_json(silent=True) or {}).get('plan') or request.form.get('plan')
    from . import pricing
    if plan != plan_mod.ADDON and plan not in pricing.offered():   # only the plans shown (the console's Pricing)
        return jsonify({'ok': False, 'error': 'Choose one of the plans shown.'}), 400
    if plan == plan_mod.ADDON and not ai_tools.pool()['can_buy']:
        return jsonify({'ok': False, 'error': 'More AI uses can be bought on a paid plan: choose a plan first.'}), 400
    brand = get_brand()
    try:
        row = subscription.create_order(tenancy.current_slug(), plan, brand['name'], current_user.username,
                                        brand.get('email') or '', payer_name=current_user.display_name)
    except subscription.PaymentError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400
    return jsonify({'ok': True, 'order_id': row['order_id'], 'amount': row['amount_paise'], 'currency': 'INR',
                    'key_id': subscription._env('PLATFORM_RAZORPAY_KEY_ID'),
                    'description': f'QuoteRoom: {plan_mod.short(plan)}',
                    'prefill': {'name': brand['name'], 'email': brand.get('email') or '',
                                'contact': _contact(brand)}})


def _contact(brand):
    """The mobile number Razorpay Checkout fills in (it asks for one on every payment in India): the first Indian
    mobile in the company phone (Settings → Company), which may hold two numbers or a landline too; else the one they
    gave when they signed up on the website; '' if none."""
    import re
    from .marketing import normalise_phone
    from .models import AppSetting
    from .ops import SIGNUP_MOBILE_KEY
    for part in re.split(r'[,/;|]|\s{2,}|\bor\b', brand.get('phone') or '') + [AppSetting.get(SIGNUP_MOBILE_KEY, '') or '']:
        found = normalise_phone(part)
        if found:
            return '+' + found
    return ''


@plan_bp.route('/plan/subscribe', methods=['POST'])
@login_required
@admin_required
def subscribe():
    """Start the monthly plan: a Razorpay subscription, approved once (UPI Autopay or a card) in Checkout."""
    _guard()
    from . import plan as plan_mod
    from .branding import get_brand
    plan = (request.get_json(silent=True) or {}).get('plan') or request.form.get('plan')
    slug = tenancy.current_slug()
    from . import pricing
    if plan not in pricing.offered():
        return jsonify({'ok': False, 'error': 'Choose one of the plans shown.'}), 400
    if subscription.current_subscription(slug):
        return jsonify({'ok': False, 'error': 'Your autopay is already on.'}), 400
    brand = get_brand()
    try:
        sub = subscription.create_subscription(slug, plan, brand['name'], current_user.username, brand.get('email') or '',
                                               brand.get('phone') or '', payer_name=current_user.display_name)
    except subscription.PaymentError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400
    return jsonify({'ok': True, 'subscription_id': sub['sub_id'], 'key_id': subscription._env('PLATFORM_RAZORPAY_KEY_ID'),
                    'description': f'QuoteRoom: {plan_mod.PLANS[plan]}, ₹{subscription.prices()[plan]} a month',
                    'prefill': {'name': brand['name'], 'email': brand.get('email') or '',
                                'contact': _contact(brand)}})


@plan_bp.route('/plan/subscribed', methods=['POST'])
@login_required
@admin_required
def subscribed():
    """Checkout's success for the monthly plan: the mandate is approved and the first month paid. Recorded once
    (the webhook may get there first)."""
    _guard()
    data = request.get_json(silent=True) or request.form
    payment_id, sub_id = data.get('razorpay_payment_id', ''), data.get('razorpay_subscription_id', '')
    if not subscription.verify_subscription_checkout(payment_id, sub_id, data.get('razorpay_signature', '')):
        return jsonify({'ok': False, 'error': 'The payment could not be verified. If money was taken, it will be '
                                              'recorded automatically within a few minutes.'}), 400
    sub = subscription.get_subscription(sub_id)
    if not sub or sub['slug'] != tenancy.current_slug():
        abort(404)
    amount = subscription.checkout_charge(sub, payment_id)
    if amount is None:                        # only the mandate check so far: the month comes with the charge
        subscription.set_autopay(sub['slug'], True)
        flash('Autopay is set up. Your first month is charged in a few minutes, and your plan is updated as soon as '
              'it goes through (you get a receipt by email).', 'success')
        return jsonify({'ok': True, 'redirect': url_for('plan.plan_page')})
    row, _ = subscription.record_charge(sub, payment_id, amount, 'app')
    return jsonify({'ok': True, 'redirect': url_for('plan.thanks', payment_id=row['id'])})


@plan_bp.route('/plan/autopay/cancel', methods=['POST'])
@login_required
@admin_required
def autopay_cancel():
    """Stop the monthly autopay: nothing more is charged; the month already paid runs to its end date."""
    _guard()
    sub = subscription.current_subscription(tenancy.current_slug())
    if sub:
        try:
            subscription.cancel_subscription(sub)
        except subscription.PaymentError as exc:
            flash(f'Could not stop the autopay: {exc} Please try again, or message us.', 'danger')
            return redirect(url_for('plan.plan_page'))
        status = load_status()
        flash(f'Autopay stopped. Nothing more will be charged; your plan runs until {status.ends_on:%d %b %Y}.', 'success')
    return redirect(url_for('plan.plan_page'))


@plan_bp.route('/plan/paid', methods=['POST'])
@login_required
@admin_required
def paid():
    """Razorpay Checkout's success handler: check the signature, record the payment once, add the plan."""
    _guard()
    data = request.get_json(silent=True) or request.form
    order_id, payment_id = data.get('razorpay_order_id', ''), data.get('razorpay_payment_id', '')
    if not subscription.verify_checkout(order_id, payment_id, data.get('razorpay_signature', '')):
        return jsonify({'ok': False, 'error': 'The payment could not be verified. If money was taken, it will be '
                                              'recorded automatically within a few minutes.'}), 400
    row = subscription.get_by_order(order_id)
    if not row or row['slug'] != tenancy.current_slug():
        abort(404)
    row, newly = subscription.mark_paid(order_id, payment_id, 'app')
    if newly:
        subscription.apply_plan(row)
        subscription.notify_paid(subscription.get(row['id']))
    return jsonify({'ok': True, 'redirect': url_for('plan.thanks', payment_id=row['id'])})


@plan_bp.route('/plan/thanks/<int:payment_id>')
@login_required
@admin_required
def thanks(payment_id):
    _guard()
    row = subscription.get(payment_id)
    if not row or row['slug'] != tenancy.current_slug() or row['status'] != 'paid':
        abort(404)
    from . import ai_tools, plan as plan_mod
    addon = row['plan'] == plan_mod.ADDON
    return render_template('plan/thanks.html', title='Thank you', row=row, status=load_status(),
                           moving=bool(tenancy.current_schema()), addon=addon,
                           ai_left=ai_tools.pool()['left'] if addon else None)


@plan_bp.route('/plan/receipt/<int:payment_id>')
@login_required
@admin_required
def receipt(payment_id):
    _guard()
    row = subscription.get(payment_id)
    if not row or row['slug'] != tenancy.current_slug() or row['status'] != 'paid':
        abort(404)
    return send_file(subscription.receipt_pdf(row), mimetype='application/pdf',
                     download_name=f'QuoteRoom-receipt-{row["receipt_no"]}.pdf', as_attachment=False)
