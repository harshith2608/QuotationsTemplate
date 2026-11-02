"""Pages for the AI helpers on quotations (logic in ai_tools.py): Draft from a message, Check before sending."""
from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from . import access, ai_tools

ai_tools_bp = Blueprint('ai_tools', __name__)


@ai_tools_bp.route('/projects/draft', methods=['GET', 'POST'])
@login_required
def draft():
    if not ai_tools.available('draft'):
        abort(404)
    left, limit = ai_tools.left('draft')
    message = ''
    if request.method == 'POST':
        message = request.form.get('message', '')
        try:
            result = ai_tools.draft(message)
        except ai_tools.AIProblem as exc:
            flash(str(exc), 'warning')
        else:
            from .projects import render_new_form
            start = {'rooms_json': result['rooms_json'], 'discount_type': 'none', 'discount_value': 0,
                     'plywood_thickness': ''}
            return render_new_form(start, ai_draft=result)
        left, limit = ai_tools.left('draft')
    return render_template('projects/draft.html', title='Draft from a message', message=message, left=left,
                           limit=limit)


@ai_tools_bp.route('/projects/<int:project_id>/check', methods=['GET', 'POST'])
@login_required
def check(project_id):
    from .models import Project
    if not ai_tools.available('check'):
        abort(404)
    project = Project.query.get_or_404(project_id)
    if not access.can_view(project, current_user):
        abort(403)
    if request.method == 'GET' or project.status == 'draft':
        return redirect(url_for('projects.view_project', project_id=project.id))
    result = ai_tools.check(project)
    left, limit = ai_tools.left('check')
    return render_template('projects/check.html', title=f'Check – {project.customer_name}', project=project,
                           result=result, left=left, limit=limit,
                           can_edit=access.can_edit(project, current_user))
