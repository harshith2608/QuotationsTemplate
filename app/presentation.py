"""Presentation pages on the customer's quotation PDF: a title page (the firm, then "Quotation for" the client), an
"About us" page, the quotation, the terms, and a last page with the next steps and a thank-you note.

Turned on per business from the console (Features → Presentation pages), off by default. The business writes its own
About us and Next steps in Settings → Quotation PDFs, in a rich text editor (app/richtext.py: headings, colours,
alignment, lists), or they come as plain text with its price list file. An empty About us leaves that page out; empty
Next steps prints the usual steps (DEFAULT_STEPS).
"""
from flask import has_app_context

KEY = 'feature_cover_pages'
ABOUT_KEY = 'about_us'
NEXT_KEY = 'next_steps'
TEXT_MAX = 20000

DEFAULT_STEPS = [
    'Go through this quotation and tell us any changes you would like.',
    'Confirm the quotation and pay the booking advance.',
    'Site measurement, then the final design and material selection.',
    'Production and installation, as per the agreed timeline.',
    'Handover, with a final walkthrough together.',
]


def enabled():
    from .models import AppSetting
    return AppSetting.get(KEY, '') == '1'


def console_status():
    return {'on': enabled()}


def set_enabled(on):
    from .models import AppSetting
    AppSetting.set(KEY, '1' if on else '')


def content():
    """{'about': [paragraphs], 'steps': [lines], 'about_html', 'steps_html'} for the PDF; the *_html ones (formatted in
    the editor) are used instead when set."""
    from . import richtext
    from .models import AppSetting
    s = AppSetting.get_many([ABOUT_KEY, NEXT_KEY])
    html = {k: richtext.clean(s[k]) if richtext.is_html(s[k]) else '' for k in (ABOUT_KEY, NEXT_KEY)}
    s = {k: '' if richtext.is_html(s[k]) else s[k] for k in (ABOUT_KEY, NEXT_KEY)}       # plain text (older / price list)
    about_html, steps_html = html[ABOUT_KEY], html[NEXT_KEY]
    about = [p.strip() for p in (s[ABOUT_KEY] or '').replace('\r', '').split('\n\n') if p.strip()]
    import re
    steps = [re.sub(r'^\s*(\d+[.)]|[•●\-–*])\s*', '', line).strip() for line in (s[NEXT_KEY] or '').splitlines()]
    steps = [x for x in steps if x] or DEFAULT_STEPS
    return {'about': about, 'steps': steps, 'about_html': about_html, 'steps_html': steps_html}


def texts():
    """The texts for the Settings editors, as HTML (plain text saved before is turned into HTML)."""
    from . import richtext
    from .models import AppSetting
    s = AppSetting.get_many([ABOUT_KEY, NEXT_KEY])
    as_html = lambda v, numbered: richtext.clean(v) if richtext.is_html(v) else richtext.from_plain(v, numbered)
    return {'about_us': as_html(s[ABOUT_KEY], False), 'next_steps': as_html(s[NEXT_KEY], True)}


def save_texts(about, steps):
    """From the editors (HTML, cleaned) or plain text."""
    from . import richtext
    from .models import AppSetting
    tidy = lambda v: richtext.clean(v) if richtext.is_html(v) else (v or '').strip()[:TEXT_MAX]
    AppSetting.set(ABOUT_KEY, tidy(about))
    AppSetting.set(NEXT_KEY, tidy(steps))
