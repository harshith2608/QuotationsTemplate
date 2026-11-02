"""Pages for the AI helpers on quotations (logic in ai_tools.py): Draft from a message, Check before sending."""
from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from . import access, ai_tools

ai_tools_bp = Blueprint('ai_tools', __name__)


def _photos():
    """The photos sent with the draft: shrunk on the phone (data URLs in photo_data) or, without JavaScript, the files
    themselves. Prepared for the AI (prepare_photo). Raises AIProblem."""
    import base64
    raws = []
    for url in request.form.getlist('photo_data'):
        head, _, body = url.partition(',')
        if head.startswith('data:image/') and ';base64' in head and body:
            try:
                raws.append(base64.b64decode(body, validate=True))
            except ValueError:
                raise ai_tools.AIProblem('A photo couldn\'t be read. Choose it again.')
    if not raws:
        raws = [f.read() for f in request.files.getlist('photos') if f and f.filename]
    if len(raws) > ai_tools.PHOTO_MAX:
        raise ai_tools.AIProblem(f'Up to {ai_tools.PHOTO_MAX} photos at a time: one page each.')
    return [ai_tools.prepare_photo(r) for r in raws]


@ai_tools_bp.route('/projects/draft', methods=['GET', 'POST'])
@login_required
def draft():
    photos_on = ai_tools.available('photos')
    if not (ai_tools.available('draft') or photos_on):
        abort(404)
    message = ''
    if request.method == 'POST':
        message = request.form.get('message', '')
        try:
            photos = _photos() if photos_on else []
            if not photos and not ai_tools.available('draft'):
                raise ai_tools.AIProblem('Add a photo of your site notes.')
            result = ai_tools.draft(message, photos)
        except ai_tools.AIProblem as exc:
            flash(str(exc), 'warning')
        else:
            import base64
            from .projects import render_new_form
            start = {'rooms_json': result['rooms_json'], 'discount_type': 'none', 'discount_value': 0,
                     'plywood_thickness': ''}
            # shown small next to the draft for checking, from this page only: never stored
            result['photos'] = ['data:image/jpeg;base64,' + base64.b64encode(p).decode() for p in photos]
            return render_new_form(start, ai_draft=result)
    return render_template('projects/draft.html', title='Draft from a message', message=message,
                           text_on=ai_tools.available('draft'), photos_on=photos_on,
                           left=ai_tools.left('draft'), photos_left=ai_tools.left('photos'),
                           photo_max=ai_tools.PHOTO_MAX)


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
