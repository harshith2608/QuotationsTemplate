"""Emails from QuoteRoom itself (e.g. hello@quote-room.co.in): the link to set up a trial, "you're on your paid plan"
with the receipt, plan reminders, and a note to the operator about each payment. Not the businesses' own emails to
their customers (those use each business's Admin → Settings → Email).

    PLATFORM_SMTP_HOST=smtp.titan.email   PLATFORM_SMTP_PORT=465 (SSL; 587 = STARTTLS)
    PLATFORM_SMTP_USER=hello@quote-room.co.in   PLATFORM_SMTP_PASSWORD=<the mailbox password>
    PLATFORM_SMTP_FROM_NAME=QuoteRoom     (optional)
    OPERATOR_EMAIL=...                    (optional: who gets "payment received" notes; default the sending address)
    MAIL_OUTBOX_DIR=/some/folder          (tests / local: write each email there as a .eml file instead of sending)
Needed on the website (set-up links), the trials app (payment emails) and the console (webhook payments, reminders).
"""
import os
import smtplib
import time
from email.message import EmailMessage
from email.utils import formataddr, make_msgid


def _env(name, default=''):
    return (os.environ.get(name) or default).strip()


def enabled():
    return bool(_env('MAIL_OUTBOX_DIR')) or bool(_env('PLATFORM_SMTP_HOST') and _env('PLATFORM_SMTP_USER')
                                                  and _env('PLATFORM_SMTP_PASSWORD'))


def sender():
    return _env('PLATFORM_SMTP_USER') or 'hello@quote-room.co.in'


def operator():
    return _env('OPERATOR_EMAIL') or sender()


def send(to, subject, text, attachments=(), reply_to=None):
    """Send a plain-text email. attachments: [(filename, bytes, 'application/pdf')]. Returns True if sent.
    Never raises: a failed email must not break a payment or a sign-up (the reason is logged)."""
    if not enabled() or not to or '@' not in to:
        return False
    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From'] = formataddr((_env('PLATFORM_SMTP_FROM_NAME', 'QuoteRoom'), sender()))
    msg['To'] = to
    msg['Message-ID'] = make_msgid(domain=sender().split('@')[-1])
    if reply_to:
        msg['Reply-To'] = reply_to
    msg.set_content(text)
    for filename, data, mime in attachments:
        main, sub = mime.split('/', 1)
        msg.add_attachment(data, maintype=main, subtype=sub, filename=filename)
    try:
        outbox = _env('MAIL_OUTBOX_DIR')
        if outbox:
            os.makedirs(outbox, exist_ok=True)
            with open(os.path.join(outbox, f'{time.time():.6f}.eml'), 'wb') as f:
                f.write(bytes(msg))
            return True
        port = int(_env('PLATFORM_SMTP_PORT', '465'))
        host = _env('PLATFORM_SMTP_HOST')
        if port == 465:
            with smtplib.SMTP_SSL(host, port, timeout=15) as s:
                s.login(_env('PLATFORM_SMTP_USER'), _env('PLATFORM_SMTP_PASSWORD'))
                s.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=15) as s:
                s.ehlo()
                s.starttls()
                s.login(_env('PLATFORM_SMTP_USER'), _env('PLATFORM_SMTP_PASSWORD'))
                s.send_message(msg)
        return True
    except Exception as exc:
        try:
            from flask import current_app
            current_app.logger.warning('Platform email to %s failed: %s', to, exc)
        except Exception:
            pass
        return False


def mask(email):
    """'meera@shahstudio.com' → 'me***@shahstudio.com' (shown on the website after sending)."""
    name, _, domain = (email or '').partition('@')
    return f'{name[:2]}***@{domain}' if domain else ''
