"""
Other company profiles: a business that quotes under more than one name (a second firm, a sister concern) keeps
each one's name, phone, email, address, GSTIN, tagline and logo here, and picks which one each quotation is from.

Off unless the operator turns it on for that business in the console (customers only), with the number of extra
profiles allowed. The main company stays in Admin → Settings; these are the others.

Stored in app_settings (no database update needed):
  company_profiles_limit   how many extra profiles the operator allows ('' / 0 = off)
  company_profiles         JSON list of {id, name, address, phone, email, gstin, tagline, logo_version}
  profile_logo_<id>        the profile's logo, base64 PNG
  quote_profile_<project>  the profile a quotation is from (no row = the main company)

A quotation keeps its profile if the feature is turned off later: what was sent stays what was sent.
"""
import base64
import json

from flask import g, has_app_context, request, url_for

LIMIT_KEY = 'company_profiles_limit'
KEY = 'company_profiles'
MAX_LIMIT = 10
FIELDS = ('name', 'address', 'phone', 'email', 'gstin', 'tagline')
# Its own payment details (optional): when any is filled, the quotation shows these instead of the main company's
PAY = ('upi_id', 'bank_name', 'account_name', 'account_number', 'ifsc_code')
SECRET_PAY = ('account_number', 'ifsc_code')                 # stored encrypted, like the main company's


class ProfileError(ValueError):
    pass


def _logo_key(pid):
    return f'profile_logo_{int(pid)}'


def _project_key(project_id):
    return f'quote_profile_{int(project_id)}'


# ── Operator switch ───────────────────────────────────────────────────────────

def limit():
    from .models import AppSetting
    try:
        return max(0, min(int(AppSetting.get(LIMIT_KEY, '') or 0), MAX_LIMIT))
    except (TypeError, ValueError):
        return 0


def enabled():
    return limit() > 0


def set_limit(n):
    from .models import AppSetting
    n = max(0, min(int(n), MAX_LIMIT))
    AppSetting.set(LIMIT_KEY, str(n) if n else '')
    return n


def console_status():
    return {'limit': limit(), 'used': len(all_profiles()), 'max': MAX_LIMIT}


# ── Profiles ──────────────────────────────────────────────────────────────────

def all_profiles():
    from .models import AppSetting
    try:
        rows = json.loads(AppSetting.get(KEY, '') or '[]')
    except ValueError:
        return []
    return [r for r in rows if isinstance(r, dict) and r.get('id')]


def _save_all(rows):
    from .models import AppSetting
    AppSetting.set(KEY, json.dumps(rows))


def get(pid):
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return None
    return next((p for p in all_profiles() if p['id'] == pid), None)


def can_add():
    return enabled() and len(all_profiles()) < limit()


def clean(form, existing=None):
    """The profile fields from a submitted form, validated. Name and GSTIN don't change once saved (like the main
    company): to correct one, the business asks us, or deletes the profile while no quotation uses it."""
    from . import branding
    out = {k: (form.get(k) or '').strip() for k in FIELDS}
    out['gstin'] = out['gstin'].upper().replace(' ', '')
    if existing and branding.lock_enabled():
        for k in ('name', 'gstin'):
            if existing.get(k):
                out[k] = existing[k]
    from .crypto import encrypt
    for k in PAY:
        v = (form.get(k) or '').strip()[:120]
        if k == 'ifsc_code':
            v = v.upper().replace(' ', '')
        out[k] = encrypt(v) if v and k in SECRET_PAY else v
    if not out['name']:
        raise ProfileError('Enter the company name.')
    if len(out['name']) > 120:
        raise ProfileError('The company name is too long.')
    if out['gstin'] and not branding.GSTIN_RE.match(out['gstin']):
        raise ProfileError(f'"{out["gstin"]}" doesn\'t look like a valid GSTIN (15 characters, e.g. 29ABCDE1234F1Z5).')
    main = (branding.get_brand().get('name') or '').strip().lower()
    others = [p['name'].strip().lower() for p in all_profiles() if not existing or p['id'] != existing['id']]
    if out['name'].lower() == main or out['name'].lower() in others:
        raise ProfileError(f'You already have a company called "{out["name"]}".')
    return out


def add(form):
    if not enabled():
        raise ProfileError('Other company profiles are not turned on for your account.')
    if not can_add():
        raise ProfileError(f'You can have up to {limit()} other compan{"y" if limit() == 1 else "ies"}. '
                           'Message us to add more.')
    rows = all_profiles()
    profile = clean(form)
    profile['id'] = max([p['id'] for p in rows] + [0]) + 1
    profile['logo_version'] = ''
    rows.append(profile)
    _save_all(rows)
    return profile


def update(pid, form):
    rows = all_profiles()
    existing = next((p for p in rows if p['id'] == int(pid)), None)
    if not existing:
        raise ProfileError('That company was not found.')
    existing.update(clean(form, existing))
    _save_all(rows)
    return existing


def quotations_using(pid):
    from .models import AppSetting
    return AppSetting.query.filter(AppSetting.key.like('quote_profile_%'), AppSetting.value == str(int(pid))).count()


def delete(pid):
    from .models import AppSetting
    n = quotations_using(pid)
    if n:
        raise ProfileError(f'{n} quotation{"s are" if n != 1 else " is"} from this company, so it can\'t be deleted.')
    _save_all([p for p in all_profiles() if p['id'] != int(pid)])
    AppSetting.set(_logo_key(pid), '')


def set_logo(pid, raw):
    from . import branding
    from .models import AppSetting
    rows = all_profiles()
    p = next((r for r in rows if r['id'] == int(pid)), None)
    if not p:
        raise ProfileError('That company was not found.')
    if p.get('logo_version') and branding.lock_enabled():
        raise ProfileError('The logo is locked once saved. Message us if it needs changing.')
    try:
        png, version = branding.process_logo_upload(raw)
    except branding.LogoError as exc:
        raise ProfileError(str(exc))
    AppSetting.set(_logo_key(pid), base64.b64encode(png).decode())
    p['logo_version'] = version
    _save_all(rows)


def logo_png(pid):
    from .models import AppSetting
    data = AppSetting.get(_logo_key(pid), '') if pid else ''
    return base64.b64decode(data) if data else None


# ── Which company a quotation is from ────────────────────────────────────────

def for_project(project_id):
    """The profile a quotation is from, or None for the main company."""
    from .models import AppSetting
    if not project_id:
        return None
    pid = AppSetting.get(_project_key(project_id), '')
    return get(pid) if pid else None


def set_for_project(project_id, pid):
    from .models import AppSetting
    if pid and str(pid) != '0':
        if not get(pid):
            raise ProfileError('That company was not found.')
        AppSetting.set(_project_key(project_id), str(int(pid)))
    else:
        row = AppSetting.query.get(_project_key(project_id))
        if row:
            from .models import db
            db.session.delete(row)
            cache = AppSetting._cache()
            if cache is not None:
                cache[_project_key(project_id)] = None


def forget_project(project_id):
    """When a quotation is deleted."""
    try:
        set_for_project(project_id, None)
    except Exception:
        pass


def payment_details(profile):
    """The profile's own payment details (decrypted), or None when it has none (the main company's are used)."""
    from .crypto import decrypt
    pay = {k: (decrypt(profile.get(k)) if k in SECRET_PAY and profile.get(k) else (profile.get(k) or '')) for k in PAY}
    return pay if any(pay.values()) else None


def brand_for(profile, base):
    """The brand dict with the company part (name, contact, GSTIN, tagline, logo) from the profile; colours stay."""
    brand = dict(base)
    for k in FIELDS:
        brand[k] = profile.get(k) or ''
    brand['tagline'] = profile.get('tagline') or ''
    brand['signatory_name'] = profile['name']
    version = profile.get('logo_version') or ''
    brand['logo_version'] = version
    brand['logo_file'] = ''
    brand['logo_url'] = url_for('main.brand_logo', p=profile['id'], v=f'{version}t') if version else ''
    brand['profile_id'] = profile['id']
    return brand


def apply(project_id):
    """Use the quotation's company for the rest of this request (PDF, link, WhatsApp, email). Safe to call for any
    quotation; does nothing for the main company."""
    if not has_app_context() or not project_id:
        return None
    try:
        from . import branding
        branding.prefetch_common(extra=[_project_key(project_id)])   # with the page's other settings: one query
        profile = for_project(project_id)
    except Exception:
        return None
    if not profile:
        return None
    from . import branding
    g.app_brand = branding.get_brand()
    g.brand = brand_for(profile, g.app_brand)
    g.profile_logo_id = profile['id']
    g.profile_pay = payment_details(profile)          # AppSetting.get / get_many answer with these
    return profile


def apply_for_request():
    """before_request: any page of a quotation (/projects/<id>/…) uses that quotation's company."""
    pid = (request.view_args or {}).get('project_id')
    if pid:
        apply(pid)


def choices():
    """[(id, name)] for the quotation's company picker: 0 = the main company."""
    from . import branding
    base = g.get('app_brand') or branding.get_brand()
    return [(0, base.get('name') or 'Main company')] + [(p['id'], p['name']) for p in all_profiles()]
