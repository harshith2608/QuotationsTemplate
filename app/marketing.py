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

With MARKETING_SITE=1, signed-out visitors to / also see the landing page.
"""
import os
import re
from datetime import datetime

from flask import Blueprint, abort, render_template, url_for

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
        legal_updated=_env('MARKETING_LEGAL_UPDATED', '4 October 2026'),
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
    """The landing page. Also served at / for signed-out visitors (see main.index)."""
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
