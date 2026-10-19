"""The setup guide: the steps a new business goes through (company details, logo, units, rates, quotation PDF, how
customers pay, the first quotation), for the admin.

A step is done when the app can see it (a logo uploaded, a quotation made…), when its page has been saved (noted by
admin_bp after a successful save), or when the admin marks it done. Progress is one app_settings row (JSON), so
there is no database update. A new business's admin lands on the guide after their first sign-in; it is always
reachable from the admin menu and, until finished or hidden, from a card on the quotations list.

While following the guide, the step's page shows a banner (templates/_setup_banner.html) with "Done, next step".
"""
import json

from flask import session, url_for

KEY = 'setup_guide'
ESTABLISHED = 3          # quotations made: from here on the guide no longer opens or shows its card by itself
SESSION_KEY = 'setup_step'


class Step:
    def __init__(self, key, title, what, endpoint, args=None, saved=None, optional=False):
        self.key, self.title, self.what, self.endpoint = key, title, what, endpoint
        self.args = args or {}
        self.saved = saved            # the page whose successful save completes it, e.g. 'admin.settings:company'
        self.optional = optional

    def url(self, **extra):
        return url_for(self.endpoint, **self.args, **extra)

    def matches(self, endpoint, args):
        return endpoint == self.endpoint and all(args.get(k) == v for k, v in self.args.items())


STEPS = [
    Step('company', 'Your company details', 'Name, phone, address and GSTIN: they go on every quotation, invoice and '
         'WhatsApp message.', 'admin.settings', {'tab': 'company'}, saved='admin.settings:company'),
    Step('logo', 'Logo & colours', 'Upload your logo and pick your colours, so the app and every PDF look like yours.',
         'admin.settings', {'tab': 'appearance'}, saved='admin.settings:appearance'),
    Step('units', 'Units of measurement', 'Feet & inches, mm, cm or inches, and rates per sqft or per sq m.',
         'admin.settings', {'tab': 'units'}, saved='admin.settings:units'),
    Step('rates', 'Your rates, materials & plywood', 'Your rate for each material and work type, the plywood you offer, '
         'and your fittings price list (Magic Corner, hinges…).', 'admin.rates', saved='admin.rates'),
    Step('pdf', 'Your quotation PDF', 'Room by room or by material, room descriptions, material specifications, payment '
         'and delivery terms, and your terms & conditions.', 'admin.settings', {'tab': 'documents'},
         saved='admin.settings:documents'),
    Step('payments', 'How customers pay you', 'Your UPI ID and bank details, printed on quotations and invoices. '
         'Online payments with Razorpay are optional.', 'admin.payment_settings', saved='admin.payment_settings'),
    Step('first_quote', 'Make your first quotation', 'Add rooms and items with their sizes; the total works itself out. '
         'Then send it on WhatsApp.', 'projects.create_project'),
    Step('costs', 'Your costs (to see your profit)', 'What each material and fitting costs you: every quotation then shows '
         'its profit, only to admins.', 'admin.costs', saved='admin.costs', optional=True),
    Step('team', 'Add your team', 'A login for each person in your team: one price, however many people.', 'admin.users',
         optional=True),
    Step('invoices', 'Invoice settings', 'GST or not, GST rate, invoice numbering and notes.', 'admin.settings',
         {'tab': 'invoices'}, saved='admin.settings:invoices', optional=True),
    Step('email', 'Send by email', 'Send quotations and invoices from your own email address.', 'admin.settings',
         {'tab': 'email'}, saved='admin.settings:email', optional=True),
]
BY_KEY = {s.key: s for s in STEPS}
BY_SAVED = {s.saved: s for s in STEPS if s.saved}


def _state():
    from .models import AppSetting
    try:
        data = json.loads(AppSetting.get(KEY, '') or '{}')
    except ValueError:
        data = {}
    return data if isinstance(data, dict) else {}


def _store(data):
    from .models import AppSetting
    AppSetting.set(KEY, json.dumps(data, sort_keys=True))


def _seen_done():
    """(steps the app can see are done, whatever the guide's own record says; quotations sent so far)"""
    from sqlalchemy import func, select
    from . import billing, db
    from .branding import get_brand
    from .models import AppSetting, CostRate, Project, User
    done = set()
    if get_brand().get('logo_url'):
        done.add('logo')
    counts = [select(func.count(Project.id)).where(Project.status != 'draft').scalar_subquery(),
              select(func.count(User.id)).scalar_subquery()]
    if billing.ready():                                    # cost_rates arrives with a database update
        counts.append(select(func.count(CostRate.id)).scalar_subquery())
    row = db.session.execute(select(*counts)).one()       # every count in one query
    if row[0]:
        done.add('first_quote')
    quotes = row[0]
    if row[1] > 1:
        done.add('team')
    if len(row) > 2 and row[2]:
        done.add('costs')
    s = AppSetting.get_many(['upi_id', 'account_number', 'smtp_host'])   # already read with the common settings
    if s['upi_id'] or s['account_number']:
        done.add('payments')
    if s['smtp_host']:
        done.add('email')
    return done, quotes


def status():
    """{'steps': [(step, done)], 'done': n, 'total': n (required steps), 'complete': bool, 'hidden': bool, 'next': step,
    'quotes': quotations made (not drafts), 'show_card': bool}"""
    data = _state()
    seen, quotes = _seen_done()
    done = set(data.get('done') or []) | seen
    rows = [(s, s.key in done) for s in STEPS]
    required = [s for s in STEPS if not s.optional]
    n_done = sum(1 for s in required if s.key in done)
    nxt = next((s for s, d in rows if not d and not s.optional), None) or next((s for s, d in rows if not d), None)
    complete = n_done == len(required)
    return {'steps': rows, 'done': n_done, 'total': len(required), 'complete': complete,
            'hidden': bool(data.get('hidden')), 'next': nxt, 'quotes': quotes,
            # the reminder card is for businesses getting started; established ones have the guide in the menu
            'show_card': not complete and not data.get('hidden') and quotes < ESTABLISHED}


def mark(key, done=True):
    if key not in BY_KEY:
        return
    data = _state()
    marked = set(data.get('done') or [])
    (marked.add if done else marked.discard)(key)
    data['done'] = sorted(marked)
    _store(data)


def page_saved(endpoint, form):
    """After a successful save in admin_bp: the step for that page is done."""
    tab = form.get('section') or form.get('tab') or 'company'
    step = BY_SAVED.get(f'{endpoint}:{tab}') or BY_SAVED.get(endpoint)
    if step:
        mark(step.key)


def set_hidden(hidden):
    data = _state()
    data['hidden'] = bool(hidden)
    _store(data)


def note_seen():
    data = _state()
    if not data.get('seen'):
        data['seen'] = True
        _store(data)


def open_on_first_login():
    """True for a new business's admin who hasn't seen the guide and hasn't made a quotation yet (so businesses already
    using the app aren't sent there after an update). Never in the demo."""
    from .demo import demo_enabled
    if demo_enabled() or _state().get('seen'):
        return False
    st = status()
    return not st['complete'] and st['quotes'] == 0


# ── Following the guide: which step this page is, for the banner ─────────────

def follow(key):
    session[SESSION_KEY] = key


def stop():
    session.pop(SESSION_KEY, None)


def banner(endpoint, args):
    """(step, number, total, next step) when the admin is following the guide and on that step's page, else None."""
    key = session.get(SESSION_KEY)
    step = BY_KEY.get(key)
    if not step or not step.matches(endpoint, args):
        return None
    st = status()
    order = [s for s, _ in st['steps']]
    required = [s for s in order if not s.optional]
    after = [s for s, d in st['steps'][order.index(step) + 1:] if not d]
    return {'step': step, 'number': None if step.optional else required.index(step) + 1, 'total': len(required),
            'next': after[0] if after else None, 'done': dict((s.key, d) for s, d in st['steps']).get(step.key)}
