"""A free 10-minute set-up call, booked by a trial business from inside its app (or a WhatsApp chat with us instead).

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
# Our hours until set in the console: weekdays not 10:15–12:00 (and Wednesday and Thursday not 9:00–18:30: office)
DEFAULT_HOURS = {0: '09:00-10:15, 12:00-20:00', 1: '09:00-10:15, 12:00-20:00', 2: '18:30-20:00',
                 3: '18:30-20:00', 4: '09:00-10:15, 12:00-20:00', 5: '09:00-20:00', 6: ''}
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
    from . import platform_switch, tenancy
    raw = None
    try:
        raw = platform_switch.value(SWITCH_KEY) if tenancy.tenant_mode() else platform_switch.console_value(
            SWITCH_KEY, raw=True)
    except Exception:
        raw = None
    try:
        found = json.loads(raw) if raw else None
    except ValueError:
        found = None
    if not isinstance(found, dict):
        return dict(DEFAULT_HOURS)
    return {d: str(found.get(str(d), '')) for d in range(7)}


def _booked_times():
    """UTC times already booked on the console's Schedule (any trial)."""
    from . import followups
    return [a['at'] for a in followups.appointments(days=AHEAD_DAYS + 1)]


def slots(now=None, taken=None):
    """[(day label, [(value 'YYYY-MM-DDTHH:MM' IST, '5:00 PM')])] for the next AHEAD_DAYS days, free ones only."""
    now = now or datetime.utcnow()
    taken = _booked_times() if taken is None else taken
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
        for start, end in ranges:
            t = -(-start // SLOT_MINUTES) * SLOT_MINUTES          # on the hour or half hour
            while t + SLOT_MINUTES <= end:
                at = datetime(day.year, day.month, day.day) + timedelta(minutes=t)
                utc = at - IST
                if at >= soonest and all(abs((utc - b).total_seconds()) >= SLOT_MINUTES * 60 for b in taken):
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
        raise ValueError('Type the phone number we should call, e.g. 98765 43210.')
    at_ist = datetime.strptime(value, '%Y-%m-%dT%H:%M')
    slug = tenancy.current_slug()
    brand = branding.get_brand()
    note = ' '.join((note or '').split())[:300]
    text = f'Set-up call booked in the app by {user_name or "their admin"}, on {phone.strip()}' + (f'. {note}' if note else '')
    aid = followups.book(slug, at_ist, mode='call', note=text)
    at = at_ist - IST
    AppSetting.set(BOOKED_KEY, json.dumps({'at': at.isoformat(), 'id': aid}))
    db.session.commit()
    if mailer.enabled():                            # so we see it straight away
        when = followups.when_text(at)
        mailer.send(mailer.operator(), f'Call booked: {brand["name"]}, {when}',
                    f'{brand["name"]} ({slug}) booked a free set-up call.\n\nWhen: {when} (India time)\n'
                    f'Call: {phone.strip()}\nBooked by: {user_name or "their admin"}\n'
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
