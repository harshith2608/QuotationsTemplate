"""Pages for invoices, payment reminders, balances due and quotation revisions (logic in billing.py)."""
import json
from datetime import date, datetime
from urllib.parse import quote

from flask import Blueprint, abort, flash, redirect, render_template, request, send_file, url_for
from flask_login import current_user, login_required

from . import billing, db
from .decorators import admin_required

billing_bp = Blueprint('billing', __name__)


def _project_or_403(project_id):
    from .models import Project, ProjectAccess
    project = Project.query.get_or_404(project_id)
    if not (current_user.is_admin or project.created_by == current_user.id or
            ProjectAccess.query.filter_by(project_id=project.id, user_id=current_user.id).first()):
        abort(403)
    return project


def _back(project, anchor=''):
    return redirect(url_for('projects.view_project', project_id=project.id) + anchor)


def _not_ready(project):
    flash('This is available after the next database update.', 'warning')
    return _back(project)


# ── Invoices ─────────────────────────────────────────────────────────────────

@billing_bp.route('/projects/<int:project_id>/invoice', methods=['POST'])
@login_required
@admin_required
def create_invoice(project_id):
    project = _project_or_403(project_id)
    if not billing.ready():
        return _not_ready(project)
    try:
        issued_on = date.fromisoformat(request.form.get('issued_on') or date.today().isoformat())
    except ValueError:
        flash('Choose a valid invoice date.', 'danger')
        return _back(project, '#invoice')
    if issued_on > date.today():
        flash('The invoice date can\'t be in the future.', 'danger')
        return _back(project, '#invoice')
    settings = billing.invoice_settings()
    try:
        gst_rate = float(request.form.get('gst_rate', settings['gst_rate']))
    except ValueError:
        gst_rate = -1
    prices = request.form.get('prices', settings['prices'])
    if prices not in (billing.PRICES_EXCLUSIVE, billing.PRICES_INCLUSIVE):
        prices = settings['prices']
    with_gst = request.form.get('with_gst', '1' if settings['with_gst'] else '0') == '1'
    if not with_gst:
        gst_rate = 0
    billing.ensure_first_revision(project, current_user)
    try:
        inv = billing.issue_invoice(project, current_user, issued_on=issued_on, gst_rate=gst_rate, prices=prices,
                                    with_gst=with_gst,
                                    layout=request.form.get('layout', settings['layout']),
                                    customer_gstin=request.form.get('customer_gstin', ''),
                                    place_code=request.form.get('place_code', ''),
                                    hsn=(request.form.get('hsn', settings['hsn']) or '').strip()[:10],
                                    notes=request.form.get('notes', settings['notes'])[:1500])
    except billing.InvoiceError as exc:
        flash(str(exc), 'danger')
        return _back(project, '#invoice')
    if project.stage == 'pending':
        project.set_stage('confirmed', current_user, note=f'Invoice {inv.number} issued')
    db.session.commit()
    flash(f'Invoice {inv.number} issued for ₹{inv.total:,.2f}.', 'success')
    return _back(project, '#invoice')


def _invoice_or_404(project, invoice_id):
    from .models import Invoice
    inv = db.session.get(Invoice, invoice_id)
    if not inv or inv.project_id != project.id:
        abort(404)
    return inv


@billing_bp.route('/projects/<int:project_id>/invoices/<int:invoice_id>/pdf')
@login_required
def invoice_pdf(project_id, invoice_id):
    project = _project_or_403(project_id)
    if not billing.ready():
        abort(404)
    inv = _invoice_or_404(project, invoice_id)
    from .pdf_utils import generate_invoice_pdf
    paid = billing.paid_total(project) if inv.status == 'issued' else 0
    buf = generate_invoice_pdf(inv, billing.invoice_data(inv), total_paid=paid)
    name = 'Invoice_' + inv.number.replace('/', '-') + '.pdf'
    return send_file(buf, mimetype='application/pdf', download_name=name,
                     as_attachment=request.args.get('download') == '1')


@billing_bp.route('/projects/<int:project_id>/invoices/<int:invoice_id>/cancel', methods=['POST'])
@login_required
@admin_required
def cancel_invoice(project_id, invoice_id):
    project = _project_or_403(project_id)
    if not billing.ready():
        return _not_ready(project)
    inv = _invoice_or_404(project, invoice_id)
    if inv.status == 'issued':
        inv.status, inv.cancelled_at = 'cancelled', datetime.utcnow()
        db.session.commit()
        flash(f'Invoice {inv.number} cancelled. Its number is not reused; you can issue a new invoice.', 'success')
    return _back(project, '#invoice')


@billing_bp.route('/projects/<int:project_id>/invoices/<int:invoice_id>/whatsapp')
@login_required
def invoice_whatsapp(project_id, invoice_id):
    project = _project_or_403(project_id)
    if not billing.ready():
        abort(404)
    inv = _invoice_or_404(project, invoice_id)
    from .share import invoice_url
    message = billing.invoice_message(project, inv, invoice_url(inv))
    return redirect(f'https://wa.me/{billing.whatsapp_number(project.mobile)}?text={quote(message)}')


def _email_target(project):
    to = (request.form.get('to') or project.email or '').strip()
    import re as _re
    return to if _re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', to) else ''


@billing_bp.route('/projects/<int:project_id>/invoices/<int:invoice_id>/email', methods=['POST'])
@login_required
def invoice_email(project_id, invoice_id):
    """Email the invoice from the business's own email account (Admin → Settings → Email), PDF attached."""
    from .branding import get_brand
    from .pdf_utils import generate_invoice_pdf
    from .projects import _send_email
    from .share import invoice_url
    project = _project_or_403(project_id)
    if not billing.ready():
        return _not_ready(project)
    inv = _invoice_or_404(project, invoice_id)
    if not billing.email_ready():
        flash('Set up email in Admin → Settings → Email to send invoices by email.', 'warning')
        return _back(project, '#invoice')
    to = _email_target(project)
    if not to:
        flash('Enter a valid customer email address.', 'warning')
        return _back(project, '#invoice')
    subject = f'Invoice {inv.number} from {get_brand()["name"]}'
    body = billing.invoice_message(project, inv, invoice_url(inv)).replace('*', '')
    paid = billing.paid_total(project) if inv.status == 'issued' else 0
    pdf = generate_invoice_pdf(inv, billing.invoice_data(inv), total_paid=paid).getvalue()
    if _send_email(to, subject, body, attachments=[('Invoice_' + inv.number.replace('/', '-') + '.pdf', pdf, 'pdf')]):
        flash(f'Invoice {inv.number} emailed to {to}.', 'success')
    else:
        flash('The email could not be sent. Check Admin → Settings → Email (use "Send test email").', 'danger')
    return _back(project, '#invoice')


@billing_bp.route('/projects/<int:project_id>/email', methods=['POST'])
@login_required
def quotation_email(project_id):
    """Email the quotation PDF (initial or full) from the business's email, optionally with the approval link."""
    import secrets
    from .branding import get_brand
    from .models import AppSetting, QuoteShare
    from .pdf_utils import generate_customer_pdf, generate_pdf
    from .projects import _send_email
    from .share import DETAILS, _active_share
    project = _project_or_403(project_id)
    if project.status == 'draft':
        flash('Save the quotation first.', 'warning')
        return _back(project)
    if not billing.email_ready():
        flash('Set up email in Admin → Settings → Email to send quotations by email.', 'warning')
        return _back(project)
    to = _email_target(project)
    if not to:
        flash('Enter a valid customer email address.', 'warning')
        return _back(project)
    full = request.form.get('pdf') == 'full'
    link = ''
    if request.form.get('with_link') and billing.ready():
        share = _active_share(project)
        if not share:
            billing.ensure_first_revision(project, current_user)
            share = QuoteShare(project_id=project.id, token=secrets.token_urlsafe(24), created_by=current_user.id,
                               detail='full' if full else 'summary')
            db.session.add(share)
            db.session.commit()
        link = url_for('share.view', token=share.token, _external=True)
    pay = AppSetting.get_many(['upi_id', 'bank_name', 'account_name', 'account_number', 'ifsc_code'])
    pdf = (generate_pdf if full else generate_customer_pdf)(project, payment_settings=pay,
                                                            total_paid=billing.paid_total(project)).getvalue()
    name = ('Quotation_' if full else 'CustomerQuotation_') + project.customer_name.replace(' ', '_') + f'_{project.id}.pdf'
    subject = f'Quotation #{project.id} from {get_brand()["name"]}'
    if _send_email(to, subject, billing.quotation_email_text(project, link), attachments=[(name, pdf, 'pdf')]):
        flash(f'Quotation emailed to {to}.', 'success')
    else:
        flash('The email could not be sent. Check Admin → Settings → Email (use "Send test email").', 'danger')
    return _back(project)


# ── Payment reminders ────────────────────────────────────────────────────────

@billing_bp.route('/projects/<int:project_id>/remind', methods=['POST'])
@login_required
def send_reminder(project_id):
    """Record the reminder and open WhatsApp with the message ready (optionally with a Razorpay link)."""
    from .models import AppSetting, PaymentReminder
    project = _project_or_403(project_id)
    if not billing.ready():
        return _not_ready(project)
    due = billing.balance(project)
    back = request.form.get('back')
    back_url = url_for('billing.balances_due') if back == 'due' else \
        url_for('projects.view_project', project_id=project.id) + '#payments'
    if due <= 0:
        flash('Nothing is due on this quotation.', 'info')
        return redirect(back_url)
    try:
        amount = round(float(request.form.get('amount') or due), 2)
    except ValueError:
        amount = due
    if not 1 <= amount <= due:
        flash(f'Enter an amount between ₹1 and the balance due (₹{due:,.2f}).', 'danger')
        return redirect(back_url)
    link = ''
    if request.form.get('with_link'):
        from .projects import RazorpayLinkError, create_razorpay_link
        try:
            link = create_razorpay_link(project, amount, due)
        except RazorpayLinkError as exc:
            flash(f'Payment link not created: {exc}', 'danger')
            return redirect(back_url)
    pay = AppSetting.get_many(['upi_id', 'bank_name', 'account_name', 'account_number', 'ifsc_code'])
    message = billing.reminder_message(project, amount, link, pay)
    db.session.add(PaymentReminder(project_id=project.id, sent_by=current_user.id, amount=amount))
    db.session.commit()
    return redirect(f'https://wa.me/{billing.whatsapp_number(project.mobile)}?text={quote(message)}')


@billing_bp.route('/payments/due')
@login_required
def balances_due():
    from .models import AppSetting
    rows = billing.balances_due(current_user)
    return render_template('billing/due.html', title='Balances due', rows=rows,
                           total=round(sum(r['balance'] for r in rows), 2), ready=billing.ready(),
                           razorpay=bool(AppSetting.get('razorpay_key_id', '')))


# ── Revisions ────────────────────────────────────────────────────────────────

@billing_bp.route('/projects/<int:project_id>/revisions/<int:number>')
@login_required
def revision(project_id, number):
    from .models import QuoteRevision
    project = _project_or_403(project_id)
    if not billing.ready():
        abort(404)
    rev = QuoteRevision.query.filter_by(project_id=project.id, number=number).first_or_404()
    prev = QuoteRevision.query.filter_by(project_id=project.id, number=number - 1).first()
    snap = json.loads(rev.snapshot)
    changes = billing.diff_snapshots(json.loads(prev.snapshot), snap) if prev else []
    return render_template('billing/revision.html', title=f'Quotation #{project.id} – Rev {number}', project=project,
                           rev=rev, snap=snap, changes=changes,
                           latest=billing.latest_revision_number(project))
