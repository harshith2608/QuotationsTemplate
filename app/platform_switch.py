"""Platform switches: a feature on or off for every business at once, off until switched on.

The shared app (trials, and customers moved onto it) reads the console's switch from public.console_state in the
trials database (the console's database), every TTL seconds. A single-business deployment (the demo, a customer's own
app) has no console switch: its environment variable turns the feature on (e.g. MATERIAL_LIST=1).
"""
import os
import time

from sqlalchemy import text

from . import db

TTL = 30
_cache = {}


def _truthy(value):
    return (value or '').strip().lower() in ('1', 'true', 'yes', 'on')


def is_on(key, env_var):
    """Is the feature switched on for this app (cached for TTL seconds in the shared app)."""
    from . import tenancy
    if not tenancy.tenant_mode():
        return _truthy(os.environ.get(env_var))
    return value(key) == '1'


def value(key):
    """The console's value for `key` in the shared app (cached for TTL seconds), or None when it has none."""
    hit = _cache.get(key)
    if hit and time.time() - hit[1] < TTL:
        return hit[0]
    found = None
    try:
        with db.engine.connect() as conn:
            if conn.execute(text("SELECT to_regclass('public.console_state')")).scalar() is not None:
                found = conn.execute(text('SELECT value FROM public.console_state WHERE key = :k'),
                                     {'k': key}).scalar()
    except Exception:
        found = None
    _cache[key] = (found, time.time())
    return found


def set_switch(key, on):
    """The console's switch (the console's database is the trials database). Takes effect within TTL."""
    set_value(key, '1' if on else '0')


def set_value(key, value):
    with db.engine.begin() as conn:
        conn.execute(text('DELETE FROM public.console_state WHERE key = :k'), {'k': key})
        conn.execute(text('INSERT INTO public.console_state (key, value) VALUES (:k, :v)'), {'k': key, 'v': value})
    _cache.pop(key, None)


def console_value(key, raw=False):
    """The console's own reading of the switch (no cache); raw: the stored value, or None."""
    with db.engine.connect() as conn:
        found = conn.execute(text('SELECT value FROM public.console_state WHERE key = :k'), {'k': key}).scalar()
    return found if raw else found == '1'


def forget(key):
    _cache.pop(key, None)
