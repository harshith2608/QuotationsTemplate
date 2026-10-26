"""Self-serve trials: a business that asks for a free trial on the website sets up its own app straight away.

The website (MARKETING_SITE) stores the request as before. For interior designers and furniture works, its thank-you
step offers "Set up your app now": a link to the console's public /start page carrying only a signed, single-use
token for that request (no name, phone or email in the address). There they choose their web address, login and
password; the console renames a ready-made trial (ops.claim_trial) and they sign in. "Others" still wait for the
operator. Every self-started trial appears in the console linked to its request, with the WhatsApp follow-ups.

    Website:  AUTO_TRIALS=1, SIGNUP_URL=https://ops.quote-room.co.in, SIGNUP_SECRET=<same as the console>
    Console:  SIGNUP_SECRET, TURNSTILE_SITE_KEY + TURNSTILE_SECRET_KEY (optional: Cloudflare's free bot check),
              SPARE_TRIALS=3 (ready-made trials kept, topped up by the daily tick and the dashboard)
"""
import hashlib
import hmac
import json
import os
import time
import urllib.parse
import urllib.request

ELIGIBLE = {'interiors', 'furniture'}
TOKEN_HOURS = 72
MAX_PER_IP_PER_HOUR = 3


def _env(name, default=''):
    return (os.environ.get(name) or default).strip()


def _sign(text):
    return hmac.new(_env('SIGNUP_SECRET').encode(), text.encode(), hashlib.sha256).hexdigest()[:32]


def make_token(lead_id, now=None):
    exp = int((now or time.time()) + TOKEN_HOURS * 3600)
    body = f'{int(lead_id)}.{exp}'
    return f'{body}.{_sign(body)}'


def read_token(token, now=None):
    """The request's id, or None if the token is altered, expired or SIGNUP_SECRET isn't set."""
    if not _env('SIGNUP_SECRET'):
        return None
    try:
        lead_id, exp, sig = (token or '').split('.')
        if not hmac.compare_digest(sig, _sign(f'{lead_id}.{exp}')) or int(exp) < (now or time.time()):
            return None
        return int(lead_id)
    except ValueError:
        return None


def website_offers(business_type):
    """True if the website should offer "Set up your app now" for this request."""
    return (_env('AUTO_TRIALS') in ('1', 'true', 'yes', 'on') and bool(_env('SIGNUP_URL')) and bool(_env('SIGNUP_SECRET'))
            and business_type in ELIGIBLE)


def setup_url(lead_id, base=None):
    """base: the console's address (the website uses SIGNUP_URL; the console its own)."""
    return f'{(base or _env("SIGNUP_URL")).rstrip("/")}/start?t={urllib.parse.quote(make_token(lead_id))}'


def turnstile_site_key():
    return _env('TURNSTILE_SITE_KEY') if _env('TURNSTILE_SECRET_KEY') else ''


def turnstile_ok(response, ip=''):
    """Cloudflare Turnstile's check (only when its keys are set)."""
    secret = _env('TURNSTILE_SECRET_KEY')
    if not secret:
        return True
    data = urllib.parse.urlencode({'secret': secret, 'response': response or '', 'remoteip': ip}).encode()
    try:
        with urllib.request.urlopen('https://challenges.cloudflare.com/turnstile/v0/siteverify', data=data, timeout=8) as r:
            return bool(json.loads(r.read()).get('success'))
    except Exception:
        return False


def email_setup_link(email, name, company, url, lead_id=None):
    """Email the set-up link (the website sends it instead of showing it, once email is set up). True if sent.
    lead_id: the request, so the console can see the email opened (app/emails.py)."""
    from . import emails, mailer
    first = (name or '').split(' ')[0] or 'there'
    body = f"""Hi {first},

Thanks for asking for a QuoteRoom free trial{f' for {company}' if company else ''}.

Set up your app here (choose a password; it takes a minute):
{url}

The link works for {TOKEN_HOURS // 24} days. Your free 7-day trial starts when you set it up.

Any questions? Just reply to this email or message us on WhatsApp.

QuoteRoom
"""
    html = emails.setup_html(body, lead_id) if lead_id else None
    return mailer.send(email, 'Set up your QuoteRoom app', body, bcc=mailer.sender(), html=html)
