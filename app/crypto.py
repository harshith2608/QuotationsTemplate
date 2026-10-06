"""
Encryption at rest for client data (customer details, amounts, rates, secrets).

    DATA_ENCRYPTION_KEY=<key>          required in production; one key per deployment
    DATA_ENCRYPTION_KEY=<new>,<old>    key rotation: encrypt with the first, read with any

Generate a key:
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

Values are stored as "enc1:<Fernet token>" (AES-128-CBC + HMAC-SHA256, random IV),
so the same value encrypts differently every time and the database can't search,
sort or add up these columns: the app does that in Python after decrypting.

Plain (not yet encrypted) values are still read correctly, so existing databases keep
working after the upgrade until `flask bootstrap` / `flask encrypt-data` encrypts them.
LOSING THE KEY MEANS LOSING THE DATA. Keep a copy outside Vercel (e.g. a password manager).
"""
import os
from contextlib import contextmanager
from contextvars import ContextVar

from sqlalchemy import Text
from sqlalchemy.types import TypeDecorator

PREFIX = 'enc1:'
ENV = 'DATA_ENCRYPTION_KEY'

_override = ContextVar('encryption_key_override', default=None)
_cache = {}


class EncryptionError(Exception):
    pass


def _keys_text():
    return (_override.get() or os.environ.get(ENV) or '').strip()


def _fernet():
    raw = _keys_text()
    if not raw:
        return None
    if raw not in _cache:
        from cryptography.fernet import Fernet, MultiFernet
        try:
            keys = [Fernet(k.strip().encode()) for k in raw.split(',') if k.strip()]
        except (ValueError, TypeError):
            raise EncryptionError(f'{ENV} is not a valid key. Generate one with: python -c "from cryptography.fernet '
                                  'import Fernet; print(Fernet.generate_key().decode())"') from None
        _cache[raw] = MultiFernet(keys)
    return _cache[raw]


def enabled():
    return bool(_keys_text())


def validate_key(raw):
    """Raise EncryptionError unless `raw` is a usable key (or comma-separated keys)."""
    token = _override.set(raw)
    try:
        if not raw or not raw.strip():
            raise EncryptionError('No key given.')
        _fernet()
    finally:
        _override.reset(token)


def is_encrypted(value):
    return isinstance(value, str) and value.startswith(PREFIX)


def encrypt(value):
    """Encrypt a string. Without a key (local development), values are stored as-is."""
    if value is None or is_encrypted(value):
        return value
    f = _fernet()
    if f is None:
        return value
    return PREFIX + f.encrypt(str(value).encode()).decode()


def decrypt(value):
    if not is_encrypted(value):
        return value
    f = _fernet()
    if f is None:
        raise EncryptionError(f'This data is encrypted but {ENV} is not set.')
    from cryptography.fernet import InvalidToken
    try:
        return f.decrypt(value[len(PREFIX):].encode()).decode()
    except InvalidToken:
        raise EncryptionError(f'This data was encrypted with a different key than {ENV}.') from None


@contextmanager
def using_key(raw):
    """Temporarily encrypt with another key (used when copying a trial into its own database)."""
    token = _override.set(raw)
    try:
        yield
    finally:
        _override.reset(token)


class EncryptedText(TypeDecorator):
    """A text column that is encrypted in the database."""
    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return None if value is None else encrypt(str(value))

    def process_result_value(self, value, dialect):
        return None if value is None else decrypt(value)


class EncryptedFloat(TypeDecorator):
    """A number column that is encrypted in the database (stored as text)."""
    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return None if value is None else encrypt(repr(float(value)))

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        value = decrypt(value)
        return float(value) if value != '' else None


# ── Encrypting existing plain data ───────────────────────────────────────────

def encrypted_columns(metadata):
    """[(table, [column names])] for every table with encrypted columns."""
    out = []
    for table in metadata.sorted_tables:
        cols = [c.name for c in table.columns if isinstance(c.type, (EncryptedText, EncryptedFloat))]
        if cols:
            out.append((table, cols))
    return out


def encrypt_existing(session, metadata, settings_keys=()):
    """Encrypt every value still stored in plain text. Safe to run any number of times.
    Returns {table: rows changed}."""
    from sqlalchemy import Text as PlainText, select, type_coerce
    if not enabled():
        return {}
    changed = {}
    for table, cols in encrypted_columns(metadata):
        # type_coerce reads the raw stored text (no decryption), so plain values can be spotted
        raw_cols = [type_coerce(table.c[c], PlainText).label(c) for c in cols]
        count = 0
        for row in session.execute(select(table.c.id, *raw_cols)).mappings().all():
            values = {}
            for c in cols:
                v = row[c]
                if v is None or is_encrypted(v):
                    continue
                values[c] = float(v) if isinstance(table.c[c].type, EncryptedFloat) else str(v)
            if values:      # the column types encrypt on write
                session.execute(table.update().where(table.c.id == row['id']).values(**values))
                count += 1
        if count:
            changed[table.name] = count
    if settings_keys:
        settings = metadata.tables['app_settings']
        count = 0
        for row in session.execute(select(settings).where(settings.c.key.in_(list(settings_keys)))).mappings().all():
            if row['value'] and not is_encrypted(row['value']):
                session.execute(settings.update().where(settings.c.key == row['key'])
                                .values(value=encrypt(row['value'])))
                count += 1
        if count:
            changed['app_settings'] = count
    return changed
