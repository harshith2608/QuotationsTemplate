"""Quotation numbers: YYYYMMDD and that day's count (2026111801, 2026111802…), from the date the quotation was made
(India time). Given once, when a saved quotation is first listed or opened (drafts have none), in the order they were
made, and kept: deleting one never renumbers the others. Shown with its latest revision: 2026111801/Rev2 (Rev1 until
a second revision is saved). Kept in app_settings (no database update): quote_numbers = {project_id: number}.
"""
import json
from datetime import timedelta

KEY = 'quote_numbers'


def _load():
    from .models import AppSetting
    try:
        v = json.loads(AppSetting.get(KEY, '') or '{}')
    except ValueError:
        v = {}
    return v if isinstance(v, dict) else {}


def _day(created_at):
    return (created_at + timedelta(hours=5, minutes=30)).strftime('%Y%m%d')


def known():
    """{project_id (int): number} as saved (no numbering; app_settings is fetched with the page's settings)."""
    return {int(k): v for k, v in _load().items()}


def assign():
    """Number every saved quotation that has none yet (oldest first). Returns {project_id (int): number}."""
    from . import db
    from .models import AppSetting, Project
    nums = _load()
    rows = (Project.query.filter(Project.status != 'draft')
            .with_entities(Project.id, Project.created_at).order_by(Project.created_at, Project.id).all())
    missing = [r for r in rows if str(r.id) not in nums and r.created_at]
    if missing:
        last = {}                                        # day → highest count given
        for n in nums.values():
            day, seq = str(n)[:8], str(n)[8:]
            if seq.isdigit():
                last[day] = max(last.get(day, 0), int(seq))
        for r in missing:
            day = _day(r.created_at)
            last[day] = last.get(day, 0) + 1
            nums[str(r.id)] = f'{day}{last[day]:02d}'
        AppSetting.set(KEY, json.dumps(nums))
        db.session.commit()
    return {int(k): v for k, v in nums.items()}


def revisions(project_ids):
    """{project_id: latest revision number} (one query; none yet: left out)."""
    from . import billing, db
    from .models import QuoteRevision
    if not project_ids or not billing.ready():
        return {}
    rows = (db.session.query(QuoteRevision.project_id, db.func.max(QuoteRevision.number))
            .filter(QuoteRevision.project_id.in_(project_ids)).group_by(QuoteRevision.project_id).all())
    return {pid: n for pid, n in rows}


def label(number, revision):
    """'2026111801/Rev2' ('' without a number)."""
    return f'{number}/Rev{max(revision or 1, 1)}' if number else ''


def labels(projects):
    """{project_id: '2026111801/Rev2'} for these quotations (drafts: none)."""
    nums = assign()
    revs = revisions([p.id for p in projects if p.status != 'draft'])
    return {p.id: label(nums.get(p.id), revs.get(p.id)) for p in projects if p.status != 'draft' and nums.get(p.id)}
