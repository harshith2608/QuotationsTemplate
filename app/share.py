"""
Online approval: a private link (/q/<token>) where the customer views the quotation, downloads the PDF,
and taps Accept or asks for changes. Accepting moves a pending quotation to Confirmed and notifies the admin.
No login: the long random token is the key. Staff turn the link on and off from the quotation page.
"""
import secrets
from datetime import datetime

from flask import Blueprint, abort, flash, make_response, redirect, render_template, request, send_file, url_for
from flask_login import current_user, login_required

from . import billing, db

share_bp = Blueprint('share', __name__)

DETAILS = {'summary': 'Material breakdown', 'full': 'Full detailed quotation'}

# Public pages: allowed even when the business's plan has ended (see plan.ALWAYS_ALLOWED)
PUBLIC_ENDPOINTS = {'share.view', 'share.pdf', 'share.respond'}


def _active_share(project):
    from .models import QuoteShare
    if not billing.ready():
        return None
    return (QuoteShare.query.filter_by(project_id=project.id, active=True)
            .order_by(QuoteShare.created_at.desc()).first())


def active_share_url(project):
    share = _active_share(project)
    return url_for('share.view', token=share.token, _external=True) if share else ''


def share_status(project, current_rev=False):
    """For the quotation page: the active link, its views and the customer's answers.
    current_rev: the latest revision number if the caller already knows it (saves a query)."""
    from .models import QuoteResponse
    if not billing.ready():
        return None
    share = _active_share(project)
    responses = (QuoteResponse.query.filter_by(project_id=project.id)
                 .order_by(QuoteResponse.created_at.desc()).all())
    if current_rev is False:
        current_rev = billing.latest_revision_number(project)
    latest = responses[0] if responses else None
    return {
        'share': share,
        'url': url_for('share.view', token=share.token, _external=True) if share else '',
        'responses': responses,
        'latest': latest,
        'current_revision': current_rev,
        # an answer about an older revision no longer applies once the quotation has changed
        'latest_is_current': bool(latest and (latest.revision or None) == (current_rev or None)),
    }


def _can_view(project):
    from .models import ProjectAccess
    return current_user.is_admin or project.created_by == current_user.id or \
        ProjectAccess.query.filter_by(project_id=project.id, user_id=current_user.id).first() is not None


# ── Staff: turn the link on / off ───────────────────────────────────────────

@share_bp.route('/projects/<int:project_id>/share', methods=['POST'])
@login_required
def create(project_id):
    from .models import Project, QuoteShare
    project = Project.query.get_or_404(project_id)
    if not _can_view(project):
        abort(403)
    if not billing.ready():
        flash('Online approval is available after the next database update.', 'warning')
    elif project.status == 'draft':
        flash('Save the quotation first.', 'warning')
    elif not _active_share(project):
        billing.ensure_first_revision(project, current_user)
        detail = request.form.get('detail')
        db.session.add(QuoteShare(project_id=project.id, token=secrets.token_urlsafe(24),
                                  created_by=current_user.id, detail=detail if detail in DETAILS else 'summary'))
        db.session.commit()
        flash('Approval link created. Send it to your customer.', 'success')
    return redirect(url_for('projects.view_project', project_id=project.id) + '#approval')


@share_bp.route('/projects/<int:project_id>/share/detail', methods=['POST'])
@login_required
def set_detail(project_id):
    """Change what the customer's link shows (same link)."""
    from .models import Project
    project = Project.query.get_or_404(project_id)
    if not _can_view(project):
        abort(403)
    share = _active_share(project)
    detail = request.form.get('detail')
    if share and detail in DETAILS:
        share.detail = detail
        db.session.commit()
        flash(f'The link now shows the {DETAILS[detail].lower()}.', 'success')
    return redirect(url_for('projects.view_project', project_id=project.id) + '#approval')


@share_bp.route('/projects/<int:project_id>/share/off', methods=['POST'])
@login_required
def disable(project_id):
    from .models import Project
    project = Project.query.get_or_404(project_id)
    if not _can_view(project):
        abort(403)
    share = _active_share(project)
    if share:
        share.active = False
        db.session.commit()
        flash('Approval link turned off. The old link no longer opens the quotation.', 'success')
    return redirect(url_for('projects.view_project', project_id=project.id) + '#approval')


# ── Public: the customer's page ─────────────────────────────────────────────

def _share_or_404(token):
    from .models import QuoteShare
    if not billing.ready() or not token or len(token) > 64:
        abort(404)
    share = QuoteShare.query.filter_by(token=token, active=True).first()
    if not share:
        abort(404)
    from .models import Project
    project = db.session.get(Project, share.project_id)
    if not project or project.status == 'draft':
        abort(404)
    return share, project


def _private(resp):
    resp = make_response(resp)
    resp.headers['Cache-Control'] = 'no-store'
    resp.headers['X-Robots-Tag'] = 'noindex, nofollow'
    return resp


@share_bp.route('/q/<token>')
def view(token):
    share, project = _share_or_404(token)
    if not current_user.is_authenticated:          # staff checking the link don't count as the customer
        now = datetime.utcnow()
        share.first_viewed_at = share.first_viewed_at or now
        share.last_viewed_at = now
        share.view_count = (share.view_count or 0) + 1
        db.session.commit()
    status = share_status(project)
    snap = billing.quotation_snapshot(project)
    from .models import AppSetting
    pay = AppSetting.get_many(['upi_id', 'bank_name', 'account_name', 'account_number', 'ifsc_code'])
    return _private(render_template('share/quote.html', share=share, project=project, snap=snap, status=status,
                                    pay=pay, paid=billing.paid_total(project)))


@share_bp.route('/q/<token>/pdf')
def pdf(token):
    share, project = _share_or_404(token)
    from .models import AppSetting
    from .pdf_utils import generate_customer_pdf, generate_pdf
    pay = AppSetting.get_many(['upi_id', 'bank_name', 'account_name', 'account_number', 'ifsc_code'])
    make = generate_pdf if share.detail == 'full' else generate_customer_pdf      # full or material breakdown
    buf = make(project, payment_settings=pay, total_paid=billing.paid_total(project))
    name = f"Quotation_{project.customer_name.replace(' ', '_')}_{project.id}.pdf"
    return _private(send_file(buf, mimetype='application/pdf', download_name=name, as_attachment=False))


@share_bp.route('/q/<token>/respond', methods=['POST'])
def respond(token):
    share, project = _share_or_404(token)
    from .models import Notification, QuoteResponse
    kind = request.form.get('kind')
    name = ' '.join((request.form.get('name') or '').split())[:80]
    note = (request.form.get('note') or '').strip()[:1000]
    back = url_for('share.view', token=token)
    if kind == 'accepted':
        if len(name) < 2 or not request.form.get('agree'):
            flash('Type your name and tick the box to accept the quotation.', 'danger')
            return redirect(back + '#respond')
    elif kind == 'changes':
        if len(note) < 3:
            flash('Tell us what you would like changed.', 'danger')
            return redirect(back + '#respond')
    else:
        abort(400)
    rev = billing.latest_revision_number(project)
    db.session.add(QuoteResponse(share_id=share.id, project_id=project.id, kind=kind, name=name or None,
                                 note=note or None, total=project.final_total, revision=rev))
    who = name or project.customer_name
    if kind == 'accepted':
        if project.stage == 'pending':
            project.set_stage('confirmed', None, note=f'Accepted online by {who}')
        title = f'Quotation #{project.id} accepted'
        message = f'{who} accepted the quotation for ₹{project.final_total:,.2f} online' + (f' (revision {rev})' if rev else '') + '.'
    else:
        title = f'Changes requested on quotation #{project.id}'
        message = f'{who} asked for changes: {note}'
    db.session.add(Notification(title=title, message=message[:500], project_id=project.id))
    db.session.commit()
    _email_admin(title, message, project)
    flash('Thank you! Your acceptance has been recorded.' if kind == 'accepted'
          else 'Thank you! We have your request and will send an updated quotation.', 'success')
    return redirect(back)


def _email_admin(title, message, project):
    """Best effort: email the business if email is set up (Admin → Settings → Email)."""
    from .models import AppSetting
    from .projects import _send_email
    to = (AppSetting.get('admin_email', '') or '').strip()
    if to:
        link = url_for('projects.view_project', project_id=project.id, _external=True)
        _send_email(to, title, f'{message}\n\nOpen the quotation: {link}')
