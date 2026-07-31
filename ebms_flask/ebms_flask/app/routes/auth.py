import secrets
from datetime import datetime, timedelta
from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_user, logout_user, login_required, current_user
from app.extensions import db
from app.models.role import Role
from app.models.user import User
from app.utils.audit import log_action
from app.utils.notify import send_email

auth_bp = Blueprint('auth', __name__)

MAX_FAILED_ATTEMPTS = 5
LOCKOUT_MINUTES = 15


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.index'))

    if request.method == 'POST':
        identifier = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        user = User.query.filter((User.username == identifier) | (User.email == identifier.lower())).first()

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


@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.index'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip().lower()
        first_name = request.form.get('first_name', '').strip()
        last_name = request.form.get('last_name', '').strip()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')
        role_code = request.form.get('role_code', 'user_department')

        if not all([username, email, first_name, last_name, password]):
            flash('Please complete all required fields.', 'danger')
            return render_template('register.html')

        if password != confirm_password:
            flash('Passwords do not match.', 'danger')
            return render_template('register.html')

        if len(password) < 8:
            flash('Password must be at least 8 characters long.', 'danger')
            return render_template('register.html')

        if User.query.filter((User.username == username) | (User.email == email)).first():
            flash('A user with that username or email already exists.', 'danger')
            return render_template('register.html')

        role = Role.query.filter_by(code=role_code).first() or Role.query.filter_by(code='user_department').first()
        if not role:
            flash('No valid user role is available. Please contact support.', 'danger')
            return render_template('register.html')

        user = User(
            username=username,
            email=email,
            first_name=first_name,
            last_name=last_name,
            department=request.form.get('department', '').strip() or 'General',
            designation=request.form.get('designation', '').strip() or 'New User',
            role_id=role.id,
            is_active=True,
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()

        log_action('USER_REGISTERED', entity_type='User', entity_id=user.id,
                   new_value={'username': user.username, 'role': role.code})
        login_user(user)
        flash('Account created successfully. Welcome to EBMS.', 'success')
        return redirect(url_for('dashboard.index'))

    return render_template('register.html')


@auth_bp.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        user = User.query.filter_by(email=email).first()
        if user:
            token = user.generate_reset_token()
            db.session.commit()
            reset_url = url_for('auth.reset_password', token=token, _external=True)
            send_email(
                user.email,
                'Reset your EBMS password',
                f"Hello {user.full_name()},\n\nClick the link below to reset your password:\n\n{reset_url}\n\n"
                "This link expires in 1 hour. If you did not request this, you can ignore this message."
            )
        flash('If an account with that email exists, a reset link has been sent.', 'info')
        return redirect(url_for('auth.login'))

    return render_template('forgot_password.html')


@auth_bp.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    user = User.query.filter_by(reset_token=token).first()
    if not user or not user.reset_token_expires_at or user.reset_token_expires_at < datetime.utcnow():
        flash('This password reset link is invalid or expired.', 'danger')
        return redirect(url_for('auth.login'))

    if request.method == 'POST':
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')

        if len(password) < 8:
            flash('Password must be at least 8 characters long.', 'danger')
            return render_template('reset_password.html', token=token)

        if password != confirm_password:
            flash('Passwords do not match.', 'danger')
            return render_template('reset_password.html', token=token)

        user.set_password(password)
        user.clear_reset_token()
        db.session.commit()
        flash('Your password has been updated successfully. Please sign in.', 'success')
        return redirect(url_for('auth.login'))

    return render_template('reset_password.html', token=token)


@auth_bp.route('/account/settings', methods=['GET', 'POST'])
@login_required
def user_settings():
    if request.method == 'POST':
        current_user.set_preference('theme', request.form.get('theme', current_user.get_preference('theme', 'light')))
        current_user.set_preference('font_family', request.form.get('font_family', current_user.get_preference('font_family', 'Segoe UI')))
        current_user.set_preference('accent_color', request.form.get('accent_color', current_user.get_preference('accent_color', '#2563eb')))
        current_user.set_preference('compact_view', request.form.get('compact_view') == 'on')
        current_user.set_preference('show_tips', request.form.get('show_tips') == 'on')

        new_password = request.form.get('new_password', '').strip()
        confirm_password = request.form.get('confirm_password', '').strip()
        if new_password:
            if len(new_password) < 8:
                flash('Password must be at least 8 characters long.', 'danger')
                return redirect(url_for('auth.user_settings'))
            if new_password != confirm_password:
                flash('New password and confirmation do not match.', 'danger')
                return redirect(url_for('auth.user_settings'))
            current_user.set_password(new_password)
            flash('Password updated successfully.', 'success')

        db.session.commit()
        log_action('USER_SETTINGS_UPDATED', entity_type='User', entity_id=current_user.id, new_value=current_user.get_preferences())
        flash('Your personal settings were saved.', 'success')
        return redirect(url_for('auth.user_settings'))

    return render_template('user_settings.html', user=current_user)


@auth_bp.route('/logout')
@login_required
def logout():
    log_action('LOGOUT', entity_type='User', entity_id=current_user.id)
    logout_user()
    flash('You have been signed out.', 'info')
    return redirect(url_for('auth.login'))
