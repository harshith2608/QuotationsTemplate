import os
import secrets
from datetime import timedelta

from dotenv import load_dotenv

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

# Load .env for local development; real env vars always take precedence.
load_dotenv(os.path.join(BASE_DIR, '.env'))


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or secrets.token_hex(32)

    # Force psycopg2 dialect — SQLAlchemy 2.x defaults to psycopg3 for postgresql:// URLs
    # but only psycopg2-binary is installed.
    # Each deployment points DATABASE_URL at its own Postgres database.
    # The SQLite fallback is for local development only (production refuses to start without it).
    _db_url = os.environ.get('DATABASE_URL') or \
        'sqlite:///' + os.path.join(BASE_DIR, 'app.db')
    if _db_url.startswith('postgres://'):
        _db_url = _db_url.replace('postgres://', 'postgresql+psycopg2://', 1)
    elif _db_url.startswith('postgresql://'):
        _db_url = _db_url.replace('postgresql://', 'postgresql+psycopg2://', 1)
    SQLALCHEMY_DATABASE_URI = _db_url

    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # PostgreSQL connection pooling (ignored for SQLite)
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_size':    10,
        'max_overflow': 20,
        'pool_recycle': 1800,   # recycle connections every 30 min
        'pool_pre_ping': True,  # verify connection is alive before use
    }

    WTF_CSRF_ENABLED = True


class DevelopmentConfig(Config):
    DEBUG = True
    # Relax cookie security for local HTTP development
    SESSION_COOKIE_SECURE   = False
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    PERMANENT_SESSION_LIFETIME = timedelta(days=7)


class ProductionConfig(Config):
    DEBUG = False
    REQUIRED_ENV = ('SECRET_KEY', 'DATABASE_URL', 'DATA_ENCRYPTION_KEY')
    SESSION_COOKIE_SECURE   = True   # HTTPS only
    SESSION_COOKIE_HTTPONLY = True   # no JS access
    SESSION_COOKIE_SAMESITE = 'Lax'
    PERMANENT_SESSION_LIFETIME = timedelta(hours=12)


config = {
    'development': DevelopmentConfig,
    'production':  ProductionConfig,
    'default':     DevelopmentConfig
}
