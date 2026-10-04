from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import check_password_hash
from .models import User
from .forms import LoginForm

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('projects.list_projects'))
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data.strip()).first()
        if user and check_password_hash(user.password_hash, form.password.data):
            login_user(user, remember=True)
            next_page = request.args.get('next', '')
            # Only follow ?next= to a page on this site (blocks open redirects to other domains)
            if not (next_page.startswith('/') and not next_page.startswith('//')) or next_page == '/':
                next_page = url_for('projects.list_projects')
            flash(f'Welcome back, {user.username}!', 'success')
            return redirect(next_page)
        flash('Invalid username or password.', 'danger')
    return render_template('auth/login.html', form=form, title='Sign In')


@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    from .marketing import marketing_enabled
    return redirect(url_for('main.index') if marketing_enabled() else url_for('auth.login'))
