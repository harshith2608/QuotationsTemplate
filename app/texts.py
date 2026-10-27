"""Every message the platform sends or drafts for the operator, editable in the console (Messages).

Each one has a key, a default (the wording written here) and placeholders ({name}, {url}…) filled in when it's used.
An edited one is kept in the console's database (public.console_texts) and used instead of the default; Reset goes back
to it. An app that can't see that table (a paying customer's own database) uses the defaults.
render() never fails on a text: a placeholder it doesn't know stays as it is.

Not here: the website's set-up link email (the website is another app, with its own database).
"""
import re

from flask import g, has_app_context
from sqlalchemy import text

from . import db

DDL = """CREATE TABLE IF NOT EXISTS public.console_texts (
    key        VARCHAR(60) PRIMARY KEY,
    subject    TEXT,
    body       TEXT NOT NULL,
    updated_at TIMESTAMP NOT NULL DEFAULT (now() AT TIME ZONE 'utc'))"""


# Follow-ups: the trial page's WhatsApp drafts, and the same text as an email (with its subject)
FU_FIELDS = {'name': "their first name (typed on the page)", 'sender': 'your name', 'product': 'QuoteRoom',
             'url': 'their app address', 'prices': 'the plan prices', 'ends_on': 'trial end date',
             'delete_on': 'date their data is deleted'}
_FU = [
    ('signin', 'Not signed in yet', 'Your {product} app is ready',
     "Hi {name}, this is {sender} from {product}. Just checking you got the login I sent. If you have any trouble "
     "signing in, tell me and I'll sort it out right away.\n\nOpen: {url}\n\nIt takes about 10 minutes to set up your "
     "rates and make your first quotation."),
    ('details', 'Company details and logo', 'Add your company details to {product}',
     "Hi {name}, good to see you've signed in to {product} 👍 Next: add your company name, address and logo in "
     "Settings, so every quotation goes out in your brand. It takes 2 minutes: {url}/admin/settings\n\nOr send me your "
     "logo here and I'll add it for you."),
    ('firstquote', 'Their first quotation', 'Make your first quotation in {product}',
     "Hi {name}, your {product} is set up 👍 Try your first quotation now: New Quotation, pick a starting quotation, "
     "type the sizes and send the PDF on WhatsApp.\n\nIf you send me one of your old quotations, I'll set up your items "
     "and rates for you, so it's ready in your own format."),
    ('rates', 'Help with rates (offer a call)', 'Setting up your rates in {product}',
     "Hi {name}, good to see you've started on {product} 👍 The next step is your rates for each material and work "
     "type. Once they're in, every quotation works itself out. If it's easier, I can set up your rates with you on a "
     "10-minute call, whenever suits you."),
    ('quote', 'Going well: make a real quotation', 'Your first real quotation with {product}',
     "Hi {name}, great to see you're set up on {product}! Try making a quotation for one of the customers you're "
     "quoting this week. You can send it on WhatsApp as a PDF, or as a link they can accept online. If you send me "
     "your logo, I'll add it so the PDF is in your brand. Anything you need, just message me."),
    ('checkin', 'Quiet for a while: check in', 'How is your {product} trial going?',
     "Hi {name}, {sender} from {product} here. How is the trial going? If something got in the way or didn't work "
     "the way you quote, tell me. I'm happy to set it up with you on a quick call."),
    ('ending', 'Trial ending soon (plans)', 'Your {product} trial ends on {ends_on}',
     "Hi {name}, your {product} trial ends on {ends_on}. Everything you've set up (rates, logo, quotations) stays "
     "when you continue. Plans: {prices}. Which one suits you? Happy to answer any questions on a quick call."),
    ('ended', 'Trial ended: continue or feedback', 'Continue with {product}',
     "Hi {name}, your {product} trial ended on {ends_on}. Your data is kept until {delete_on}, so you can continue "
     "right where you left off: {prices}. If it wasn't the right fit, could you tell me what was missing? It really "
     "helps."),
    ('custom', 'Custom message', '', 'Hi {name}, '),
]

STAGE_FIELDS = {'hello': '"Hello Ravi" (or "Hello")', 'url': 'their app address'}
_OUTRO = '\n\nQuestions? Just reply to this email or message us on WhatsApp.\n\nQuoteRoom\n'
_REMIND_FIELDS = {'when': '"today", "tomorrow" or "in 3 days"', 'end': 'end date', 'plan': 'their plan',
                  'grace': 'last day before read-only', 'delete': 'date their data is deleted',
                  'plan_link': 'their Plan page', 'price_6m': '6-month price', 'price_1y': '12-month price'}


def _remind(first):
    return ('Hello,\n\n' + first + '\n\nChoose a plan in your app: {plan_link}\n'
            '6 months ₹{price_6m} · 12 months ₹{price_1y} (your whole team, all features)\n\n'
            'Questions? Just reply to this email.\n\nQuoteRoom\n')


# key: (group, label, channel, subject, body, {placeholder: what it is})
TEXTS = {}
for _k, _label, _subject, _body in _FU:
    TEXTS[f'fu_{_k}'] = ('Follow-ups (trial page and Email)', _label, 'WhatsApp draft, and the same as an email',
                         _subject, _body, FU_FIELDS)
TEXTS.update({
    'email_signoff': ('Follow-ups (trial page and Email)', 'Email sign-off', 'Added under emails you write in the console',
                      None, '\n\n{sender}\n{product}\n(Just reply to this email if you have any questions.)',
                      {'sender': 'your name', 'product': 'QuoteRoom'}),
    'trial_welcome': ('New trials and customers', 'Trial is ready (login)', 'WhatsApp, after Create trial', None,
                      "{hello} Your {product} free trial{for_company} is ready.\n\nOpen: {url}\nUsername: {username}\n"
                      "Password: {password}\n\nWhen you sign in, a short setup guide takes you through your rates and "
                      "settings step by step.\n\n{company_note}{tutorials}Your trial runs until {ends_on}. On your phone, "
                      "add the page to your home screen for one-tap access. Reply here if you need any help!",
                      {'hello': '"Hi Ravi!" (or "Hi!")', 'product': 'QuoteRoom', 'for_company': '" for Kumar Interiors"',
                       'url': 'their app address', 'username': 'login', 'password': 'password',
                       'company_note': 'a line saying their company name is filled in (when it is)',
                       'tutorials': 'the tutorials line', 'ends_on': 'trial end date'}),
    'customer_ready': ('New trials and customers', 'Paid app is ready (new customer)', 'WhatsApp, on the customer page',
                       None, "Hi! Your {product} app is ready.\n\nOpen: {url}\nUsername: {username}\nPassword: {password}"
                       "\n\n{tutorials}On your phone, add the page to your home screen for one-tap access. Reply here if "
                       "you need any help!",
                       {'product': 'QuoteRoom', 'url': 'their app address', 'username': 'login', 'password': 'password',
                        'tutorials': 'the tutorials line'}),
    'customer_subscribed': ('New trials and customers', 'Thank you for subscribing (trial moved to paid)',
                            'WhatsApp, on the customer page', None,
                            "Hi! Thank you for subscribing to {product}. Your app is now on your paid plan: same address "
                            "({url}), same login and all your quotations. Reply here if you need any help!",
                            {'product': 'QuoteRoom', 'url': 'their app address'}),
    'lead_whatsapp': ('Trial requests', 'Thanks for your interest (WhatsApp)', 'WhatsApp, on a new request', None,
                      'Hi {name}, thanks for your interest in QuoteRoom!', {'name': 'their name'}),
    'lead_setup': ('Trial requests', 'Set-up link again', 'Email, on a new request', 'Your {product} set-up link',
                   "Hi {name},\n\nThanks for asking for a {product} free trial. Here is your link to set up your app, in "
                   "case the first email got lost:\n{link}\n\nIt takes a minute: choose your web address and password, "
                   "and your free 7-day trial starts. The link works for {days} days.",
                   {'name': 'their first name', 'product': 'QuoteRoom', 'link': 'a fresh set-up link',
                    'days': 'days the link works'}),
    'lead_hello': ('Trial requests', 'Thanks for your interest (email)', 'Email, on a new request',
                   'Your {product} free trial',
                   "Hi {name},\n\nThanks for your interest in {product}. I'd be happy to set up your free trial with "
                   "you, with your own items and rates. When is a good time for a quick call?",
                   {'name': 'their first name', 'product': 'QuoteRoom'}),
    'stage_signin': ('Automatic emails (daily)', 'Not signed in after a day', 'Email', 'Your QuoteRoom app is ready',
                     '{hello},\n\nYour QuoteRoom app is ready and waiting for you:\n{url}\n\nSign in with the username and '
                     'password you chose (or the ones we sent you). Setting up takes about 10 minutes: your company '
                     'details and logo, then your first quotation.' + _OUTRO, STAGE_FIELDS),
    'stage_details': ('Automatic emails (daily)', 'No company details after a day', 'Email',
                      'Add your company details to QuoteRoom',
                      "{hello},\n\nGood to see you've signed in to QuoteRoom!\n\nNext: add your company name, address and "
                      "logo in Settings, so every quotation goes out in your own brand. It takes 2 minutes:\n"
                      "{url}/admin/settings\n\nYou can also reply with your logo and we'll add it for you." + _OUTRO,
                      STAGE_FIELDS),
    'stage_firstquote': ('Automatic emails (daily)', 'No quotation after two days', 'Email',
                         'Make your first quotation in QuoteRoom',
                         "{hello},\n\nYour QuoteRoom app is set up. Now try your first quotation: New Quotation, pick a "
                         "starting quotation, type the sizes, and send the PDF to your customer on WhatsApp.\n"
                         "{url}/projects/new\n\nHave old quotations? Reply with one and we'll set up your items and rates "
                         "for you." + _OUTRO, STAGE_FIELDS),
    'remind_trial_2': ('Automatic emails (daily)', 'Trial ends in 2 days', 'Email', 'Your QuoteRoom free trial ends {when}',
                       _remind('Your free trial ends {when} ({end}). Choose a plan to keep everything you have set up '
                               'and keep quoting.'), _REMIND_FIELDS),
    'remind_trial_end': ('Automatic emails (daily)', 'Trial has ended', 'Email', 'Your QuoteRoom free trial has ended',
                         _remind('Your free trial ended on {end}, so your app is now read-only. Choose a plan to carry '
                                 'on: everything is still there until {delete}.'), _REMIND_FIELDS),
    'remind_paid_15': ('Automatic emails (daily)', 'Plan ends in 15 days', 'Email', 'Your QuoteRoom plan ends on {end}',
                       _remind('Your {plan} ends on {end}. Renew now and the new period starts when this one ends, so no '
                               'days are lost.'), _REMIND_FIELDS),
    'remind_paid_3': ('Automatic emails (daily)', 'Plan ends in 3 days', 'Email', 'Your QuoteRoom plan ends {when}',
                      _remind('Your {plan} ends {when} ({end}). Renew to keep creating quotations without a break.'),
                      _REMIND_FIELDS),
    'remind_paid_end': ('Automatic emails (daily)', 'Plan has ended', 'Email', 'Your QuoteRoom plan has ended',
                        _remind('Your {plan} ended on {end}. You can keep working until {grace}; after that your app '
                                'becomes read-only. Renew to carry on.'), _REMIND_FIELDS),
    'pay_link': ('Payments', 'Payment link', 'WhatsApp and email, with a payment link', 'Your QuoteRoom payment link ({plan})',
                 "Hi! Here is the payment link for your QuoteRoom {plan} ({amount}, your whole team, all features):\n\n"
                 "{link}\n\nPay by UPI, card or net banking. {after} You'll get a receipt by email.\n\nThank you!",
                 {'plan': 'the plan', 'amount': 'the amount', 'link': 'the payment link',
                  'after': 'what happens once paid (new app, or plan active straight away)'}),
    'pay_receipt': ('Payments', 'Payment received (with the receipt)', 'Email, when they pay',
                    'Payment received: QuoteRoom {plan}',
                    "{hello},\n\nThank you! We've received {amount} for your QuoteRoom {plan}.\n\nBusiness: {business}\n"
                    "Your app: {app}\nPlan: {plan_start} to {plan_end}\nReceipt: {receipt_no} (attached)\n\nEverything "
                    "you've set up and every quotation stays exactly as it is. Same address, same login.\n\nQuestions? "
                    "Just reply to this email.\n\nQuoteRoom\n",
                    {'hello': '"Hello Ravi" (or "Hello")', 'amount': 'the amount', 'plan': 'the plan',
                     'business': 'business name', 'app': 'their app address', 'plan_start': 'plan start',
                     'plan_end': 'plan end', 'receipt_no': 'receipt number'}),
})
GROUPS = list(dict.fromkeys(v[0] for v in TEXTS.values()))
FIELD_RE = re.compile(r'\{([a-z_0-9]+)\}')

_ready = False


def ensure_table():
    global _ready
    if not _ready:
        with db.engine.begin() as conn:
            conn.execute(text(DDL))
        _ready = True


def _overrides():
    """{key: (subject, body)} edited in the console; {} when the table can't be read (once per request)."""
    if has_app_context() and '_texts' in g:
        return g._texts
    try:
        ensure_table()
        with db.engine.connect() as conn:
            out = {r[0]: (r[1], r[2]) for r in conn.execute(text('SELECT key, subject, body FROM public.console_texts'))}
    except Exception:
        out = {}
    if has_app_context():
        g._texts = out
    return out


def get(key):
    """(subject, body) as edited, else the default."""
    _, _, _, subject, body, _ = TEXTS[key]
    o = _overrides().get(key)
    return (o[0] if o and subject is not None else subject, o[1] if o else body)


class _Keep(dict):
    def __missing__(self, key):
        return '{' + key + '}'


def fill(template, **values):
    """The text with its placeholders filled in; unknown ones stay as they are; never fails."""
    try:
        return (template or '').format_map(_Keep(values))
    except (ValueError, IndexError, AttributeError):
        return template or ''


def render(key, **values):
    subject, body = get(key)
    return (fill(subject, **values) if subject is not None else None), fill(body, **values)


def unknown_fields(key, *parts):
    allowed = set(TEXTS[key][5])
    return sorted({f for p in parts for f in FIELD_RE.findall(p or '')} - allowed)


def save(key, subject, body):
    ensure_table()
    with db.engine.begin() as conn:
        conn.execute(text("INSERT INTO public.console_texts (key, subject, body, updated_at) VALUES (:k, :s, :b, "
                          "(now() AT TIME ZONE 'utc')) ON CONFLICT (key) DO UPDATE SET subject = :s, body = :b, "
                          "updated_at = (now() AT TIME ZONE 'utc')"), {'k': key, 's': subject, 'b': body})
    if has_app_context():
        g.pop('_texts', None)


def reset(key):
    ensure_table()
    with db.engine.begin() as conn:
        conn.execute(text('DELETE FROM public.console_texts WHERE key = :k'), {'k': key})
    if has_app_context():
        g.pop('_texts', None)


def listing():
    """[(group, [{key, label, channel, subject, body, fields, edited, default_subject, default_body}])] for the page."""
    o = _overrides()
    out = {grp: [] for grp in GROUPS}
    for key, (grp, label, channel, subject, body, fields) in TEXTS.items():
        s, b = get(key)
        out[grp].append({'key': key, 'label': label, 'channel': channel, 'subject': s, 'body': b, 'fields': fields,
                         'edited': key in o, 'default_subject': subject, 'default_body': body})
    return list(out.items())
