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
interested, the latest note). Every note saved is also kept in the log (channel 'note'), so a trial's history has its
messages, calls and notes, newest first; a note isn't a message, so it doesn't count as being in touch.

Sales calls (console → Sales calls): every running trial with its contact details, how far it got, a talking point and
its history, for phoning them one after another. A call is logged with its outcome (OUTCOMES): interested marks it
hot, call back on a date snoozes it until then (it comes back as a call-back due), not interested marks it lost.
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
    'ALTER TABLE public.console_followups ALTER COLUMN note TYPE VARCHAR(500)',     # notes kept in the log too
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
        rows = conn.execute(text("SELECT DISTINCT ON (slug) slug, at, stage, channel FROM public.console_followups "
                                 "WHERE channel <> 'note' ORDER BY slug, at DESC")).all()
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
                     {'s': slug, 'st': stage, 'c': channel, 'n': (note or '')[:500] or None})


def add_note(slug, note, stage=''):
    """A note: kept in the trial's history and shown as its latest note on the lists."""
    note = (note or '').strip()[:500]
    if note:
        log(slug, stage, 'note', note)
        set_mark(slug, note=note)


def history(slug, limit=100):
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


def histories(slugs, limit=30):
    """{slug: [{'at', 'stage', 'channel', 'note'}, …]} newest first, for many trials in one query."""
    ensure_tables()
    out = {s: [] for s in slugs}
    if not out:
        return out
    with db.engine.connect() as conn:
        for r in conn.execute(text('SELECT slug, at, stage, channel, note FROM public.console_followups '
                                   'ORDER BY at DESC')).mappings():
            if r['slug'] in out and len(out[r['slug']]) < limit:
                out[r['slug']].append(dict(r))
    return out


# outcome key: (label, what it does)
OUTCOMES = {'interested': 'Interested', 'callback': 'Call back', 'no_answer': 'No answer',
            'not_interested': 'Not interested'}


def log_call(slug, outcome, note='', callback_on=None, stage=''):
    """A phone call and how it went. Interested → hot; call back → snoozed to that date (a call-back due then);
    not interested → lost. The note joins the history with the call (and is the trial's latest note)."""
    if outcome not in OUTCOMES:
        raise ValueError('Choose how the call went.')
    note = (note or '').strip()[:500]
    from . import plan as plan_mod
    if outcome == 'callback':
        callback_on = callback_on or plan_mod.today() + timedelta(days=2)
        if callback_on <= plan_mod.today():
            raise ValueError('Choose a call-back date after today.')
    label = OUTCOMES[outcome] + (f" on {callback_on.strftime('%d %b')}" if outcome == 'callback' else '')
    log(slug, stage, 'call', label + (f': {note}' if note else ''))
    fields = {}
    if note:
        fields['note'] = note
    if outcome == 'interested':
        fields['mark'] = 'hot'
    elif outcome == 'not_interested':
        fields['mark'] = 'lost'
    elif outcome == 'callback':
        fields['snooze_until'] = callback_on
    if fields:
        set_mark(slug, **fields)


def talking_point(row):
    """What to talk about on the call, from what the app can see of the trial."""
    u, st, stage = row.get('usage') or {}, row.get('status_obj'), row.get('stage')
    q = u.get('quotations') or 0
    if stage == 'ended':
        return 'Trial ended. Ask what stopped them, and offer a plan (₹4,999 for 6 months, ₹8,999 for 12).'
    if stage == 'signin':
        return 'Never signed in. Check they got the login link, and offer to set it up together on the call.'
    if stage == 'details':
        return 'Signed in, nothing set up. Offer to add their company details and logo for them (ask them to WhatsApp the logo).'
    if stage == 'firstquote':
        return ('Set up, no quotation yet. Offer to set up their items and rates from an old quotation they have '
                'sent: they can upload it, or WhatsApp it to you.')
    if stage == 'ending':
        days = st.days_left if st else 0
        when = 'today' if days <= 0 else 'tomorrow' if days == 1 else f'in {days} days'
        return (f'Trial ends {when} with {q} quotation{"s" if q != 1 else ""}. Ask how it went, then the plans and '
                'the payment link.')
    seen = u.get('last_seen_at')
    quiet = seen and (datetime.utcnow() - seen.replace(tzinfo=None)).days
    if quiet and quiet >= QUIET_DAYS:
        return (f'Made {q} quotation{"s" if q != 1 else ""}, quiet for {quiet} days. Ask what got in the way, and '
                'if anything is missing.')
    return f'Using it: {q} quotation{"s" if q != 1 else ""}. Ask what they like, what is missing, and if they have questions.'


def call_list(board_rows, now=None):
    """The board's rows for Sales calls: each with its history, calls made, call-back date and talking point, and
    {'rows', 'counts'}. To call: not lost, not waiting for a call-back date, not called in the last 2 days."""
    from . import plan as plan_mod
    now = now or datetime.utcnow()
    today = plan_mod.today()
    hist = histories([r['slug'] for r in board_rows])
    counts = {'to_call': 0, 'callbacks': 0, 'never': 0, 'week': 0, 'hot': 0}
    for r in board_rows:
        h = r['history'] = hist.get(r['slug'], [])
        calls = [x for x in h if x['channel'] == 'call']
        r['last_call'] = calls[0] if calls else None
        r['calls'] = len(calls)
        snooze = (r.get('mark') or {}).get('snooze_until')
        r['callback_due'] = bool(snooze and snooze <= today and calls and calls[0]['note']
                                 and calls[0]['note'].startswith('Call back'))
        r['waiting'] = bool(snooze and snooze > today)
        recent = calls and (now - calls[0]['at']).total_seconds() < 2 * 86400
        lost = (r.get('mark') or {}).get('mark') == 'lost'
        r['to_call'] = not lost and not r['waiting'] and (r['callback_due'] or not recent)
        r['talk'] = talking_point(r)
        counts['to_call'] += r['to_call']
        counts['callbacks'] += r['callback_due']
        counts['never'] += not calls and not lost
        counts['week'] += bool(calls and (now - calls[0]['at']).days < 7)
        counts['hot'] += (r.get('mark') or {}).get('mark') == 'hot'
    # call-backs due first, then hot, then the board's own order (ending soon before the early stages)
    order = {r['slug']: i for i, r in enumerate(board_rows)}
    rows = sorted(board_rows, key=lambda r: (not r['to_call'], not r['callback_due'],
                                             (r.get('mark') or {}).get('mark') != 'hot', order[r['slug']]))
    return {'rows': rows, 'counts': counts}


def snooze(slug, days):
    from . import plan as plan_mod
    set_mark(slug, snooze_until=plan_mod.today() + timedelta(days=days))


# ── Emails by stage (daily task) ─────────────────────────────────────────────

EMAILS = {   # stage → (days since the trial started, subject, body); the texts used: console → Messages (app/texts.py)
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
            from . import emails, texts
            subject, body = texts.render(f'stage_{stage}', hello=f'Hello {name}' if name else 'Hello', url=t['url'])
            emails.send(email, subject, body, kind='stage', slug=t['slug'], bcc=False)
            log(t['slug'], stage, 'email', subject)
            out[t['slug']] = stage
        except Exception as exc:                        # one trial's problem mustn't stop the others
            out[t['slug']] = f'failed: {exc}'
    return out
