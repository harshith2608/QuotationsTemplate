"""
Business reports for admins: by Indian financial year (April–March), all time, and a projection.

- Quotations made: by the date they were created.
- Won: quotations that reached Confirmed (or later) and weren't cancelled, by the date they were confirmed.
- Invoiced / GST: issued invoices by invoice date. Collected: payments by the date recorded.
- Estimated profit: won quotations priced with today's costs (Admin → Costs & profit).
Amounts are encrypted in the database, so everything is added up here in Python.
"""
from datetime import date, datetime, timedelta

from . import billing, db

WON = ('confirmed', 'ongoing', 'completed', 'on_hold')
IST = timedelta(hours=5, minutes=30)


def _day(dt):
    return (dt + IST).date() if isinstance(dt, datetime) else dt


def fy_bounds(fy):
    start = int(fy[:4])
    return date(start, 4, 1), date(start + 1, 3, 31)


def _blank():
    return {'made': 0, 'made_value': 0.0, 'won': 0, 'won_value': 0.0, 'invoiced': 0.0, 'gst': 0.0,
            'collected': 0.0, 'profit': 0.0, 'cost': 0.0, 'revenue': 0.0, 'profit_jobs': 0, 'missing_costs': 0}


def build(today=None):
    from sqlalchemy.orm import undefer
    from . import plywood
    from .models import Invoice, Item, Payment, Project, ProjectStageChange, Room
    today = today or (datetime.utcnow() + IST).date()
    current_fy = billing.financial_year(today)
    ply = plywood.table_ready()        # plywood columns: with the rows, not one query per item / quotation
    q = Project.query.filter(Project.status != 'draft')
    projects = (q.options(undefer(Project.plywood)) if ply else q).all()
    ids = [p.id for p in projects]

    # Rooms and items for every quotation in two queries (for profit)
    rooms_by_project = {}
    if ids:
        rooms = Room.query.filter(Room.project_id.in_(ids)).order_by(Room.id).all()
        items_by_room = {}
        iq = Item.query.filter(Item.room_id.in_([r.id for r in rooms])).order_by(Item.id)
        for it in (iq.options(undefer(Item.plywood)) if ply else iq):
            items_by_room.setdefault(it.room_id, []).append(it)
        for r in rooms:
            r.item_list = items_by_room.get(r.id, [])
            rooms_by_project.setdefault(r.project_id, []).append(r)

    won_at = {}
    for ch in ProjectStageChange.query.filter(ProjectStageChange.to_stage.in_(WON)).order_by(ProjectStageChange.changed_at):
        won_at.setdefault(ch.project_id, ch.changed_at)

    years, months = {}, {}
    total = _blank()
    costs = billing.cost_rates()
    has_costs = bool(costs)
    settings = billing.invoice_settings()
    gst_registered = bool(billing.business_state_code())
    issued = Invoice.query.filter_by(status='issued').all() if billing.ready() else []
    active = {}
    for inv in issued:                       # the latest issued invoice of each quotation
        if inv.project_id not in active or inv.created_at > active[inv.project_id].created_at:
            active[inv.project_id] = inv
    pending_value, pending_count = 0.0, 0

    def bucket(day):
        fy = billing.financial_year(day)
        return years.setdefault(fy, _blank()), fy

    for p in projects:
        made = _day(p.created_at)
        y, _ = bucket(made)
        for b in (y, total):
            b['made'] += 1
            b['made_value'] += p.final_total
        if p.stage == 'pending':
            pending_value += p.final_total
            pending_count += 1
        if p.stage in WON:
            when = _day(won_at.get(p.id, p.created_at))
            y, fy = bucket(when)
            pr = billing.profit(p, rooms_by_project.get(p.id, []), invoice=active.get(p.id), costs=costs,
                                settings=settings, gst_registered=gst_registered) if has_costs else None
            targets = [y, total]
            if fy == current_fy:
                targets.append(months.setdefault((when.year, when.month), _blank()))
            for b in targets:
                b['won'] += 1
                b['won_value'] += p.final_total
                if pr:
                    b['profit'] += pr['profit']
                    b['cost'] += pr['cost']
                    b['revenue'] += pr['selling']
                    b['profit_jobs'] += 1
                    b['missing_costs'] += 1 if pr['missing'] else 0

    if billing.ready():
        for inv in issued:
            data = billing.invoice_data(inv)
            gst = sum(t['amount'] for t in data.get('taxes', []))
            y, fy = bucket(inv.issued_on)
            targets = [y, total] + ([months.setdefault((inv.issued_on.year, inv.issued_on.month), _blank())]
                                    if fy == current_fy else [])
            for b in targets:
                b['invoiced'] += inv.total
                b['gst'] += gst
    paid = {}
    for pay in Payment.query.filter(Payment.project_id.in_(ids)) if ids else []:
        paid[pay.project_id] = paid.get(pay.project_id, 0) + pay.amount
        when = _day(pay.recorded_at)
        y, fy = bucket(when)
        targets = [y, total] + ([months.setdefault((when.year, when.month), _blank())] if fy == current_fy else [])
        for b in targets:
            b['collected'] += pay.amount

    for b in list(years.values()) + list(months.values()) + [total]:
        decided = b['made']
        b['conversion'] = round(b['won'] / decided * 100, 1) if decided else 0.0
        b['margin'] = round(b['profit'] / b['revenue'] * 100, 1) if b['profit_jobs'] and b['revenue'] else None
        for k in ('made_value', 'won_value', 'invoiced', 'gst', 'collected', 'profit', 'cost', 'revenue'):
            b[k] = round(b[k], 2)

    # Current financial year: months April → March, and a projection to 31 March
    start, end = fy_bounds(current_fy)
    month_rows = []
    d = start
    while d <= end:
        m = months.get((d.year, d.month), _blank())
        month_rows.append({'label': d.strftime('%b %Y'), 'future': d > today, **m})
        d = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    cur = years.get(current_fy, _blank())
    for k in ('conversion', 'margin'):
        cur.setdefault(k, None)
    elapsed = (today - start).days + 1
    length = (end - start).days + 1
    factor = length / elapsed if elapsed > 0 else 1
    last12 = [p for p in projects if _day(p.created_at) > today - timedelta(days=365)]
    win_rate = (sum(1 for p in last12 if p.stage in WON) / len(last12)) if last12 else 0
    projection = {
        'days_elapsed': elapsed, 'days_in_year': length,
        'won_value': round(cur['won_value'] * factor, 2),
        'collected': round(cur['collected'] * factor, 2),
        'profit': round(cur['profit'] * factor, 2) if cur['profit_jobs'] else None,
        'pipeline_value': round(pending_value, 2), 'pipeline_count': pending_count,
        'win_rate': round(win_rate * 100, 1),
        'pipeline_expected': round(pending_value * win_rate, 2),
    }
    # Still to collect: the same rule as billing.balances_due, from the rows already loaded here
    outstanding = 0.0
    for p in projects:
        inv = active.get(p.id)
        if p.stage in billing.DUE_STAGES or inv:
            outstanding += round(max((round(inv.total, 2) if inv else p.total_payable) - paid.get(p.id, 0), 0), 2)
    max_month = max([m['won_value'] for m in month_rows] + [m['collected'] for m in month_rows] + [1])
    return {
        'today': today, 'current_fy': current_fy, 'current': cur, 'months': month_rows, 'max_month': max_month,
        'years': sorted(years.items(), reverse=True), 'total': total, 'projection': projection,
        'outstanding': round(outstanding, 2), 'has_costs': has_costs,
    }

