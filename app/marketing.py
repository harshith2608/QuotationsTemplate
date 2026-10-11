"""
Public marketing page for the product itself (not for a client's business).

Every client deployment runs this same code, so the page is OFF by default and
returns 404. Turn it on only on your own demo/marketing deployment:

    MARKETING_SITE=1
    MARKETING_PRODUCT_NAME=QuoteRoom
    MARKETING_WHATSAPP=919876543210          # country code + number, digits only
    META_PIXEL_ID=...                        # optional
    GOOGLE_ADS_ID=AW-...                     # optional
    GOOGLE_ADS_CONVERSION=AW-.../label       # optional, fired on WhatsApp clicks
    MARKETING_LEGAL_NAME, MARKETING_CONTACT_EMAIL, MARKETING_ADDRESS,
    MARKETING_JURISDICTION, MARKETING_LEGAL_UPDATED  # used on /privacy and /terms
    MARKETING_PRIVACY_URL / MARKETING_TERMS_URL      # optional: link to externally hosted policies instead
    LEADS_PASSWORD=...                       # opens /leads (free-trial requests); unset → /leads is 404

Ad tags (Meta Pixel, Google) load only after the visitor accepts the cookie notice.
"Start free trial" opens a short form (name, phone, business type); requests are stored
encrypted in the leads table, which survives the nightly demo reset.

With MARKETING_SITE=1, signed-out visitors to / also see the landing page.
"""
import csv
import hashlib
import hmac
import io
import os
import re
from datetime import datetime, timedelta
from urllib.parse import quote

from flask import Blueprint, Response, abort, current_app, jsonify, render_template, request, url_for

marketing_bp = Blueprint('marketing', __name__)


def _env(name, default=''):
    return (os.environ.get(name) or default).strip()


def marketing_enabled():
    return _env('MARKETING_SITE').lower() in ('1', 'true', 'yes', 'on')


def _display_number(digits):
    """919876543210 → +91 98765 43210 (falls back to +digits)."""
    if len(digits) == 12 and digits.startswith('91'):
        return f'+91 {digits[2:7]} {digits[7:]}'
    return f'+{digits}' if digits else ''


def _context():
    """Values shared by every marketing page, all from env vars."""
    wa_number = re.sub(r'\D', '', _env('MARKETING_WHATSAPP', '919999999999'))
    product = _env('MARKETING_PRODUCT_NAME', 'QuoteRoom')
    google_ads_id = _env('GOOGLE_ADS_ID')
    google_conv = _env('GOOGLE_ADS_CONVERSION')
    return dict(
        product=product,
        legal_name=_env('MARKETING_LEGAL_NAME', product),
        contact_email=_env('MARKETING_CONTACT_EMAIL'),
        business_address=_env('MARKETING_ADDRESS'),
        jurisdiction=_env('MARKETING_JURISDICTION'),
        legal_updated=_env('MARKETING_LEGAL_UPDATED', '11 October 2026'),
        wa_number=wa_number,
        wa_display=_display_number(wa_number),
        meta_pixel_id=re.sub(r'\D', '', _env('META_PIXEL_ID')),
        google_ads_id=google_ads_id if re.fullmatch(r'AW-\d+', google_ads_id) else '',
        google_ads_conversion=google_conv if re.fullmatch(r'AW-\d+/[\w-]+', google_conv) else '',
        privacy_url=_env('MARKETING_PRIVACY_URL') or url_for('marketing.privacy'),
        terms_url=_env('MARKETING_TERMS_URL') or url_for('marketing.terms'),
        home_url=url_for('main.index'),
        year=datetime.utcnow().year,
    )


def render_landing():
    """The landing page. Also served at / on the marketing deployment (see main.index)."""
    ctx = _context()
    ctx['home_url'] = ''   # on the landing page itself, nav links are plain #anchors
    return render_template('marketing/landing.html', **ctx)


@marketing_bp.route('/landingpage')
def landing():
    if not marketing_enabled():
        abort(404)
    return render_landing()


@marketing_bp.route('/privacy')
def privacy():
    if not marketing_enabled():
        abort(404)
    return render_template('marketing/privacy.html', **_context())


@marketing_bp.route('/terms')
def terms():
    if not marketing_enabled():
        abort(404)
    return render_template('marketing/terms.html', **_context())


# ── Free-trial requests ──────────────────────────────────────────────────────

BUSINESS_TYPES = {'interiors': 'Interior designer', 'furniture': 'Furniture works', 'other': 'Other'}
MAX_PER_IP_PER_HOUR = 5
KEEP_LEADS_DAYS = 365          # stated in the privacy policy


def normalise_phone(raw):
    """Indian mobile → '91XXXXXXXXXX', or None. Accepts spaces, dashes, +91, 91 or 0 prefixes."""
    digits = re.sub(r'\D', '', raw or '')
    if len(digits) == 12 and digits.startswith('91'):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith('0'):
        digits = digits[1:]
    return '91' + digits if re.fullmatch(r'[6-9]\d{9}', digits) else None


def _validate_lead(form):
    """(clean dict, {field: error})"""
    name = ' '.join((form.get('name') or '').split())[:80]
    phone = normalise_phone(form.get('phone'))
    btype = (form.get('business_type') or '').strip()
    other = ' '.join((form.get('business_other') or '').split())[:80]
    errors = {}
    if len(name) < 2:
        errors['name'] = 'Please enter your name.'
    if not phone:
        errors['phone'] = 'Please enter a 10-digit Indian mobile number.'
    if btype not in BUSINESS_TYPES:
        errors['business_type'] = 'Please choose your type of business.'
    elif btype == 'other' and len(other) < 2:
        errors['business_other'] = 'Please tell us what your business does.'
    return dict(name=name, phone=phone, business_type=btype,
                business_other=other if btype == 'other' else None), errors


def _business_label(lead):
    return lead.business_other if lead.business_type == 'other' and lead.business_other \
        else BUSINESS_TYPES.get(lead.business_type, lead.business_type)


def _whatsapp_followup_url(ctx, name, business):
    text = (f"Hi, I'm {name} ({business}). I just requested a free trial of {ctx['product']} "
            "on your website and would like to get started.")
    return f"https://wa.me/{ctx['wa_number']}?text={quote(text)}"


def _ip_hash():
    ip = (request.headers.get('X-Forwarded-For') or request.remote_addr or '').split(',')[0].strip()
    key = (current_app.config.get('SECRET_KEY') or '').encode()
    return hmac.new(key, ip.encode(), hashlib.sha256).hexdigest()


@marketing_bp.route('/free-trial')
def free_trial():
    """The trial form as its own page: works without JavaScript and can be linked from ads."""
    if not marketing_enabled():
        abort(404)
    form = {k: request.args.get(k, '')[:60] for k in ('utm_source', 'utm_campaign')}
    form['page'] = '/free-trial'
    return render_template('marketing/free_trial.html', standalone_trial=True, errors={}, form=form, **_context())


@marketing_bp.route('/trial-request', methods=['POST'])
def trial_request():
    """The "Start free trial" form. Answers JSON for the page's script, or a thank-you page without JS."""
    if not marketing_enabled():
        abort(404)
    from . import db
    from .models import Lead
    wants_json = request.accept_mimetypes.best == 'application/json'
    ctx = _context()
    data, errors = _validate_lead(request.form)

    if request.form.get('website'):                      # honeypot filled in → a bot; pretend it worked
        errors = {}
        bot = True
    else:
        bot = False
    if errors:
        if wants_json:
            return jsonify({'ok': False, 'errors': errors}), 400
        return render_template('marketing/free_trial.html', standalone_trial=True, errors=errors, form=request.form, **ctx), 400

    business = data['business_other'] if data['business_type'] == 'other' else BUSINESS_TYPES.get(data['business_type'], '')
    if not bot:
        ip_hash = _ip_hash()
        now = datetime.utcnow()
        recent = Lead.query.filter(Lead.ip_hash == ip_hash, Lead.created_at > now - timedelta(hours=1)).count()
        if recent >= MAX_PER_IP_PER_HOUR:
            msg = 'Too many requests. Please message us on WhatsApp instead.'
            if wants_json:
                return jsonify({'ok': False, 'errors': {'form': msg}}), 429
            return render_template('marketing/free_trial.html', standalone_trial=True, errors={'form': msg}, form=request.form, **ctx), 429
        # Same number again within a day: don't store a duplicate (phones are encrypted, so compare in Python)
        dup = any(l.phone == data['phone'] for l in Lead.query.filter(Lead.created_at > now - timedelta(days=1)))
        if not dup:
            source = ' · '.join(filter(None, [
                (request.form.get('utm_source') or '')[:60], (request.form.get('utm_campaign') or '')[:60],
                (request.form.get('page') or '')[:60]]))[:200]
            db.session.add(Lead(name=data['name'], phone=data['phone'], business_type=data['business_type'],
                                business_other=data['business_other'], source=source or None, ip_hash=ip_hash))
        Lead.query.filter(Lead.created_at < now - timedelta(days=KEEP_LEADS_DAYS)).delete()
        db.session.commit()

    wa_url = _whatsapp_followup_url(ctx, data['name'], business)
    if wants_json:
        return jsonify({'ok': True, 'name': data['name'], 'whatsapp_url': wa_url})
    return render_template('marketing/free_trial.html', standalone_trial=True, errors={}, name=data['name'], whatsapp_url=wa_url, **ctx)


def _leads_password():
    return _env('LEADS_PASSWORD')


def _leads_authorised():
    pw = _leads_password()
    auth = request.authorization
    return bool(pw) and auth is not None and hmac.compare_digest((auth.password or '').encode(), pw.encode())


def _leads_guard():
    if not marketing_enabled() or not _leads_password():
        abort(404)
    if not _leads_authorised():
        return Response('Sign in to see trial requests.', 401,
                        {'WWW-Authenticate': 'Basic realm="Trial requests", charset="UTF-8"'})
    return None


@marketing_bp.route('/leads')
def leads():
    """Trial requests, newest first. Protected by LEADS_PASSWORD (any username)."""
    denied = _leads_guard()
    if denied:
        return denied
    from .models import Lead
    rows = Lead.query.order_by(Lead.created_at.desc()).limit(500).all()
    ctx = _context()
    items = [dict(lead=l, business=_business_label(l), phone_display=_display_number(l.phone),
                  wa_url=f"https://wa.me/{l.phone}?text={quote(f'Hi {l.name}, thanks for your interest in ' + ctx['product'] + '!')}")
             for l in rows]
    resp = Response(render_template('marketing/leads.html', items=items, ist_offset=timedelta(hours=5, minutes=30), **ctx))
    resp.headers['Cache-Control'] = 'no-store'
    resp.headers['X-Robots-Tag'] = 'noindex'
    return resp


@marketing_bp.route('/leads.csv')
def leads_csv():
    denied = _leads_guard()
    if denied:
        return denied
    from .models import Lead
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(['Received (UTC)', 'Name', 'Phone', 'Business', 'Source'])
    for l in Lead.query.order_by(Lead.created_at.desc()).all():
        w.writerow([l.created_at.strftime('%Y-%m-%d %H:%M'), l.name, '+' + l.phone, _business_label(l), l.source or ''])
    return Response(out.getvalue(), mimetype='text/csv',
                    headers={'Content-Disposition': 'attachment; filename=trial-requests.csv', 'Cache-Control': 'no-store'})
