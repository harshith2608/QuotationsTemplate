from datetime import datetime
from flask import Blueprint, jsonify, request
from flask_login import login_required, current_user
from . import db
from .models import MasterRoom, MasterItem, WoodRate, Project

api_bp = Blueprint('api', __name__, url_prefix='/api')


@api_bp.route('/master-rooms')
@login_required
def master_rooms():
    rooms = MasterRoom.query.order_by(MasterRoom.name).all()
    return jsonify([r.name for r in rooms])


@api_bp.route('/master-items')
@login_required
def master_items():
    items = MasterItem.query.order_by(MasterItem.name).all()
    return jsonify([i.name for i in items])


@api_bp.route('/wood-rates')
@login_required
def wood_rates():
    rates = WoodRate.query.all()
    return jsonify({r.wood_type: r.rate_per_sqft for r in rates})


@api_bp.route('/draft', methods=['POST'])
@login_required
def save_draft():
    """Auto-save a draft quotation including rooms/items. Creates on first call, updates thereafter."""
    from .projects import _save_project_data

    data = request.get_json(silent=True) or {}
    draft_id   = data.get('draft_id')
    customer_name = data.get('customer_name', '').strip() or 'Unnamed'
    mobile     = data.get('mobile', '').strip() or '—'
    email      = data.get('email', '').strip() or None
    rooms_data = data.get('rooms_data', [])

    project = None
    if draft_id:
        project = Project.query.get(int(draft_id))
        if not project or project.created_by != current_user.id or project.status != 'draft':
            project = None

    if project:
        project.customer_name = customer_name
        project.mobile        = mobile
        project.email         = email
        project.updated_at    = datetime.utcnow()
    else:
        project = Project(
            customer_name=customer_name,
            mobile=mobile,
            email=email,
            created_by=current_user.id,
            grand_total=0.0,
            status='draft'
        )
        db.session.add(project)
        db.session.flush()   # get project.id before saving rooms

    from . import plywood
    if plywood.table_ready() and 'plywood' in data:
        project.plywood = plywood.clean_choice(data.get('plywood'))
    # Save rooms/items (replaces any previously auto-saved rooms for this draft)
    if rooms_data:
        grand_total = _save_project_data(project, rooms_data, remember=False)
        project.grand_total = grand_total

    db.session.commit()
    return jsonify({'draft_id': project.id})
