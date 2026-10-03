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
  * every PDF carries a large "DEMO — NOT A VALID QUOTATION" watermark
  * /demo/reset (called by the Vercel cron with CRON_SECRET) wipes and
    reloads the demo data
"""
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
    'projects.delete_project', 'projects.delete_payment',
    'projects.generate_payment_link', 'projects.set_project_access',
    'projects.razorpay_webhook',
}

WATERMARK_TEXT = 'DEMO — NOT A VALID QUOTATION'


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
    return redirect(request.referrer or request.path)


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
    canvas.drawCentredString(0, -34, 'Created in a public demo · values are examples only')
    canvas.restoreState()


def watermark_canvas_class():
    """A reportlab Canvas that stamps the watermark on top of each finished page."""
    from reportlab.pdfgen.canvas import Canvas

    class WatermarkedCanvas(Canvas):
        def showPage(self):
            _draw_watermark(self)
            super().showPage()

    return WatermarkedCanvas
