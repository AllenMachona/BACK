from datetime import datetime, timedelta
from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_user, logout_user, login_required, current_user
from app.extensions import db
from app.models.user import User
from app.utils.audit import log_action

auth_bp = Blueprint('auth', __name__)

MAX_FAILED_ATTEMPTS = 5
LOCKOUT_MINUTES = 15


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.index'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        user = User.query.filter_by(username=username).first()

        if user and user.locked_until and user.locked_until > datetime.utcnow():
            flash('This account is temporarily locked due to repeated failed logins. Try again later.', 'danger')
            log_action('LOGIN_BLOCKED_LOCKED', entity_type='User', entity_id=user.id)
            return render_template('login.html')

        if not user or not user.check_password(password):
            if user:
                user.failed_login_attempts = (user.failed_login_attempts or 0) + 1
                if user.failed_login_attempts >= MAX_FAILED_ATTEMPTS:
                    user.locked_until = datetime.utcnow() + timedelta(minutes=LOCKOUT_MINUTES)
                db.session.commit()
            log_action('LOGIN_FAILED', entity_type='User', entity_id=user.id if user else None,
                       reason='bad credentials')
            flash('Invalid username or password.', 'danger')
            return render_template('login.html')

        if not user.is_active:
            flash('This account has been deactivated.', 'danger')
            return render_template('login.html')

        user.failed_login_attempts = 0
        user.locked_until = None
        user.last_login = datetime.utcnow()
        user.last_login_ip = request.remote_addr
        db.session.commit()

        login_user(user, remember=bool(request.form.get('remember')))
        log_action('LOGIN_SUCCESS', entity_type='User', entity_id=user.id)
        flash(f'Welcome back, {user.full_name()}.', 'success')
        return redirect(url_for('dashboard.index'))

    return render_template('login.html')


@auth_bp.route('/logout')
@login_required
def logout():
    log_action('LOGOUT', entity_type='User', entity_id=current_user.id)
    logout_user()
    flash('You have been signed out.', 'info')
    return redirect(url_for('auth.login'))
