"""
Public demo mode — for the product's own demo deployment only.

    DEMO_MODE=1          turn it on
    DEMO_USER=demo-admin the account visitors are signed into (default: demo-admin)
    DEMO_PASSWORD=...    set to something long and random; visitors never need it
    CRON_SECRET=...      lets the nightly Vercel cron reset the demo data

In demo mode:
  * /demo signs a visitor straight into the demo account (no password shown), and
    /login redirects there, so visitors never see a password form; the sign-in is
    remembered, so closing the browser doesn't sign them out
  * anything that could vandalise the demo or produce a convincing fake is
    blocked: all admin saves (settings, branding, rates, users), deleting,
    payment links and access changes
  * every PDF carries a "DEMO" watermark and a notice at the top saying it's a sample from the demo, made out by
    the fictional Demo Interiors: the amounts are the real calculation, so a visitor sees a quotation that adds up
  * a guide at the top walks a visitor through it: see a finished sample quotation and its PDF, make their own
    (started from the sample's first room: change a size, save), get their PDF, then start a free trial
  * /demo/reset (called by the Vercel cron with CRON_SECRET) wipes and
    reloads the demo data
"""
import hashlib
import hmac
import os

from flask import Blueprint, abort, current_app, flash, jsonify, redirect, request, url_for
from flask_login import login_user

demo_bp = Blueprint('demo', __name__)

# Endpoints that change data and are off-limits to demo visitors
BLOCKED_ENDPOINTS = {
    'admin.settings', 'admin.payment_settings', 'admin.rates',
    'admin.costs',
    'billing.quotation_email', 'billing.invoice_email',
    'admin.create_user', 'admin.delete_user', 'admin.rename_user', 'admin.change_user_password',
    'admin.clear_notifications',
    'admin.test_razorpay', 'admin.test_email',
    'projects.delete_project', 'projects.delete_payment',
    'projects.generate_payment_link', 'projects.set_project_access',
    'projects.razorpay_webhook',
}

WATERMARK_TEXT = 'DEMO — NOT A VALID QUOTATION'
NOTICE_TITLE = 'DEMO QUOTATION — NOT VALID'
NOTICE_TEXT = ('A sample made in the QuoteRoom demo by Demo Interiors, a fictional firm. It is not a quotation '
               'from any real business. In your own app, this PDF carries your name, logo and rates.')
FOOTER_TEXT = 'Demo PDF · made with QuoteRoom · not a valid quotation'
SAMPLE_KEY = 'demo_sample_project'      # AppSetting: the finished quotation the demo opens on (set by seed_demo)


def demo_notice_flowable(width):
    """Red-bordered notice box placed at the top of every demo PDF."""
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import Paragraph, Table, TableStyle
    red = colors.HexColor('#c62828')
    title = Paragraph(NOTICE_TITLE, ParagraphStyle('demo_t', fontName='Helvetica-Bold', fontSize=12,
                                                   textColor=red, leading=15, spaceAfter=2))
    body = Paragraph(NOTICE_TEXT, ParagraphStyle('demo_b', fontName='Helvetica', fontSize=8.5,
                                                 textColor=colors.HexColor('#7f1d1d'), leading=11))
    box = Table([[title], [body]], colWidths=[width])
    box.setStyle(TableStyle([
        ('BOX', (0, 0), (-1, -1), 1.5, red),
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#fef2f2')),
        ('LEFTPADDING', (0, 0), (-1, -1), 8), ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (0, 0), 6), ('BOTTOMPADDING', (0, -1), (-1, -1), 7),
    ]))
    box.spaceAfter = 8
    return box


def demo_enabled():
    return (os.environ.get('DEMO_MODE') or '').strip().lower() in ('1', 'true', 'yes', 'on')


def demo_username():
    return (os.environ.get('DEMO_USER') or 'demo-admin').strip()


def sample_id():
    """The sample quotation's id, or None (before the seed sets it, or once it's gone)."""
    from flask import g
    if 'demo_sample' not in g:
        from .models import AppSetting
        try:
            g.demo_sample = int(AppSetting.get(SAMPLE_KEY) or 0) or None
        except (TypeError, ValueError):
            g.demo_sample = None
    return g.demo_sample


# endpoint → (counter, methods, counts when the response status is in this range)
COUNTED = {
    'projects.create_project':        ('quotations', 'POST', range(300, 400)),   # saved → redirect to it
    'projects.download_pdf':          ('pdfs', 'GET', range(200, 300)),
    'projects.download_customer_pdf': ('pdfs', 'GET', range(200, 300)),
}
PDF_ENDPOINTS = ('projects.download_pdf', 'projects.download_customer_pdf')


_BOT = ('bot', 'crawl', 'spider', 'slurp', 'facebookexternalhit', 'preview', 'whatsapp', 'headless', 'lighthouse')


def _is_bot():
    ua = (request.headers.get('User-Agent') or '').lower()
    return not ua or any(b in ua for b in _BOT)


def count(field):
    """Add one to today's anonymous demo counter. Never breaks the request (e.g. before the table exists).
    True when counted."""
    if _is_bot():
        return False
    from datetime import datetime
    from sqlalchemy.exc import IntegrityError
    from . import db
    from .models import DemoStat
    t = DemoStat.__table__
    today = datetime.utcnow().date()
    for _ in range(2):                 # second try if another request created today's row at the same moment
        try:
            done = db.session.execute(t.update().where(t.c.day == today).values({field: t.c[field] + 1})).rowcount
            if not done:
                db.session.execute(t.insert().values({'day': today, 'starts': 0, 'quotations': 0, 'pdfs': 0, field: 1}))
            db.session.commit()
            return True
        except IntegrityError:
            db.session.rollback()
        except Exception:
            db.session.rollback()
            return False
    return False


def count_demo_use(response):
    """after_request hook: count quotations created and PDFs opened in the demo."""
    if not demo_enabled():
        return response
    rule = COUNTED.get(request.endpoint)
    if rule and request.method == rule[1] and response.status_code in rule[2]:
        field = rule[0]
        if request.endpoint in PDF_ENDPOINTS and (request.view_args or {}).get('project_id') == sample_id():
            field = 'sample_pdfs'          # the sample's PDF (step 1); 'pdfs' is a quotation they made
        count(field)
    elif (request.endpoint == 'projects.create_project' and request.method == 'GET' and request.args.get('try')
          and response.status_code == 200):
        count('tried')                     # opened "Make your own" (step 2)
    return response


# Marketing-site pages: a browser's first visit to any of them counts once (an anonymous "seen" cookie, no ID)
SITE_PAGES = {'main.index', 'marketing.landing', 'marketing.tutorials_page', 'marketing.privacy', 'marketing.terms',
              'marketing.free_trial'}
SEEN_COOKIE = 'qr_seen'


def count_site_visit(response):
    """after_request hook (marketing deployment): count a browser's first visit to the website."""
    from .marketing import marketing_enabled
    if (request.method == 'GET' and request.endpoint in SITE_PAGES and response.status_code == 200
            and not request.cookies.get(SEEN_COOKIE) and marketing_enabled() and not _is_bot()):
        if count('site_visitors'):         # only mark the browser once it has been counted (not before the update)
            response.set_cookie(SEEN_COOKIE, '1', max_age=2 * 365 * 24 * 3600, httponly=True, samesite='Lax',
                                secure=request.is_secure)
    return response


def block_demo_writes():
    """before_request hook: refuse data-changing requests that are blocked in the demo."""
    if not demo_enabled() or request.method in ('GET', 'HEAD', 'OPTIONS'):
        return None
    if request.endpoint not in BLOCKED_ENDPOINTS:
        return None
    message = 'This is disabled in the demo. Get your own app to use it for real.'
    if request.is_json or request.accept_mimetypes.best == 'application/json' or \
            request.endpoint in ('projects.generate_payment_link', 'projects.set_project_access'):
        return jsonify({'error': message}), 403
    flash(message, 'warning')
    return redirect(request.referrer or url_for('projects.list_projects'))


@demo_bp.route('/demo')
def start():
    """One click into the demo account — no password needed."""
    if not demo_enabled():
        abort(404)
    from flask_login import current_user
    from .models import User
    if current_user.is_authenticated:
        return redirect(_landing())
    user = User.query.filter_by(username=demo_username()).first()
    if not user:
        # No redirect to the login page here: in demo mode that sends visitors back to /demo (a loop)
        return ('<!doctype html><meta name="viewport" content="width=device-width"><title>Demo resetting</title>'
                '<body style="font-family:system-ui;padding:3rem;text-align:center"><h2>The demo is being reset</h2>'
                '<p>Please try again in a minute.</p><p><a href="/demo">Try again</a></p></body>', 503)
    login_user(user, remember=True)     # stays signed in after the browser is closed
    count('starts')                     # once per browser: later visits are already signed in
    return redirect(_landing())


def _landing():
    """?next= when it's a page on this site, else the sample quotation (step 1 of the guide), else the list."""
    from .auth import safe_next
    if request.args.get('next') or not sample_id():
        return safe_next()
    return url_for('projects.view_project', project_id=sample_id())


def guide():
    """The demo guide's state for this page: {'step': 1–3 (0 elsewhere), 'sample': id, 'pdf': this quotation's PDF,
    'try': on "Make your own"}."""
    from . import layout
    sid = sample_id()
    pid = (request.view_args or {}).get('project_id')
    out = {'step': 0, 'sample': sid, 'pdf': None, 'try': False}
    if request.endpoint == 'projects.view_project' and pid:
        pdf = 'projects.download_customer_pdf' if layout.single_pdf() else 'projects.download_pdf'
        out.update(step=1 if pid == sid else 3, pdf=url_for(pdf, project_id=pid))
    elif request.endpoint == 'projects.create_project':
        out['step'], out['try'] = 2, bool(request.args.get('try'))
    return out


@demo_bp.route('/demo/reset', methods=['GET', 'POST'])
def reset():
    """Nightly reset, called by Vercel Cron with `Authorization: Bearer $CRON_SECRET`."""
    secret = (os.environ.get('CRON_SECRET') or '').strip()
    supplied = request.headers.get('Authorization', '')
    if not demo_enabled() or not secret or not hmac.compare_digest(supplied, f'Bearer {secret}'):
        abort(404)
    from .seed import seed_demo
    seed_demo(reset=True)
    current_app.logger.info('Demo data reset by cron.')   # seed log includes the password, so don't echo it
    return jsonify({'status': 'reset'})


def _draw_watermark(canvas):
    from reportlab.lib import colors
    width, height = canvas._pagesize
    canvas.saveState()
    canvas.setFillColor(colors.HexColor('#c62828'))
    canvas.setFillAlpha(0.10)
    canvas.setFont('Helvetica-Bold', 38)
    canvas.translate(width / 2, height / 2)
    canvas.rotate(40)
    canvas.drawCentredString(0, 0, WATERMARK_TEXT)
    canvas.restoreState()
    canvas.saveState()
    canvas.setFillColor(colors.HexColor('#c62828'))
    canvas.setFont('Helvetica-Bold', 8)
    canvas.drawCentredString(width / 2, 0.45 * 28.35, FOOTER_TEXT)
    canvas.restoreState()


def watermark_canvas_class():
    """A reportlab Canvas that stamps the watermark on top of each finished page."""
    from reportlab.pdfgen.canvas import Canvas

    class WatermarkedCanvas(Canvas):
        def showPage(self):
            _draw_watermark(self)
            super().showPage()

    return WatermarkedCanvas
