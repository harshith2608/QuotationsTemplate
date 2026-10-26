"""Presentation pages on the customer's quotation PDF: a title page (the firm, then "Quotation for" the client), an
"About us" page, the quotation, the terms, and a last page with the next steps and a thank-you note.

Turned on per business from the console (Features → Presentation pages), off by default. The business writes its own
About us and Next steps in Settings → Quotation PDFs (or they come with its price list file). An empty About us
leaves that page out; empty Next steps prints the usual steps (DEFAULT_STEPS).
"""
from flask import has_app_context

KEY = 'feature_cover_pages'
ABOUT_KEY = 'about_us'
NEXT_KEY = 'next_steps'
TEXT_MAX = 5000

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
    """{'about': [paragraphs], 'steps': [lines]} for the PDF."""
    from .models import AppSetting
    s = AppSetting.get_many([ABOUT_KEY, NEXT_KEY])
    about = [p.strip() for p in (s[ABOUT_KEY] or '').replace('\r', '').split('\n\n') if p.strip()]
    import re
    steps = [re.sub(r'^\s*(\d+[.)]|[•●\-–*])\s*', '', line).strip() for line in (s[NEXT_KEY] or '').splitlines()]
    steps = [x for x in steps if x] or DEFAULT_STEPS
    return {'about': about, 'steps': steps}


def texts():
    """The raw texts for Settings."""
    from .models import AppSetting
    s = AppSetting.get_many([ABOUT_KEY, NEXT_KEY])
    return {'about_us': s[ABOUT_KEY] or '', 'next_steps': s[NEXT_KEY] or ''}


def save_texts(about, steps):
    from .models import AppSetting
    AppSetting.set(ABOUT_KEY, (about or '').strip()[:TEXT_MAX])
    AppSetting.set(NEXT_KEY, (steps or '').strip()[:TEXT_MAX])
