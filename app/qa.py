"""The QA copy (docs/OPERATIONS.md 3i): QA_MODE=1 on the QA projects, built from the dev branch on their own database.

Every page is marked QA and kept out of search engines, and nobody gets past a "QA key" page without QA_ACCESS_KEY
(entered once per browser: a cookie for QA_COOKIE_DOMAIN, e.g. qa.quote-room.co.in, covers the console, every trial
and the website). Without QA_ACCESS_KEY the QA copy stays closed. The live apps never set QA_MODE.
"""
import hashlib
import hmac
import os
import time
from html import escape

from flask import redirect, request

PATH = '/qa-access'
COOKIE = 'qa_access'
DAYS = 90


def enabled():
    return os.environ.get('QA_MODE', '').strip().lower() in ('1', 'true', 'yes', 'on')


def _key():
    return (os.environ.get('QA_ACCESS_KEY') or '').strip()


def _token(key):
    return hmac.new(key.encode(), b'quoteroom-qa-access-v1', hashlib.sha256).hexdigest()


def _cookie_domain(host):
    """QA_COOKIE_DOMAIN (else TENANT_BASE_DOMAIN) when this address is in it, so one key opens every QA address."""
    domain = (os.environ.get('QA_COOKIE_DOMAIN') or os.environ.get('TENANT_BASE_DOMAIN') or '').strip().lower().strip('.')
    return domain if domain and (host == domain or host.endswith('.' + domain)) else None


def _page(message='', status=401):
    note = f'<p class="err">{escape(message)}</p>' if message else ''
    nxt = request.args.get('next') or (request.full_path.rstrip('?') if request.path != PATH else '/')
    html = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><meta name="robots" content="noindex, nofollow">
<title>QA</title><style>
body{{font-family:system-ui,sans-serif;background:#f4f5f7;margin:0;display:flex;min-height:100vh;align-items:center;justify-content:center}}
form{{background:#fff;padding:28px;border-radius:10px;box-shadow:0 2px 12px rgba(0,0,0,.08);width:min(340px,90vw)}}
h1{{font-size:18px;margin:0 0 6px}} p{{color:#555;font-size:14px;margin:0 0 16px}} .err{{color:#c62828}}
input{{width:100%;box-sizing:border-box;padding:10px;font-size:16px;border:1px solid #ccc;border-radius:6px;margin-bottom:12px}}
button{{width:100%;padding:10px;font-size:16px;border:0;border-radius:6px;background:#e65100;color:#fff;font-weight:600}}
</style></head><body><form method="post" action="{PATH}?next={escape(nxt, quote=True)}">
<h1>QA copy</h1><p>This is a test copy, not the live site. Enter the QA key to continue.</p>{note}
<input type="password" name="key" autocomplete="current-password" placeholder="QA key" required autofocus>
<button type="submit">Continue</button></form></body></html>"""
    return html, status, {'X-Robots-Tag': 'noindex, nofollow', 'Cache-Control': 'no-store'}


def gate():
    """before_request, first of all: the QA key page until this browser has entered QA_ACCESS_KEY."""
    key = _key()
    if not key:
        return _page('This QA copy is closed: QA_ACCESS_KEY is not set.', 503)
    expected = _token(key)
    if hmac.compare_digest(request.cookies.get(COOKIE, ''), expected):
        if request.path == PATH:
            return redirect(_safe_next())
        return None
    if request.path != PATH or request.method != 'POST':
        return _page()
    if not hmac.compare_digest((request.form.get('key') or '').strip().encode(), key.encode()):
        time.sleep(1)                       # slows down guessing
        return _page('That key is not right.')
    response = redirect(_safe_next())
    host = (request.host or '').split(':')[0].lower()
    response.set_cookie(COOKIE, expected, max_age=DAYS * 24 * 3600, domain=_cookie_domain(host), secure=request.is_secure,
                        httponly=True, samesite='Lax')
    return response


def _safe_next():
    nxt = request.args.get('next') or '/'
    return nxt if nxt.startswith('/') and not nxt.startswith('//') and not nxt.startswith(PATH) else '/'


def init(app):
    """QA_MODE: the key page before everything else, the QA label on every page, no search engines."""
    if not enabled():
        return
    app.before_request_funcs.setdefault(None, []).insert(0, gate)

    @app.after_request
    def qa_noindex(response):
        response.headers['X-Robots-Tag'] = 'noindex, nofollow'
        return response

    @app.context_processor
    def qa_flag():
        return {'qa_mode': True}
