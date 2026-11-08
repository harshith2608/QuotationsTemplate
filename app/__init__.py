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

from flask_sqlalchemy.session import Session as _FlaskSession


class _TenantSession(_FlaskSession):
    """In the shared app, a paying customer's requests use their own database (tenancy.resolve_tenant sets
    g.tenant_engine); everything else uses the app's database as usual."""
    def get_bind(self, mapper=None, clause=None, bind=None, **kwargs):
        if bind is None:
            from flask import g, has_app_context
            engine = g.get('tenant_engine') if has_app_context() else None
            if engine is not None:
                return engine
        return super().get_bind(mapper=mapper, clause=clause, bind=bind, **kwargs)


db = SQLAlchemy(session_options={'class_': _TenantSession})
migrate = Migrate()
login_manager = LoginManager()
csrf = CSRFProtect()
_asset_versions = {}

login_manager.login_view = 'auth.login'
login_manager.login_message = 'Please log in to access this page.'
login_manager.login_message_category = 'warning'


HELP_CARD_SKIP = ('welcome.call', 'auth.login', 'auth.logout')   # a trial's admin sees "Get your rates set up for you"
                                                                 # on every other page, until they close it


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

    from flask_wtf.csrf import CSRFError

    @app.errorhandler(CSRFError)
    def _form_expired(exc):
        """A form refused (e.g. signed out meanwhile in another tab): back to the page with a note, not a bare error."""
        from flask import flash, jsonify, redirect, request
        message = 'That didn\'t go through because the page was out of date. Please try again.'
        if request.is_json or request.accept_mimetypes.best == 'application/json':
            return jsonify({'ok': False, 'error': message}), 400
        flash(message, 'warning')
        back = request.referrer or ''
        same_site = back.startswith(request.host_url)
        return redirect(back if same_site else '/')

    # A QA copy (QA_MODE=1: built from the dev branch, on its own database): behind the QA key, marked QA, not indexed
    from . import qa
    qa.init(app)

    # Operator console deployment: serves only the console (no business app, no tenants)
    from .plan import short as plan_short
    app.add_template_filter(plan_short, 'plan_short')   # '12 months with AI', '40 AI uses' (the app and the console)
    from .numbers import inr
    app.add_template_filter(inr, 'inr')                  # 15,50,000.00: numbers the Indian way, on every page
    from .materials import customer_label
    app.add_template_filter(customer_label, 'customer_material')   # "Laminate Finish", not "Laminates – Box Work"

    from .console import console_mode
    if console_mode():
        if tenancy.tenant_mode():
            raise RuntimeError('CONSOLE_MODE and TENANT_MODE cannot both be on.')
        if config_name == 'production':
            needed = ('CONSOLE_PASSWORD_HASH',) if qa.enabled() else ('CONSOLE_PASSWORD_HASH', 'CONSOLE_TOTP_SECRET')
            missing = [k for k in needed if not os.environ.get(k)]   # (the QA console: 2FA optional)
            if missing:
                raise RuntimeError(f"Missing required environment variable(s): {', '.join(missing)}")
        from .console import console_bp, platform_webhook
        app.config['SESSION_COOKIE_NAME'] = 'qr_console'
        app.register_blueprint(console_bp)
        csrf.exempt(platform_webhook)                  # Razorpay is the caller (signature-checked)
        from .cli import register_cli
        register_cli(app)
        return app

    app.before_request(tenancy.resolve_tenant)
    app.teardown_request(tenancy.release_tenant)

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
    from .plan_bp import plan_bp
    from .material_list_bp import material_list_bp
    from .ai_tools_bp import ai_tools_bp
    app.register_blueprint(share_bp)
    app.register_blueprint(material_list_bp)
    app.register_blueprint(ai_tools_bp)
    app.register_blueprint(billing_bp)
    app.register_blueprint(plan_bp)
    from .welcome_bp import welcome_bp
    app.register_blueprint(welcome_bp)
    app.before_request(block_demo_writes)
    from .demo import count_demo_use, count_site_visit
    app.after_request(count_demo_use)
    app.after_request(count_site_visit)
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
        from flask import request, session
        setup_banner = None
        if current_user.is_authenticated and current_user.is_admin and session.get('setup_step') and request.endpoint:
            from . import setup_guide             # only while following the setup guide
            setup_banner = setup_guide.banner(request.endpoint, request.args)
        welcome_bar = None
        if current_user.is_authenticated and current_user.is_admin and request.endpoint:
            from . import welcome                 # the guided first setup's strip on the app's own pages
            try:
                welcome_bar = welcome.bar(request.endpoint, request.view_args or {})
            except Exception:
                welcome_bar = None
        ai_import_on = material_list_on = False
        if current_user.is_authenticated and current_user.is_admin:
            from . import ai_import             # Bring your old quotation: one switch for every business
            ai_import_on = ai_import.available()
            if request.endpoint == 'admin.rates':
                from . import material_list     # the Material rules link: one switch for every business
                material_list_on = material_list.available()
        demo_guide = None
        if demo_enabled() and current_user.is_authenticated:
            from . import demo
            demo_guide = demo.guide()
        help_card = None
        if current_user.is_authenticated and current_user.is_admin and request.endpoint \
                and request.endpoint not in HELP_CARD_SKIP and not request.endpoint.startswith('static'):
            from . import callbook                # Get your rates set up for you: a call, or WhatsApp
            if callbook.available():
                help_card = {'booked': callbook.booked(), 'whatsapp': callbook.whatsapp_url()}
        from . import business
        from .marketing import call_url
        return {'biz': business.profile(), 'help_card': help_card, 'call_url': call_url(), 'demo_guide': demo_guide, 'ai_import_on': ai_import_on, 'material_list_on': material_list_on, 'now': datetime.utcnow(), 'unread_notifications_count': unread_count, 'units': units,
                'setup_banner': setup_banner, 'welcome_bar': welcome_bar,
                'brand': get_brand(), 'catalog': catalog, 'demo_mode': demo_enabled(),
                'marketing_mode': marketing_enabled(), **_plan_context(current_user)}

    @app.context_processor
    def _announcements():
        from flask_login import current_user
        from .announcements import for_user
        from .plan import load_status
        try:
            return {'announcements': for_user(load_status(), current_user)}
        except Exception:                            # a banner mustn't break a page
            app.logger.exception('Announcements could not be shown')
            return {'announcements': []}

    def _lower_price(status, user):
        """{'paying', 'now'} when this business's monthly autopay costs more than the plan's price today (it was
        lowered in the console's Pricing): admins see a banner until they restart the autopay at the new price."""
        if not (status.autopay and user.is_authenticated and user.is_admin):
            return None
        try:
            from . import pricing, subscription, tenancy
            sub = subscription.current_subscription(tenancy.current_slug())
            now = pricing.prices()[sub['plan']] if sub else None
            if sub and sub.get('amount_paise') and now and sub['amount_paise'] > now * 100:
                return {'paying': sub['amount_paise'] // 100, 'now': now}
        except Exception:
            pass
        return None

    def _plan_context(user):
        from flask import request
        from .plan import load_status, renew_message_url
        status = load_status()
        if not status.has_limit:
            return {'plan': status, 'renew_url': ''}
        from . import subscription
        if subscription.enabled():                   # pay in the app (Razorpay) instead of asking on WhatsApp
            return {'plan': status, 'renew_url': url_for('plan.plan_page'), 'renew_in_app': True,
                    'lower_price': _lower_price(status, user)}
        return {'plan': status, 'renew_url': renew_message_url(status, user, request.host_url)}

    from .cli import register_cli
    register_cli(app)

    return app
