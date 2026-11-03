"""Pages for the material list of a quotation and its rules (logic in material_list.py)."""
import json
from urllib.parse import quote

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from . import access, db
from . import material_list as ML
from .catalog import WORK_TYPES
from .decorators import admin_required

material_list_bp = Blueprint('materials_list', __name__)


def _project(project_id):
    if not ML.switched_on():
        abort(404)
    from .models import Project
    project = Project.query.get_or_404(project_id)
    if not access.can_view(project, current_user):
        abort(403)
    return project


def _back(project):
    return redirect(url_for('materials_list.view', project_id=project.id))


def _not_ready(project):
    if not ML.ready():
        flash('The material list is available after the next database update.', 'warning')
        return redirect(url_for('projects.view_project', project_id=project.id))
    if project.status == 'draft':
        flash('Finish the quotation first: the material list is made from a saved quotation.', 'warning')
        return redirect(url_for('projects.view_project', project_id=project.id))
    return None


@material_list_bp.route('/projects/<int:project_id>/materials', methods=['GET', 'POST'])
@login_required
def view(project_id):
    project = _project(project_id)
    stop = _not_ready(project)
    if stop:
        return stop
    can_edit = access.can_edit(project, current_user)
    lst = ML.get(project)
    if request.method == 'POST':
        if not can_edit or lst is None:
            abort(403)
        ML.save(lst, request.form)
        flash('Material list saved.', 'success')
        return _back(project)
    if lst is None:
        ML.seed_rules()
        lst = ML.create(project)
    groups, removed = ML.by_group(lst), ML.by_group(lst, removed=True)
    return render_template('projects/materials.html', project=project, lst=lst, groups=groups, removed=removed,
                           removed_count=sum(len(lines) for _, lines in removed), names=ML.groups(), can_edit=can_edit,
                           changed=ML.changed(lst, project),
                           texts={g_: ML.text(lst, project, g_) for g_, _ in groups},
                           all_text=ML.text(lst, project), title=f'Material list – {project.customer_name}')


@material_list_bp.route('/projects/<int:project_id>/materials/rebuild', methods=['POST'])
@login_required
def rebuild(project_id):
    project = _project(project_id)
    stop = _not_ready(project)
    if stop:
        return stop
    lst = ML.get(project)
    if lst is None or not access.can_edit(project, current_user):
        abort(403)
    report = ML.rebuild(lst, project)
    bits = []
    for label, key in (('added', 'added'), ('changed', 'changed'), ('no longer needed', 'gone')):
        if report[key]:
            bits.append(f'{label}: ' + ', '.join(report[key][:5]) + (' …' if len(report[key]) > 5 else ''))
    flash('Rebuilt from the quotation, with your changes kept. ' + ('; '.join(bits).capitalize() + '.' if bits
          else 'Nothing else changed.'), 'success')
    return _back(project)


@material_list_bp.route('/projects/<int:project_id>/materials/whatsapp')
@login_required
def whatsapp(project_id):
    project = _project(project_id)
    stop = _not_ready(project)
    if stop:
        return stop
    lst = ML.get(project)
    if lst is None:
        return _back(project)
    group = request.args.get('group') or None
    # no number: they choose who to send it to (a supplier, the carpenter…)
    return redirect('https://wa.me/?text=' + quote(ML.text(lst, project, group)))


# ── Admin → Material rules ───────────────────────────────────────────────────

def _rule_from_form(form, p, rule):
    from . import units
    rule.name = ML.clean_text(form.get(p + 'name'), 100) or rule.name
    group = ML.clean_text(form.get(p + 'group'), ML.GROUP_MAX)
    rule.category = group if group in ML.groups() else ML.fallback_group()
    work = form.get(p + 'work', '')
    rule.work_type = work if work in WORK_TYPES else ''
    per = ML.number(form.get(p + 'per'))
    rule.per_sqft = units.rate_to_sqft(per) if per is not None else (rule.per_sqft or 0)
    rule.unit = ML.clean_text(form.get(p + 'unit'), ML.UNIT_MAX)
    rule.wastage = min(ML.number(form.get(p + 'wastage')) or 0, 500)
    rule.round_up = bool(form.get(p + 'up'))
    rule.active = bool(form.get(p + 'active'))
    mats = [m for m in form.getlist(p + 'mat') if m]
    rule.materials = json.dumps([] if form.get(p + 'allmat') else mats)


@material_list_bp.route('/admin/material-rules', methods=['GET', 'POST'])
@login_required
@admin_required
def rules():
    if not ML.switched_on():
        abort(404)
    if not ML.ready():
        flash('Material rules are available after the next database update.', 'warning')
        return redirect(url_for('admin.rates'))
    from .models import AppSetting, Material, MaterialRule
    ML.seed_rules()
    if request.method == 'POST':
        section = request.form.get('section')
        if section == 'rules':
            for rule in ML.rules():
                p = f'r{rule.id}_'
                if request.form.get(p + 'remove'):
                    db.session.delete(rule)
                elif p + 'name' in request.form:
                    _rule_from_form(request.form, p, rule)
            import re
            news = sorted((int(m.group(1) or 1), m.group(0)[:-4]) for m in
                          (re.fullmatch(r'new(\d*)_name', k) for k in request.form) if m)
            for n, (_, p) in enumerate(news):               # the new rules: new_, new2_, new3_… (one per row)
                if ML.clean_text(request.form.get(p + 'name'), 100):
                    rule = MaterialRule(sort_order=len(ML.rules()) + 1 + n)
                    _rule_from_form(request.form, p, rule)
                    db.session.add(rule)
            flash('Material rules saved. Lists made from now on use them (Rebuild an existing list to update it).',
                  'success')
        elif section == 'groups':
            olds, news = request.form.getlist('group_old'), request.form.getlist('group_new')
            gone = set(request.form.getlist('group_remove'))
            rows = [(o, n, str(i) in gone) for i, (o, n) in enumerate(zip(olds, news))]
            if ML.clean_text(request.form.get('group_add'), ML.GROUP_MAX):
                rows.append(('', request.form.get('group_add'), False))
            ML.save_groups(rows)
            flash('Groups saved.', 'success')
        elif section == 'items':
            names = ML.groups()
            for name, group in zip(request.form.getlist('item_name'), request.form.getlist('item_group')):
                if group == '__forget':
                    ML.forget(name)
                elif group == '' or group in names:
                    ML.remember(name, group)
            spare = ML.number(request.form.get('spare'))
            AppSetting.set(ML.SPARE_KEY, str(min(spare or 0, 100)))
            flash('Saved.', 'success')
        db.session.commit()
        return redirect(url_for('materials_list.rules'))
    from . import units
    materials = [m.name for m in Material.query.filter_by(active=True).order_by(Material.sort_order, Material.id)]
    rows = [{'rule': r, 'materials': ML.rule_materials(r), 'per': round(units.rate_value(r.per_sqft), 4)}
            for r in ML.rules()]
    return render_template('admin/material_rules.html', rows=rows, groups=ML.groups(), materials=materials,
                           work_types=WORK_TYPES, items=ML.item_group_rows(), spare=ML.spare(),
                           area_label=units.area_label(), title='Material rules')
