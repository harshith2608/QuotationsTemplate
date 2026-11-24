"""BOM pages: the list, New BOM / edit, a BOM with its quotations and Create quotation (logic in boms.py)."""
from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from . import boms as B
from . import db

boms_bp = Blueprint('boms', __name__)


def _allowed():
    if not B.enabled():
        abort(404)
    if not B.can_use(current_user):
        abort(403)
    return B.ready()


def _bom(bom_id):
    if not _allowed():
        abort(404)
    bom = B.get(bom_id)
    if bom is None:
        abort(404)
    return bom


def _form_context(bom, areas):
    from . import business
    return dict(bom=bom, areas=areas, room_names=business.room_names())


@boms_bp.route('/boms')
@login_required
def list_boms():
    ready = _allowed()
    q = ' '.join((request.args.get('q') or '').split()).lower()
    rows = []
    if ready:
        counts = B.quotation_counts()
        for b in B.all_boms():
            if q and q not in f'{b.customer_name} {b.mobile} {b.email or ""} {b.address or ""} #{b.id}'.lower():
                continue
            areas = B.areas_of(b)
            rows.append({'bom': b, 'areas': len(areas), 'total': B.total(areas), 'quotes': counts.get(b.id, 0)})
    return render_template('boms/list.html', title='BOMs', rows=rows, q=q, ready=ready)


@boms_bp.route('/boms/new', methods=['GET', 'POST'])
@login_required
def new_bom():
    if not _allowed():
        return redirect(url_for('boms.list_boms'))
    from .models import Bom
    bom = Bom()
    if request.method == 'POST':
        errors = B.save(bom, request.form, current_user)
        if not errors:
            db.session.commit()
            flash('BOM saved.', 'success')
            return redirect(url_for('boms.view', bom_id=bom.id))
        for e in errors:
            flash(e, 'danger')
        return render_template('boms/form.html', title='New BOM', **_form_context(None, B.clean_areas(request.form.get('areas'))),
                               form=request.form)
    return render_template('boms/form.html', title='New BOM', **_form_context(None, []), form={})


@boms_bp.route('/boms/<int:bom_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_bom(bom_id):
    bom = _bom(bom_id)
    if request.method == 'POST':
        errors = B.save(bom, request.form, current_user)
        if not errors:
            db.session.commit()
            flash('BOM saved.', 'success')
            return redirect(url_for('boms.view', bom_id=bom.id))
        for e in errors:
            flash(e, 'danger')
        return render_template('boms/form.html', title=f'BOM #{bom.id}', **_form_context(bom, B.clean_areas(request.form.get('areas'))),
                               form=request.form)
    form = {'customer_name': bom.customer_name, 'mobile': bom.mobile, 'email': bom.email or '', 'address': bom.address or ''}
    return render_template('boms/form.html', title=f'BOM #{bom.id}', **_form_context(bom, B.areas_of(bom)), form=form)


@boms_bp.route('/boms/<int:bom_id>')
@login_required
def view(bom_id):
    bom = _bom(bom_id)
    areas = B.areas_of(bom)
    from . import access, quote_templates as QT
    quotes = [p for p in B.quotations_for(bom.id) if access.can_view(p, current_user)]
    return render_template('boms/view.html', title=f'BOM #{bom.id}', bom=bom, areas=areas, total=B.total(areas),
                           quotes=quotes, templates=QT.all_templates(),
                           quote_nos=__import__('app.quote_numbers', fromlist=['known']).known())


@boms_bp.route('/boms/<int:bom_id>/delete', methods=['POST'])
@login_required
def delete(bom_id):
    bom = _bom(bom_id)
    if not current_user.is_admin:
        abort(403)
    B.delete(bom)
    db.session.commit()
    flash(f'BOM #{bom_id} deleted. Quotations made from it are not affected.', 'success')
    return redirect(url_for('boms.list_boms'))
