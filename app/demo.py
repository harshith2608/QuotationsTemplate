"""
Public demo mode — for the product's own demo deployment only.

    DEMO_MODE=1          turn it on
    DEMO_USER=demo-admin the account visitors are signed into (default: demo-admin)
    DEMO_PASSWORD=...    set to something long and random; visitors never need it
    CRON_SECRET=...      lets the nightly Vercel cron reset the demo data

In demo mode:
  * /demo signs a visitor straight into the demo account (no password shown)
  * anything that could vandalise the demo or produce a convincing fake is
    blocked: all admin saves (settings, branding, rates, users), deleting,
    payment links and access changes
  * every PDF carries a large "DEMO — NOT A VALID QUOTATION" watermark, a
    notice box at the top, and deliberately WRONG amounts (each figure is
    altered independently, so rows and totals don't add up) — a demo PDF can
    never be passed off as a real quotation
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
    'admin.create_user', 'admin.delete_user', 'admin.rename_user', 'admin.change_user_password',
    'admin.clear_notifications',
    'admin.test_razorpay', 'admin.test_email',
    'projects.delete_project', 'projects.delete_payment',
    'projects.generate_payment_link', 'projects.set_project_access',
    'projects.razorpay_webhook',
}

WATERMARK_TEXT = 'DEMO — NOT A VALID QUOTATION'
NOTICE_TITLE = 'DEMO QUOTATION — NOT VALID'
NOTICE_TEXT = ('This PDF was made in a public demo. All amounts shown are deliberately altered sample '
               'figures, not actual calculated values, and totals will not add up. Do not use it as a quotation.')
FOOTER_TEXT = 'Demo PDF · amounts are altered sample figures, not actual calculated values'


def scramble_amount(value):
    """A deliberately wrong amount for demo PDFs: the real value × 0.35–0.85 or 1.15–1.85, rounded.
    Deterministic (same input → same output) so a PDF looks stable, but each figure is changed
    independently, so rows never add up to the totals."""
    try:
        value = float(value or 0)
    except (TypeError, ValueError):
        return value
    if not value:
        return 0.0
    h = int(hashlib.sha256(f'{value:.2f}'.encode()).hexdigest()[:8], 16)
    step = (h % 1000) / 1000                       # 0.000–0.999
    factor = 0.35 + step * 0.5 if h & 1 << 20 else 1.15 + step * 0.7
    wrong = value * factor
    if abs(wrong) >= 100:
        wrong = round(wrong, -1)
    elif round(wrong, 2) == round(value, 2):
        wrong += 1
    return round(wrong, 2)


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
    from .models import User
    user = User.query.filter_by(username=demo_username()).first()
    if not user:
        flash('The demo is being reset. Please try again in a minute.', 'warning')
        return redirect(url_for('auth.login'))
    login_user(user)
    flash('Welcome to the demo! Explore freely — everything resets every night.', 'success')
    return redirect(url_for('projects.list_projects'))


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
    canvas.setFillAlpha(0.14)
    canvas.setFont('Helvetica-Bold', 38)
    canvas.translate(width / 2, height / 2)
    canvas.rotate(40)
    canvas.drawCentredString(0, 0, WATERMARK_TEXT)
    canvas.setFont('Helvetica-Bold', 16)
    canvas.drawCentredString(0, -34, 'Amounts are altered sample figures, not calculated values')
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
