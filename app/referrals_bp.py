"""Admin → Refer & earn (shared app, admins): apply to be a partner, then the code, link, referrals and earnings.
See app/referrals.py."""
from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from . import referrals, tenancy
from .decorators import admin_required

referrals_bp = Blueprint('referrals', __name__)


def _guard():
    if not referrals.available() or not tenancy.current_slug():
        abort(404)


def _prefill():
    """The application form from what the app already has (the business can change it)."""
    from .branding import get_brand
    from .models import AppSetting
    from .ops import SIGNUP_MOBILE_KEY
    brand = get_brand()
    s = AppSetting.get_many(['company_mobile', 'company_email', 'company_address', SIGNUP_MOBILE_KEY])
    address = (s.get('company_address') or '').replace('\n', ', ')
    city = address.split(',')[-1].strip() if address else ''
    city = ''.join(ch for ch in city if not ch.isdigit()).strip(' -') or city
    return {'name': getattr(current_user, 'display_name', '') or '', 'business': brand.get('name') or '',
            'phone': s.get('company_mobile') or s.get(SIGNUP_MOBILE_KEY) or '', 'email': s.get('company_email') or '',
            'city': city[:60]}


@referrals_bp.route('/refer', methods=['GET', 'POST'])
@login_required
@admin_required
def refer():
    _guard()
    slug = tenancy.current_slug()
    rules = referrals.settings()
    partner = referrals.get(slug)
    can_apply, why_not = referrals.eligibility(slug)
    form, errors = None, {}
    if request.method == 'POST' and request.form.get('action') == 'apply':
        if not can_apply:
            flash(why_not, 'warning')
            return redirect(url_for('referrals.refer'))
        values, errors = referrals.clean_application(request.form)
        if not errors:
            try:
                referrals.apply(slug, values)
            except referrals.ReferralError as exc:
                flash(str(exc), 'danger')
                return redirect(url_for('referrals.refer'))
            except Exception:
                flash('Your application couldn\'t be saved right now. Please try again in a while.', 'danger')
                return redirect(url_for('referrals.refer'))
            try:
                from . import notify
                notify.send(f'🤝 Refer & earn application: {values["business"]}',
                            [' · '.join(filter(None, (values['name'], values['city']))), slug],
                            phone=values['phone'], console_path='/partners')
            except Exception:
                pass
            flash('Thank you! We\'ll review your application and let you know. You can start referring once '
                  'it\'s approved.', 'success')
            return redirect(url_for('referrals.refer'))
        form = request.form
    if request.method == 'POST' and request.form.get('action') == 'payout' and partner and partner['status'] == 'approved':
        values, errors = referrals.clean_application(dict(request.form, name=partner['name'], phone=partner['phone'],
                                                          city=partner['city'], business=partner['business'], agree='1'))
        errors = {k: v for k, v in errors.items() if k in ('upi', 'account_number', 'ifsc', 'pan')}
        if not errors:
            referrals.set_payout_details(slug, values)
            flash('Payout details saved.', 'success')
            return redirect(url_for('referrals.refer') + '#payout')
        form = request.form
    if partner and partner['status'] == 'approved':
        try:
            referrals.sync()
        except Exception:
            pass
        return render_template('referrals/refer.html', title='Refer & earn', rules=rules, product_name=referrals.product(), refer_site=referrals.site_url(), partner=partner,
                               pct=referrals.pct_of(partner), link=referrals.signup_link(partner['code']),
                               refs=referrals.referrals(slug), earnings=referrals.earnings(slug),
                               totals=referrals.totals(slug), payouts=referrals.payouts(slug),
                               payout=referrals.payout_details(partner), active=referrals.plan_active(slug),
                               form=form, errors=errors, EARNING=referrals.EARNING)
    show_form = can_apply and (not partner or partner['status'] in ('rejected', 'stopped') or form is not None)
    prefill = dict(_prefill(), **({k: partner[k] for k in ('name', 'phone', 'city', 'business', 'email')}
                                  if partner else {}))
    if partner:
        prefill.update({k: v for k, v in referrals.payout_details(partner).items() if v})
    return render_template('referrals/refer.html', title='Refer & earn', rules=rules, product_name=referrals.product(), refer_site=referrals.site_url(), partner=partner,
                           can_apply=can_apply, why_not=why_not, show_form=show_form,
                           form=form or prefill, errors=errors, STATUSES=referrals.STATUSES)
