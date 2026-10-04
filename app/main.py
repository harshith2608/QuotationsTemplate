from flask import Blueprint, redirect, url_for, render_template, Response, abort, request, current_app
from flask_login import current_user
from .branding import get_brand, load_logo_png
from .marketing import marketing_enabled, render_landing

main_bp = Blueprint('main', __name__)


@main_bp.route('/')
def index():
    # On the product's own marketing deployment the domain root is always the sales page
    # (signed-in users get an "Open app" button there); everywhere else / is the app.
    if marketing_enabled():
        return render_landing()
    if current_user.is_authenticated:
        return redirect(url_for('projects.list_projects'))
    return current_app.login_manager.unauthorized()


_FAVICON_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16">'
    '<rect width="16" height="16" rx="3" fill="{color}"/>'
    '<path fill="white" d="M7.293 2.5a1 1 0 0 1 1.414 0l5 5a.5.5 0 0 1-.353.854L13 8.354V13a1 1 0 0 1-1 1H9.5'
    'a.5.5 0 0 1-.5-.5v-2H7v2a.5.5 0 0 1-.5.5H4a1 1 0 0 1-1-1V8.354l-.354.001a.5.5 0 0 1-.353-.854zM8 9'
    'c-.51 0-1 .23-1 .757C7 10.586 8 11.5 8 11.5s1-.914 1-1.743C9 9.23 8.51 9 8 9"/></svg>'
)


@main_bp.route('/favicon.svg')
def favicon():
    """Favicon drawn in the current primary brand colour (URL is versioned by base.html)."""
    svg = _FAVICON_SVG.format(color=get_brand()['primary'])
    return Response(svg, mimetype='image/svg+xml',
                    headers={'Cache-Control': 'public, max-age=86400'})


@main_bp.route('/brand/logo.png')
def brand_logo():
    """Logo uploaded in Admin → Settings. The ?v= version changes on every upload, so cache hard."""
    png = load_logo_png()
    if not png:
        abort(404)
    cache = 'public, max-age=31536000, immutable' if request.args.get('v') else 'no-cache'
    return Response(png, mimetype='image/png', headers={'Cache-Control': cache})


@main_bp.app_errorhandler(403)
def forbidden(e):
    return render_template('errors/403.html'), 403


@main_bp.app_errorhandler(404)
def not_found(e):
    return render_template('errors/404.html'), 404


@main_bp.app_errorhandler(500)
def internal_error(e):
    return render_template('errors/500.html'), 500
