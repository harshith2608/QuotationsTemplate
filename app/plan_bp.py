"""Choose a plan / Renew inside the app (shared trials app, admins): Razorpay Checkout with the platform's account.
See app/subscription.py."""
from flask import Blueprint, abort, jsonify, render_template, request, send_file, url_for
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
    status = load_status()
    return render_template('plan/plan.html', title='Your plan', status=status, prices=subscription.prices(),
                           payments=subscription.history(tenancy.current_slug()),
                           key_id=subscription._env('PLATFORM_RAZORPAY_KEY_ID'))


@plan_bp.route('/plan/order', methods=['POST'])
@login_required
@admin_required
def order():
    _guard()
    from .branding import get_brand
    plan = (request.get_json(silent=True) or {}).get('plan') or request.form.get('plan')
    brand = get_brand()
    try:
        row = subscription.create_order(tenancy.current_slug(), plan, brand['name'], current_user.username,
                                        brand.get('email') or '')
    except subscription.PaymentError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400
    return jsonify({'ok': True, 'order_id': row['order_id'], 'amount': row['amount_paise'], 'currency': 'INR',
                    'key_id': subscription._env('PLATFORM_RAZORPAY_KEY_ID'),
                    'description': f'QuoteRoom {"6-month" if plan == "6m" else "12-month"} plan',
                    'prefill': {'name': brand['name'], 'email': brand.get('email') or '',
                                'contact': ''.join(ch for ch in (brand.get('phone') or '') if ch.isdigit())[-12:]}})


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
    return render_template('plan/thanks.html', title='Thank you', row=row, status=load_status(),
                           moving=bool(tenancy.current_schema()))


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
