"""Quotation numbers, in the business's own format (Settings → Quotation PDFs → Quotation numbers). By default
YYYYMMDD and that day's count (2026111801, 2026111802…); a firm can choose another, e.g. QT-{NNN} (QT-001, QT-002…),
QT/{FY}/{NNN} (QT/2026-27/001) or its own, from these parts:
  {YYYY} {YY} {MM} {DD}   the date the quotation was made (India time)
  {FY} {FY2}              the financial year, April–March: 2026-27 / 26-27
  {N} {NN} {NNN} {NNNN}   the count, with at least that many digits (one of these is needed)
The count starts again each day when the format has {DD}, each month with {MM}, each financial year with {FY}/{FY2},
each year with {YYYY}/{YY}, else it keeps running (from the "start from" number, e.g. to carry on a paper series).

Given once, when a saved quotation is first listed or opened (drafts have none), in the order they were made, and
kept: deleting one never renumbers the others. Changing the format (or start) renumbers them all in the new format.
Shown with its latest revision: 2026111801 (the original), 2026111801/Rev1 after the first change… Kept in app_settings (no database update):
  quote_numbers        JSON {project_id: number, '_format': 'format|start', '_last': {period: count}}
  quote_number_format  the format ('' = the default)
  quote_number_start   where a running count starts ('' = 1)
"""
import json
import re
from datetime import timedelta

KEY, FORMAT_KEY, START_KEY = 'quote_numbers', 'quote_number_format', 'quote_number_start'
ON_PDF_KEY = 'quote_number_on_pdf'                # '0': keep the number off the PDF (default: printed)
DEFAULT = '{YYYY}{MM}{DD}{NN}'
PRESETS = [(DEFAULT, 'Date + that day\'s count'), ('QT-{NNN}', 'Running number'),
           ('QT/{FY}/{NNN}', 'Financial year + count'), ('Q{YY}{MM}-{NNN}', 'Month + count')]
TOKEN = re.compile(r'\{(YYYY|YY|MM|DD|FY2|FY|N{1,6})\}')
LITERAL = re.compile(r'^[A-Za-z0-9 \-/_.#]*$')


def _load():
    from .models import AppSetting
    try:
        v = json.loads(AppSetting.get(KEY, '') or '{}')
    except ValueError:
        v = {}
    return v if isinstance(v, dict) else {}


def fmt():
    from .models import AppSetting
    return (AppSetting.get(FORMAT_KEY, '') or '').strip() or DEFAULT


def start():
    from .models import AppSetting
    raw = (AppSetting.get(START_KEY, '') or '').strip()
    return int(raw) if raw.isdigit() and int(raw) > 0 else 1


def check(pattern):
    """An error message for a format that won't do, else None."""
    pattern = (pattern or '').strip()
    if not pattern:
        return None
    if len(pattern) > 40:
        return 'Keep the quotation number format to 40 characters.'
    counters = [t for t in TOKEN.findall(pattern) if t.startswith('N')]
    if len(counters) != 1:
        return 'The quotation number format needs the count once: {N}, {NN}, {NNN} or {NNNN}.'
    if not LITERAL.match(TOKEN.sub('', pattern)):
        return ('Quotation numbers can have letters, digits, spaces and - / _ . # besides the parts in braces '
                '({YYYY} {YY} {MM} {DD} {FY} {FY2} {NNN}).')
    return None


def set_format(pattern, start_from=''):
    """Settings → Quotation PDFs. Returns an error message, or None (saved)."""
    from .models import AppSetting
    err = check(pattern)
    if err:
        return err
    raw = str(start_from or '').strip()
    if raw and (not raw.isdigit() or not 0 < int(raw) < 10 ** 7):
        return 'Start the count from a whole number, e.g. 1 or 245.'
    pattern = (pattern or '').strip()
    AppSetting.set(FORMAT_KEY, '' if pattern == DEFAULT else pattern)
    AppSetting.set(START_KEY, '' if raw in ('', '1') else str(int(raw)))
    return None


def _local(created_at):
    return created_at + timedelta(hours=5, minutes=30)


def _fy(d):
    y = d.year if d.month >= 4 else d.year - 1
    return f'{y}-{str(y + 1)[2:]}'


def resets(pattern):
    """When the count starts again: 'day', 'month', 'financial year', 'year' or None (keeps running)."""
    found = set(TOKEN.findall(pattern))
    return ('day' if 'DD' in found else 'month' if 'MM' in found else
            'financial year' if found & {'FY', 'FY2'} else 'year' if found & {'YYYY', 'YY'} else None)


def _period(pattern, d):
    every = resets(pattern)
    return {'day': d.strftime('%Y%m%d'), 'month': d.strftime('%Y%m'), 'financial year': _fy(d),
            'year': d.strftime('%Y')}.get(every, '')


def render(pattern, d, count):
    """The number for a quotation made on d (India time) with this count."""
    def part(m):
        t = m.group(1)
        if t.startswith('N'):
            return f'{count:0{len(t)}d}'
        return {'YYYY': d.strftime('%Y'), 'YY': d.strftime('%y'), 'MM': d.strftime('%m'), 'DD': d.strftime('%d'),
                'FY': _fy(d), 'FY2': _fy(d)[2:]}[t]
    return TOKEN.sub(part, pattern)


def known():
    """{project_id (int): number} as saved (no numbering; app_settings is fetched with the page's settings). After
    the format changed: none (numbered again by assign())."""
    nums = _load()
    pattern, first = fmt(), start()
    if nums.get('_format', f'{DEFAULT}|1') != f'{pattern}|{first}':
        return {}
    return {int(k): v for k, v in nums.items() if not k.startswith('_')}


def assign():
    """Number every saved quotation that has none yet (oldest first). Returns {project_id (int): number}."""
    from . import db
    from .models import AppSetting, Project
    nums = _load()
    pattern, first = fmt(), start()
    marker = f'{pattern}|{first}'
    changed = nums.get('_format') != marker
    if changed:
        old = {k: v for k, v in nums.items() if not k.startswith('_')}
        if '_format' not in nums and pattern == DEFAULT and first == 1:
            last = {}                                    # numbered before formats: kept as they are
            for n in old.values():
                day, seq = str(n)[:8], str(n)[8:]
                if seq.isdigit():
                    last[day] = max(last.get(day, 0), int(seq))
            nums = dict(old, _last=last)
        else:
            nums = {'_last': {}}                         # a new format: all numbered again, oldest first
        nums['_format'] = marker
    last = nums.setdefault('_last', {})
    rows = (Project.query.filter(Project.status != 'draft')
            .with_entities(Project.id, Project.created_at).order_by(Project.created_at, Project.id).all())
    missing = [r for r in rows if str(r.id) not in nums and r.created_at]
    for r in missing:
        d = _local(r.created_at)
        per = _period(pattern, d)
        count = max(last.get(per, 0), (first - 1) if per == '' else 0) + 1
        last[per] = count
        nums[str(r.id)] = render(pattern, d, count)
    if missing or changed:
        AppSetting.set(KEY, json.dumps(nums))
        db.session.commit()
    return {int(k): v for k, v in nums.items() if not k.startswith('_')}


def preview(pattern=None, first=None):
    """The first two numbers in this format, made today: e.g. ['QT-001', 'QT-002']."""
    from datetime import datetime
    pattern = (pattern or fmt()).strip() or DEFAULT
    first = first or start()
    d = _local(datetime.utcnow())
    n = first if resets(pattern) is None else 1
    return [render(pattern, d, n), render(pattern, d, n + 1)]


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
    """'2026111801' for the original (stored revision 1), '2026111801/Rev1' after the first change… ('' without a
    number)."""
    if not number:
        return ''
    shown = max((revision or 1) - 1, 0)
    return f'{number}/Rev{shown}' if shown else number


def labels(projects):
    """{project_id: '2026111801/Rev2'} for these quotations (drafts: none)."""
    nums = assign()
    revs = revisions([p.id for p in projects if p.status != 'draft'])
    return {p.id: label(nums.get(p.id), revs.get(p.id)) for p in projects if p.status != 'draft' and nums.get(p.id)}


def on_pdf():
    """Print the quotation's number (with its revision) on the PDF? On unless the business turned it off."""
    from .models import AppSetting
    return AppSetting.get(ON_PDF_KEY, '1') != '0'


def set_on_pdf(on):
    from .models import AppSetting
    AppSetting.set(ON_PDF_KEY, '1' if on else '0')


def for_pdf(project, revision=None):
    """'QT-016/Rev5' for this quotation's PDF (revision: an earlier one's number), '' for a draft or when it's off."""
    if project is None or getattr(project, 'status', '') == 'draft' or not getattr(project, 'id', None):
        return ''
    number = assign().get(project.id)
    if not number:
        return ''
    if revision is None:
        from .billing import latest_revision_number
        revision = latest_revision_number(project)
    return label(number, revision)
