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
    MARKETING_PRIVACY_URL / MARKETING_TERMS_URL   # optional footer links
"""
import os
import re
from datetime import datetime

from flask import Blueprint, abort, render_template

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


@marketing_bp.route('/landingpage')
def landing():
    if not marketing_enabled():
        abort(404)
    wa_number = re.sub(r'\D', '', _env('MARKETING_WHATSAPP', '919999999999'))
    return render_template(
        'marketing/landing.html',
        product=_env('MARKETING_PRODUCT_NAME', 'QuoteRoom'),
        wa_number=wa_number,
        wa_display=_display_number(wa_number),
        meta_pixel_id=re.sub(r'\D', '', _env('META_PIXEL_ID')),
        google_ads_id=_env('GOOGLE_ADS_ID') if re.fullmatch(r'AW-\d+', _env('GOOGLE_ADS_ID')) else '',
        google_ads_conversion=_env('GOOGLE_ADS_CONVERSION') if re.fullmatch(r'AW-\d+/[\w-]+', _env('GOOGLE_ADS_CONVERSION')) else '',
        privacy_url=_env('MARKETING_PRIVACY_URL'),
        terms_url=_env('MARKETING_TERMS_URL'),
        year=datetime.utcnow().year,
    )
