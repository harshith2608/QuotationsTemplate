"""Forgot password (admins only): a reset link to the business's email (Admin → Settings → company email), valid
for an hour and once (it carries part of the current password hash: a new password ends it). Staff ask their admin,
who sets their password in Admin → Users."""
import json
import time

from flask import current_app, url_for
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from . import db

SALT = 'password-reset'
MAX_AGE = 3600                     # seconds the link works
GAP = 120                          # at most one email per admin every 2 minutes
SENT_KEY = 'password_reset_sent'   # app_settings: {user_id: last sent (epoch)}


def mask(email):
    """'pola.harshith2000@gmail.com' → 'po***************00@gmail.com': the first and last two letters."""
    name, _, domain = (email or '').partition('@')
    if not domain:
        return ''
    if len(name) <= 4:
        return f'{name[:1]}{"*" * max(len(name) - 1, 1)}@{domain}'
    return f'{name[:2]}{"*" * (len(name) - 4)}{name[-2:]}@{domain}'


def business_email():
    from .models import AppSetting
    email = (AppSetting.get('company_email') or '').strip()
    return email if '@' in email else ''


def _serializer():
    return URLSafeTimedSerializer(current_app.config['SECRET_KEY'], salt=SALT)


def _slug():
    from . import tenancy
    return tenancy.current_slug() or ''


def make_token(user):
    return _serializer().dumps({'u': user.id, 's': _slug(), 'h': user.password_hash[-16:]})


def read_token(token):
    """The admin this link is for, or None (altered, expired, another business, or already used)."""
    from .models import User
    try:
        data = _serializer().loads(token or '', max_age=MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None
    user = db.session.get(User, data.get('u')) if isinstance(data, dict) else None
    if not user or not user.is_admin or data.get('s') != _slug() or user.password_hash[-16:] != data.get('h'):
        return None
    return user


def _recently_sent(user):
    from .models import AppSetting
    try:
        sent = json.loads(AppSetting.get(SENT_KEY) or '{}')
    except ValueError:
        sent = {}
    return time.time() - float(sent.get(str(user.id), 0)) < GAP, sent


def send_link(user):
    """Email the reset link to the business's email. Returns 'sent', 'recent' (one went out a moment ago: check the
    inbox), 'no_email', 'no_mail' (email isn't set up on this app) or 'send_failed' (the mail server refused it)."""
    from . import mailer
    from .branding import get_brand
    from .models import AppSetting
    email = business_email()
    if not email:
        return 'no_email'
    if not mailer.enabled():
        current_app.logger.warning('Password reset: email is not set up on this app (PLATFORM_SMTP_*)')
        return 'no_mail'
    recent, sent = _recently_sent(user)
    if recent:
        return 'recent'
    link = url_for('auth.reset_password', token=make_token(user), _external=True)
    name = get_brand().get('name') or 'your business'
    body = (f'Hello,\n\nSomeone (hopefully you) asked to reset the password for "{user.username}", an admin login of '
            f'{name} on QuoteRoom.\n\nChoose a new password here (the link works for 1 hour, once):\n{link}\n\n'
            f'If you didn\'t ask for this, ignore this email: your password stays as it is.\n\nQuoteRoom\n')
    if not mailer.send(email, f'Reset your {name} password', body):
        return 'send_failed'                       # (the reason is in the log: app/mailer.py)
    sent[str(user.id)] = time.time()
    AppSetting.set(SENT_KEY, json.dumps(sent))
    db.session.commit()
    return 'sent'
