import hashlib
import os
from datetime import datetime
from flask import Flask, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager
from flask_wtf.csrf import CSRFProtect
from whitenoise import WhiteNoise
from config import config

db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
csrf = CSRFProtect()
_asset_versions = {}

login_manager.login_view = 'auth.login'
login_manager.login_message = 'Please log in to access this page.'
login_manager.login_message_category = 'warning'


def create_app(config_name='default'):
    cfg = config[config_name]
    missing = [k for k in getattr(cfg, 'REQUIRED_ENV', ()) if not os.environ.get(k)]
    if missing:
        raise RuntimeError(f"Missing required environment variable(s): {', '.join(missing)}")
    from . import crypto
    if crypto.enabled():
        crypto.validate_key(os.environ[crypto.ENV])   # fail at startup, not on the first save

    app = Flask(__name__, template_folder='../templates', static_folder='../static')
    app.config.from_object(cfg)

    db.init_app(app)
    migrate.init_app(app, db)

    # Shared trials app: pick the tenant schema from the Host before any other hook queries the DB
    from . import tenancy
    if tenancy.tenant_mode() and not tenancy.base_domain():
        raise RuntimeError('TENANT_MODE needs TENANT_BASE_DOMAIN (e.g. quote-room.co.in).')
    login_manager.init_app(app)
    csrf.init_app(app)

    # Operator console deployment: serves only the console (no business app, no tenants)
    from .console import console_mode
    if console_mode():
        if tenancy.tenant_mode():
            raise RuntimeError('CONSOLE_MODE and TENANT_MODE cannot both be on.')
        if config_name == 'production':
            missing = [k for k in ('CONSOLE_PASSWORD_HASH', 'CONSOLE_TOTP_SECRET') if not os.environ.get(k)]
            if missing:
                raise RuntimeError(f"Missing required environment variable(s): {', '.join(missing)}")
        from .console import console_bp
        app.config['SESSION_COOKIE_NAME'] = 'qr_console'
        app.register_blueprint(console_bp)
        from .cli import register_cli
        register_cli(app)
        return app

    app.before_request(tenancy.resolve_tenant)

    from .auth import auth_bp
    from .main import main_bp
    from .projects import projects_bp
    from .admin_bp import admin_bp
    from .api import api_bp
    from .marketing import marketing_bp
    from .demo import demo_bp, block_demo_writes, demo_enabled
    from .marketing import marketing_enabled

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(projects_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(marketing_bp)
    app.register_blueprint(demo_bp)
    from .share import share_bp
    from .billing_bp import billing_bp
    app.register_blueprint(share_bp)
    app.register_blueprint(billing_bp)
    app.before_request(block_demo_writes)
    from .demo import count_demo_use
    app.after_request(count_demo_use)
    from .plan import enforce_read_only
    app.before_request(enforce_read_only)
    from .activity import touch
    app.before_request(touch)

    # Serve static files efficiently in production (Gunicorn doesn't serve them)
    # autorefresh=True in development so edited JS/CSS is served without restart
    is_dev = config_name in ('development', 'default')
    app.wsgi_app = WhiteNoise(app.wsgi_app, root='static/', prefix='static',
                              autorefresh=is_dev)

    # Razorpay webhook is called by Razorpay servers — exempt from CSRF
    from .projects import razorpay_webhook
    csrf.exempt(razorpay_webhook)
    # Public trial form: no login or session involved; protected by a honeypot and a rate limit instead
    from .marketing import trial_request
    csrf.exempt(trial_request)

    @app.template_global()
    def asset_url(filename):
        """Static URL with a content-hash query string, so browsers refetch CSS/JS after each deploy."""
        if filename not in _asset_versions:
            try:
                with open(os.path.join(app.static_folder, filename), 'rb') as fh:
                    _asset_versions[filename] = hashlib.sha1(fh.read()).hexdigest()[:10]
            except OSError:
                _asset_versions[filename] = ''
            if is_dev:
                version = _asset_versions.pop(filename)  # re-hash on every request while developing
                return url_for('static', filename=filename, v=version)
        return url_for('static', filename=filename, v=_asset_versions[filename])

    @app.template_filter('ist_time')
    def ist_time_filter(dt, fmt='%d %b %Y, %I:%M %p'):
        """A stored (UTC) time shown in Indian time."""
        from datetime import timedelta
        return (dt + timedelta(hours=5, minutes=30)).strftime(fmt) if dt else ''

    @app.template_filter('ft_in')
    def ft_in_filter(decimal_ft):
        """A stored size (decimal feet) in the business's unit (Settings → Units): '7 ft 6 in', '2286 mm'…"""
        from . import units
        return units.length(decimal_ft) or '—'

    @app.template_filter('area')
    def area_filter(sqft, dp=2):
        """A stored area (sqft) in the business's unit: '50.00 sqft' or '4.65 sq m'."""
        from . import units
        return units.area(sqft, dp)

    @app.template_filter('rate')
    def rate_filter(per_sqft):
        """A stored rate (₹ per sqft) per the business's area unit, as a number."""
        from . import units
        return units.rate_value(per_sqft)

    @app.context_processor
    def inject_globals():
        from flask_login import current_user
        unread_count = 0
        if current_user.is_authenticated and current_user.is_admin:
            try:
                from .models import Notification
                unread_count = Notification.query.filter_by(is_read=False).count()
            except Exception:
                pass
        from . import catalog, units
        from .branding import get_brand
        return {'now': datetime.utcnow(), 'unread_notifications_count': unread_count, 'units': units,
                'brand': get_brand(), 'catalog': catalog, 'demo_mode': demo_enabled(),
                'marketing_mode': marketing_enabled(), **_plan_context(current_user)}

    def _plan_context(user):
        from flask import request
        from .plan import load_status, renew_message_url
        status = load_status()
        if not status.has_limit:
            return {'plan': status, 'renew_url': ''}
        return {'plan': status, 'renew_url': renew_message_url(status, user, request.host_url)}

    from .cli import register_cli
    register_cli(app)

    return app
