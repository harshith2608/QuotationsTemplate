from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import check_password_hash
from .models import User
from .forms import LoginForm

auth_bp = Blueprint('auth', __name__)


def safe_next(default_endpoint='projects.list_projects'):
    """?next= only if it points to a page on this site (blocks open redirects to other domains)."""
    next_page = request.args.get('next', '')
    if not (next_page.startswith('/') and not next_page.startswith('//')) or next_page == '/':
        return url_for(default_endpoint)
    return next_page


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('projects.list_projects'))
    from .demo import demo_enabled
    if demo_enabled() and request.method == 'GET':
        # Public demo: never show a password form; sign the visitor straight in
        return redirect(url_for('demo.start', next=request.args.get('next') or None))
    form = LoginForm()
    if form.validate_on_submit():
        user = find_user(form.username.data)
        password = form.password.data or ''
        right = user and (check_password_hash(user.password_hash, password) or       # (or with a space a phone
                          (password != password.strip() and                          #  keyboard added at the end)
                           check_password_hash(user.password_hash, password.strip())))
        if not user:
            current_app.logger.info('Sign-in failed: no user %r', (form.username.data or '').strip()[:80])
        elif not right:
            current_app.logger.info('Sign-in failed: wrong password for %r', user.username)
        if right:
            login_user(user, remember=True)
            from .activity import record_login
            record_login()
            if user.is_admin and not request.args.get('next'):
                from . import db, welcome
                if welcome.start_on_first_login():          # a new business: the guided first setup
                    db.session.commit()
                    return redirect(url_for('welcome.resume'))
                welcome.note_sign_in()
            flash(f'Welcome back, {user.username}!', 'success')
            return redirect(safe_next())
        flash('Invalid username or password.', 'danger')
    return render_template('auth/login.html', form=form, title='Sign In')


def find_user(username):
    """The user signing in: the exact username, or else the same one in other capitals (a phone types "Admin" for
    "admin"). If two users differ only in capitals, only the exact one matches."""
    from sqlalchemy import func
    name = (username or '').strip()
    if not name:
        return None
    user = User.query.filter_by(username=name).first()
    if user:
        return user
    same = User.query.filter(func.lower(User.username) == name.lower()).limit(2).all()
    return same[0] if len(same) == 1 else None


@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    from .marketing import marketing_enabled
    return redirect(url_for('main.index') if marketing_enabled() else url_for('auth.login'))


@auth_bp.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    """Admins: a reset link to the business's email. Staff: ask your admin."""
    from . import password_reset as pr
    from .branding import support_contact
    from .demo import demo_enabled
    if current_user.is_authenticated:
        return redirect(url_for('projects.list_projects'))
    if demo_enabled():                            # the public demo has no passwords to reset
        return redirect(url_for('demo.start'))
    result, username = None, ''
    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()[:80]
        user = find_user(username) if username else None
        result = pr.send_link(user) if user and user.is_admin else 'not_admin'
    return render_template('auth/forgot.html', title='Forgot password', result=result, username=username,
                           email=pr.mask(pr.business_email()), support=support_contact())


@auth_bp.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    """The link from the email: choose a new password (the link then stops working)."""
    from werkzeug.security import generate_password_hash
    from . import db, password_reset as pr
    from .demo import demo_enabled
    if demo_enabled():
        return redirect(url_for('demo.start'))
    user = pr.read_token(token)
    if user is None:
        return render_template('auth/reset.html', title='Reset password', invalid=True), 400
    errors = {}
    if request.method == 'POST':
        password = request.form.get('password') or ''
        if len(password) < 8:
            errors['password'] = 'Use at least 8 characters.'
        elif password != request.form.get('password2'):
            errors['password2'] = "The passwords don't match."
        if not errors:
            user.password_hash = generate_password_hash(password, method='pbkdf2:sha256')
            db.session.commit()
            if current_user.is_authenticated:
                logout_user()
            flash('Password changed. Sign in with your new password.', 'success')
            return redirect(url_for('auth.login', u=user.username))
    return render_template('auth/reset.html', title='Reset password', user=user, errors=errors)
