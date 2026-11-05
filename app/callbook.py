"""A free 10-minute set-up call (on WhatsApp), booked by a trial business from inside its app (or a WhatsApp chat with
us instead).

Shown to a trial's admins in the shared app: at the end of the guided setup and as a card on the quotations. They
pick a free slot; it goes on the console's Schedule (followups.book, in the trials database the shared app runs on),
the trial is marked hot, and we get an email (when email is set up). Our hours are set in the console (Features →
Call bookings): one line per weekday of India-time ranges, e.g. "09:00-10:15, 12:00-20:00"; empty = not that day.
"""
import json
import re
from datetime import datetime, timedelta


SWITCH_KEY = 'call_hours'           # console_state: JSON {"0": "09:00-10:15, 12:00-20:00", … "6": ""} (Monday = 0)
BOOKED_KEY = 'help_call'            # app_settings (the business): JSON {"at": UTC ISO, "id": appointment id}
DAYS = ('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday')
# Our hours until set in the console: weekdays not 10:15–12:00 (and Wednesday and Thursday not 9:00–18:30: office);
# the weekend all day
DEFAULT_HOURS = {0: '09:00-10:15, 12:00-20:00', 1: '09:00-10:15, 12:00-20:00', 2: '18:30-20:00',
                 3: '18:30-20:00', 4: '09:00-10:15, 12:00-20:00', 5: '09:00-20:00', 6: '09:00-20:00'}
# Times blocked in the console (a day off, a meeting): JSON [{"date": "2026-11-09", "start": "14:00", "end": "16:00",
# "note": "…"}] in console_state; no start = the whole day. Past ones are dropped when the list is saved.
BLOCKS_KEY = 'call_blocks'
SLOT_MINUTES = 30                   # a 10-minute call, with time around it
LEAD_MINUTES = 60                   # the soonest bookable: an hour from now
AHEAD_DAYS = 7
IST = timedelta(hours=5, minutes=30)
RANGE_RE = re.compile(r'^\s*(\d{1,2})[:.](\d{2})\s*[-–]\s*(\d{1,2})[:.](\d{2})\s*$')


def parse_ranges(text):
    """'09:00-10:15, 12:00-20:00' → [(540, 615), (720, 1200)] (minutes of the day). Raises ValueError."""
    out = []
    for part in (text or '').split(','):
        if not part.strip():
            continue
        m = RANGE_RE.match(part)
        if not m:
            raise ValueError(f'"{part.strip()}" isn\'t a time range like 09:00-10:15.')
        h1, m1, h2, m2 = map(int, m.groups())
        start, end = h1 * 60 + m1, h2 * 60 + m2
        if not (0 <= start < end <= 24 * 60) or m1 > 59 or m2 > 59:
            raise ValueError(f'"{part.strip()}": the start must be before the end, within the day.')
        out.append((start, end))
    return sorted(out)


def hours():
    """{weekday: 'ranges text'}: the console's, else DEFAULT_HOURS."""
    raw = _console_raw(SWITCH_KEY)
    try:
        found = json.loads(raw) if raw else None
    except ValueError:
        found = None
    if not isinstance(found, dict):
        return dict(DEFAULT_HOURS)
    return {d: str(found.get(str(d), '')) for d in range(7)}


def _console_raw(key):
    from . import platform_switch, tenancy
    try:
        return platform_switch.value(key) if tenancy.tenant_mode() else platform_switch.console_value(key, raw=True)
    except Exception:
        return None


def blocks():
    """The blocked times, soonest first: [{'date', 'start', 'end', 'note'}] (start '' = the whole day)."""
    try:
        found = json.loads(_console_raw(BLOCKS_KEY) or '[]')
    except ValueError:
        found = []
    out = [b for b in found if isinstance(b, dict) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', str(b.get('date', '')))]
    return sorted(out, key=lambda b: (b['date'], b.get('start') or ''))


def new_block(date_text, start, end, note, now=None):
    """A block from the console's form, checked: {'date', 'start', 'end', 'note'}. Raises ValueError."""
    try:
        day = datetime.strptime((date_text or '').strip(), '%Y-%m-%d').date()
    except ValueError:
        raise ValueError('Choose the day to block.')
    if day < ((now or datetime.utcnow()) + IST).date():
        raise ValueError('That day has passed.')
    start, end = (start or '').strip(), (end or '').strip()
    if start or end:
        parse_ranges(f'{start}-{end}')                         # raises with a plain message
    return {'date': day.isoformat(), 'start': start, 'end': end, 'note': ' '.join((note or '').split())[:80]}


def _blocked(at, day_blocks):
    """A slot starting at `at` (India time) runs into one of the day's blocks."""
    t = at.hour * 60 + at.minute
    for b in day_blocks:
        if not b.get('start'):
            return True
        (start, end), = parse_ranges(f"{b['start']}-{b['end']}")
        if t < end and t + SLOT_MINUTES > start:
            return True
    return False


def _booked_times():
    """UTC times already booked on the console's Schedule (any trial)."""
    from . import followups
    return [a['at'] for a in followups.appointments(days=AHEAD_DAYS + 1)]


def slots(now=None, taken=None, blocked=None):
    """[(day label, [(value 'YYYY-MM-DDTHH:MM' IST, '5:00 PM')])] for the next AHEAD_DAYS days, free ones only: in our
    hours, not blocked, not booked."""
    now = now or datetime.utcnow()
    taken = _booked_times() if taken is None else taken
    blocked = blocks() if blocked is None else blocked
    soonest = now + IST + timedelta(minutes=LEAD_MINUTES)
    table = hours()
    out = []
    for n in range(AHEAD_DAYS + 1):
        day = (now + IST).date() + timedelta(days=n)
        try:
            ranges = parse_ranges(table.get(day.weekday(), ''))
        except ValueError:
            ranges = []
        free = []
        day_blocks = [b for b in blocked if b['date'] == day.isoformat()]
        for start, end in ranges:
            t = -(-start // SLOT_MINUTES) * SLOT_MINUTES          # on the hour or half hour
            while t + SLOT_MINUTES <= end:
                at = datetime(day.year, day.month, day.day) + timedelta(minutes=t)
                utc = at - IST
                if at >= soonest and not _blocked(at, day_blocks) and \
                        all(abs((utc - b).total_seconds()) >= SLOT_MINUTES * 60 for b in taken):
                    free.append((at.strftime('%Y-%m-%dT%H:%M'), at.strftime('%-I:%M %p')))
                t += SLOT_MINUTES
        if free:
            label = 'Today' if n == 0 else 'Tomorrow' if n == 1 else day.strftime('%A %-d %b')
            out.append((label, free))
    return out


def available():
    """Shown to this business: a trial in the shared app (the Schedule is in its database), not the demo."""
    from . import tenancy
    from .demo import demo_enabled
    from .plan import load_status
    if not tenancy.tenant_mode() or demo_enabled():
        return False
    try:
        return load_status().is_trial
    except Exception:
        return False


def booked():
    """This business's call still to come: {'at': UTC datetime, 'when': 'Tue 4 Nov, 5:00 PM'} or None."""
    from . import followups
    from .models import AppSetting
    try:
        found = json.loads(AppSetting.get(BOOKED_KEY) or 'null')
        at = datetime.fromisoformat(found['at'])
    except (ValueError, TypeError, KeyError):
        return None
    if at < datetime.utcnow() - timedelta(minutes=30):
        return None
    return {'at': at, 'when': followups.when_text(at)}


def book(value, phone, note, user_name):
    """Book the slot ('YYYY-MM-DDTHH:MM' India time) if it's still free. Returns the booked() dict. Raises ValueError."""
    from . import branding, followups, mailer, tenancy
    from .models import AppSetting
    from . import db
    if value not in {v for _, free in slots() for v, _ in free}:
        raise ValueError('That time was just taken or has passed. Please choose another.')
    digits = re.sub(r'\D', '', phone or '')
    if not 10 <= len(digits) <= 13:
        raise ValueError('Type your WhatsApp number, e.g. 98765 43210.')
    at_ist = datetime.strptime(value, '%Y-%m-%dT%H:%M')
    slug = tenancy.current_slug()
    brand = branding.get_brand()
    note = ' '.join((note or '').split())[:300]
    text = (f'Set-up call booked in the app by {user_name or "their admin"}, WhatsApp {phone.strip()}'
            + (f'. {note}' if note else ''))
    aid = followups.book(slug, at_ist, mode='call', note=text)
    at = at_ist - IST
    AppSetting.set(BOOKED_KEY, json.dumps({'at': at.isoformat(), 'id': aid}))
    db.session.commit()
    if mailer.enabled():                            # so we see it straight away
        when = followups.when_text(at)
        mailer.send(mailer.operator(), f'Call booked: {brand["name"]}, {when}',
                    f'{brand["name"]} ({slug}) booked a free set-up call.\n\n'
                    f'When: {when} (India time)\nWhatsApp: {phone.strip()}\nBooked by: {user_name or "their admin"}\n'
                    + (f'Note: {note}\n' if note else '') + '\nIt\'s on the console\'s Schedule.\n')
    return booked()


def whatsapp_url():
    """A WhatsApp chat with us, the message already saying who they are. '' when SUPPORT_WHATSAPP isn't set."""
    from urllib.parse import quote
    from flask import has_request_context, request
    from . import branding
    _, url = branding.support_contact()
    if not url:
        return ''
    name = branding.get_brand()['name']
    host = request.host if has_request_context() else ''
    return url + '?text=' + quote(f'Hi! This is {name}' + (f' ({host})' if host else '') +
                                  '. Can you help me set up my rates in QuoteRoom?')
