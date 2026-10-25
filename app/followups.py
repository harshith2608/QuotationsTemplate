"""Following up trials (console → Follow-ups): where each trial is, who to message today, and what to say.

Every running trial gets a stage, worked out from its own data (activity.usage and its plan):
    signin      not signed in yet
    details     signed in, company details not saved (and no quotation yet)
    firstquote  set up, no quotation yet
    quoting     making quotations (whatever else is done)
    ending      2 days or less left
    ended       trial over (read-only, data kept until the deletion date)
A trial is due for a message when it hasn't been messaged for a couple of days (a quoting one only when it has gone quiet),
isn't snoozed and isn't marked not interested. The operator sends from their own WhatsApp (wa.me), one after another
(the queue); each one sent is logged. The daily task also emails the early stages once each (send_stage_emails).
Kept in the console's database: public.console_followups (the log) and public.console_trial_marks (snooze, hot, not
interested, a note).
"""
from datetime import datetime, timedelta

from sqlalchemy import text

from . import db

DDL = [
    """CREATE TABLE IF NOT EXISTS public.console_followups (
        id      SERIAL PRIMARY KEY,
        slug    VARCHAR(40) NOT NULL,
        at      TIMESTAMP NOT NULL DEFAULT (now() AT TIME ZONE 'utc'),
        stage   VARCHAR(20),
        channel VARCHAR(10) NOT NULL DEFAULT 'whatsapp',
        note    VARCHAR(300))""",
    'CREATE INDEX IF NOT EXISTS console_followups_slug ON public.console_followups (slug, at)',
    """CREATE TABLE IF NOT EXISTS public.console_trial_marks (
        slug         VARCHAR(40) PRIMARY KEY,
        snooze_until DATE,
        mark         VARCHAR(20),                 -- 'hot' / 'lost' (not interested) / ''
        note         VARCHAR(500),
        updated_at   TIMESTAMP NOT NULL DEFAULT (now() AT TIME ZONE 'utc'))""",
]

# key: (label, what to do next, follow-up draft key, days between messages)
STAGES = {
    'signin':     ('Not signed in', 'Check they got the login', 'signin', 2),
    'details':    ('No company details', 'Company details and logo', 'details', 2),
    'firstquote': ('No quotation yet', 'Their first quotation', 'firstquote', 2),
    'quoting':    ('Quoting', 'Check in when they go quiet', 'checkin', 4),
    'ending':     ('Ending soon', 'Plans and payment link', 'ending', 1),
    'ended':      ('Ended', 'Continue, or what was missing', 'ended', 4),
}
ORDER = list(STAGES)
QUIET_DAYS = 3                  # a quoting trial is due once it hasn't been used for this long
ENDED_DAYS = 10                 # an ended trial stays on the list this long after its end date

_ready = False


def ensure_tables():
    global _ready
    if not _ready:
        with db.engine.begin() as conn:
            for ddl in DDL:
                conn.execute(text(ddl))
        _ready = True


def stage_of(t):
    """The trial's stage key, or None (not running / no data)."""
    st, u = t.get('status_obj'), t.get('usage')
    if t.get('status') != 'active' or st is None or u is None:
        return None
    if st.has_limit and st.days_left is not None:
        if st.days_left < 0:
            return 'ended'
        if st.days_left <= 2:
            return 'ending'
    if not u.get('last_login_at') and not u.get('used'):
        return 'signin'
    if u.get('quotations'):
        return 'quoting'                          # already quoting: company details can wait
    if not u.get('company_set'):
        return 'details'
    return 'firstquote'


def last_contacts(slugs=None):
    """{slug: (at, stage, channel)} for the latest follow-up of each trial."""
    ensure_tables()
    with db.engine.connect() as conn:
        rows = conn.execute(text('SELECT DISTINCT ON (slug) slug, at, stage, channel FROM public.console_followups '
                                 'ORDER BY slug, at DESC')).all()
    return {r[0]: (r[1], r[2], r[3]) for r in rows if slugs is None or r[0] in slugs}


def marks():
    """{slug: {'snooze_until', 'mark', 'note'}}"""
    ensure_tables()
    with db.engine.connect() as conn:
        return {r[0]: {'snooze_until': r[1], 'mark': r[2] or '', 'note': r[3] or ''}
                for r in conn.execute(text('SELECT slug, snooze_until, mark, note FROM public.console_trial_marks'))}


def is_due(t, stage, last, mark, now=None):
    """Due for a message today?"""
    now = now or datetime.utcnow()
    if stage is None or (mark or {}).get('mark') == 'lost':
        return False
    snooze = (mark or {}).get('snooze_until')
    if snooze and snooze > now.date():
        return False
    gap = STAGES[stage][3]
    if last and (now - last[0]).total_seconds() < gap * 86400 - 3600 and last[1] == stage:
        return False                              # messaged about this stage recently
    if last and (now - last[0]).total_seconds() < 20 * 3600:
        return False                              # never twice in a day, whatever the stage
    if stage == 'quoting':
        seen = (t.get('usage') or {}).get('last_seen_at')
        return bool(seen) and (now - seen.replace(tzinfo=None)).days >= QUIET_DAYS
    if stage == 'ended':
        st = t['status_obj']
        return -st.days_left <= ENDED_DAYS
    return True


def board(trials, contacts):
    """Trials with stage, due, last contact and marks: {'rows': [...], 'counts': {stage: n}, 'due': [...]}.
    contacts: {slug: {'name', 'phone', 'company'}} (console.trial_contacts)."""
    last, mk = last_contacts(), marks()
    rows, counts = [], {k: 0 for k in ORDER}
    now = datetime.utcnow()
    for t in trials:
        stage = stage_of(t)
        if stage is None:
            continue
        counts[stage] += 1
        m = mk.get(t['slug'], {})
        rows.append(dict(t, stage=stage, stage_label=STAGES[stage][0], next_step=STAGES[stage][1],
                         draft_key=STAGES[stage][2], last=last.get(t['slug']), mark=m,
                         contact=contacts.get(t['slug'], {}), due=is_due(t, stage, last.get(t['slug']), m, now)))
    rank = {k: i for i, k in enumerate(ORDER)}
    # due first: hot ones, then the most urgent stages (ending before the early ones), then the oldest trials
    urgency = {'ending': 0, 'ended': 1, 'signin': 2, 'details': 3, 'firstquote': 4, 'quoting': 5}
    rows.sort(key=lambda r: (not r['due'], r['mark'].get('mark') != 'hot', urgency[r['stage']], r.get('created_at') or now))
    lost = sum(1 for r in rows if r['mark'].get('mark') == 'lost')
    return {'rows': rows, 'counts': counts, 'due': [r for r in rows if r['due']], 'lost': lost, 'rank': rank}


def log(slug, stage, channel='whatsapp', note=''):
    ensure_tables()
    with db.engine.begin() as conn:
        conn.execute(text('INSERT INTO public.console_followups (slug, stage, channel, note) VALUES (:s, :st, :c, :n)'),
                     {'s': slug, 'st': stage, 'c': channel, 'n': (note or '')[:300] or None})


def history(slug, limit=20):
    ensure_tables()
    with db.engine.connect() as conn:
        return [dict(r) for r in conn.execute(text(
            'SELECT at, stage, channel, note FROM public.console_followups WHERE slug = :s ORDER BY at DESC LIMIT :l'),
            {'s': slug, 'l': limit}).mappings()]


def set_mark(slug, **fields):
    """snooze_until (date or None), mark ('hot' / 'lost' / ''), note."""
    ensure_tables()
    cur = marks().get(slug, {'snooze_until': None, 'mark': '', 'note': ''})
    cur.update({k: v for k, v in fields.items() if k in ('snooze_until', 'mark', 'note')})
    with db.engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO public.console_trial_marks (slug, snooze_until, mark, note, updated_at) VALUES (:s, :z, :m, :n, "
            "(now() AT TIME ZONE 'utc')) ON CONFLICT (slug) DO UPDATE SET snooze_until = :z, mark = :m, note = :n, "
            "updated_at = (now() AT TIME ZONE 'utc')"),
            {'s': slug, 'z': cur['snooze_until'], 'm': (cur['mark'] or '')[:20], 'n': (cur['note'] or '')[:500]})


def snooze(slug, days):
    from . import plan as plan_mod
    set_mark(slug, snooze_until=plan_mod.today() + timedelta(days=days))


# ── Emails by stage (daily task) ─────────────────────────────────────────────

EMAILS = {   # stage → (days since the trial started, subject, body)
    'signin': (1, 'Your QuoteRoom app is ready',
               'Your QuoteRoom app is ready and waiting for you:\n{url}\n\nSign in with the username and password you '
               'chose (or the ones we sent you). Setting up takes about 10 minutes: your company details and logo, '
               'then your first quotation.'),
    'details': (1, 'Add your company details to QuoteRoom',
                'Good to see you\'ve signed in to QuoteRoom!\n\nNext: add your company name, address and logo in '
                'Settings, so every quotation goes out in your own brand. It takes 2 minutes:\n{url}/admin/settings\n\n'
                'You can also reply with your logo and we\'ll add it for you.'),
    'firstquote': (2, 'Make your first quotation in QuoteRoom',
                   'Your QuoteRoom app is set up. Now try your first quotation: New Quotation, pick a starting '
                   'quotation, type the sizes, and send the PDF to your customer on WhatsApp.\n{url}/projects/new\n\n'
                   'Have old quotations? Reply with one and we\'ll set up your items and rates for you.'),
}


def send_stage_emails(trials):
    """Daily (console tick): one email per trial per early stage, once its trial is a day or two old. Uses the
    plan reminders log (public.plan_reminders) so each goes once. Returns {slug: stage}."""
    from . import mailer, tenancy
    from . import subscription
    from .models import AppSetting
    if not mailer.enabled():
        return {}
    subscription.ensure_table()
    out = {}
    now = datetime.utcnow()
    for t in trials:
        stage = stage_of(t)
        if stage not in EMAILS:
            continue
        min_days, subject, body = EMAILS[stage]
        started = t.get('created_at')
        if not started or (now - started).days < min_days:
            continue
        try:
            with tenancy.tenant_context(t['slug'], t['schema_name']):
                email = AppSetting.get('company_email', '') or ''
            if '@' not in email:
                continue
            with db.engine.begin() as conn:
                fresh = conn.execute(text('INSERT INTO public.plan_reminders (slug, kind, ends_on) VALUES (:s, :k, :e) '
                                          'ON CONFLICT DO NOTHING RETURNING slug'),
                                     {'s': t['slug'], 'k': f'stage_{stage}', 'e': t['status_obj'].ends_on}).first()
            if not fresh:
                continue
            name = (t.get('contact') or {}).get('name', '').split(' ')[0]
            mailer.send(email, subject, f"Hello{(' ' + name) if name else ''},\n\n" + body.format(url=t['url'])
                        + '\n\nQuestions? Just reply to this email or message us on WhatsApp.\n\nQuoteRoom\n')
            log(t['slug'], stage, 'email', subject)
            out[t['slug']] = stage
        except Exception as exc:                        # one trial's problem mustn't stop the others
            out[t['slug']] = f'failed: {exc}'
    return out
