import secrets
from datetime import datetime, timedelta
from flask import Blueprint, render_template, redirect, url_for, request, flash, current_app
from flask_login import login_user, logout_user, login_required, current_user
from markupsafe import Markup, escape
from app.extensions import db
from app.models.bidder import Bidder
from app.models.role import Role
from app.models.user import User
from app.utils.audit import log_action
from app.utils.notify import send_email
from app.utils.security import sanitize_string, validate_email, validate_password_strength

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

        if user.has_role('bidder') and user.email_confirmation_token:
            if user.email_confirmation_valid():
                flash('Please confirm your email address using the link we sent you before signing in.', 'warning')
            else:
                flash('Your confirmation link has expired. Please register again.', 'danger')
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
        username = sanitize_string(request.form.get('username', '').strip(), max_length=80)
        email = sanitize_string(request.form.get('email', '').strip().lower(), max_length=120)
        first_name = sanitize_string(request.form.get('first_name', '').strip(), max_length=100)
        last_name = sanitize_string(request.form.get('last_name', '').strip(), max_length=100)
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')
        
        # SECURITY: Force bidder role only - prevent users from registering as other roles
        role_code = request.form.get('role_code', '').strip().lower()
        if role_code != 'bidder':
            flash('Invalid role selection. Only bidder registration is allowed.', 'danger')
            log_action('UNAUTHORIZED_REGISTRATION_ATTEMPT', entity_type='User', 
                      reason=f'attempted role: {role_code}')
            return render_template('register.html')

        # Validate all required fields
        department = sanitize_string(request.form.get('department', '').strip(), max_length=100)
        designation = sanitize_string(request.form.get('designation', '').strip(), max_length=100)
        
        if not all([username, email, first_name, last_name, password, department, designation]):
            flash('Please complete all required fields.', 'danger')
            return render_template('register.html')

        # SECURITY: Validate email format
        if not validate_email(email):
            flash('Please enter a valid email address.', 'danger')
            return render_template('register.html')

        if password != confirm_password:
            flash('Passwords do not match.', 'danger')
            return render_template('register.html')

        # SECURITY: Enforce strong password policy using utility
        is_valid, error_msg = validate_password_strength(password)
        if not is_valid:
            flash(error_msg, 'danger')
            return render_template('register.html')

        # Check for duplicate username/email
        if User.query.filter((User.username == username) | (User.email == email)).first():
            flash('A user with that username or email already exists.', 'danger')
            log_action('REGISTRATION_DUPLICATE_ATTEMPT', entity_type='User', 
                      reason=f'duplicate: {username}/{email}')
            return render_template('register.html')

        # Get bidder role - should always exist
        role = Role.query.filter_by(code='bidder').first()
        if not role:
            flash('Bidder role not configured. Please contact support.', 'danger')
            return render_template('register.html')

        # Public registration always creates a bidder company and a pending account.
        bidder = Bidder(
            company_name=department,
            contact_email=email,
            active=True,
            verified=False,
        )
        db.session.add(bidder)
        db.session.flush()

        user = User(
            username=username,
            email=email,
            first_name=first_name,
            last_name=last_name,
            department=department,
            designation=designation,
            role_id=role.id,
            bidder_id=bidder.id,
            is_active=False,
        )
        user.set_password(password)
        confirmation_token = user.generate_email_confirmation_token()
        db.session.add(user)
        db.session.commit()

        confirmation_url = url_for('auth.confirm_email', token=confirmation_token, _external=True)
        email_sent = send_email(
            user.email,
            'Confirm your EBMS Botswana bidder account',
            f"Hello {user.full_name()},\n\n"
            "Confirm your email address and activate your bidder account using this link:\n\n"
            f"{confirmation_url}\n\n"
            "This link expires in 24 hours. If you did not create this account, ignore this message.",
        )
        log_action('USER_REGISTERED', entity_type='User', entity_id=user.id,
                   new_value={'username': user.username, 'role': 'bidder', 'company': department})
        if email_sent:
            flash('Account created. Check your email and confirm your address before signing in.', 'success')
        elif not current_app.config.get('MAIL_CONFIGURED') and current_app.config.get('APP_ENV') != 'production':
            flash(Markup(
                'Email delivery is not configured for this development server. '
                f'<a href="{escape(confirmation_url)}">Confirm the bidder account here</a>.'
            ), 'warning')
        else:
            flash('Account created, but the confirmation email could not be sent. Please contact support.', 'warning')
        return redirect(url_for('auth.login'))

    return render_template('register.html')


@auth_bp.route('/confirm-email/<token>')
def confirm_email(token):
    user = User.query.filter_by(email_confirmation_token=token).first()
    if not user or not user.email_confirmation_valid():
        flash('This email confirmation link is invalid or expired. Please register again.', 'danger')
        return redirect(url_for('auth.login'))

    user.confirm_email()
    db.session.commit()
    log_action('EMAIL_CONFIRMED', entity_type='User', entity_id=user.id)
    flash('Your email has been confirmed and your bidder account is active. You can now sign in.', 'success')
    return redirect(url_for('auth.login'))


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

        mfa_requested = request.form.get('enable_mfa') == 'on'
        if mfa_requested and not current_user.mfa_secret:
            current_user.generate_mfa_secret()
            flash('MFA was enabled. Save the secret below in your authenticator app.', 'success')
        if not mfa_requested:
            current_user.mfa_enabled = False
            current_user.mfa_secret = None

        mfa_code = request.form.get('mfa_code', '').strip()
        if mfa_code and current_user.mfa_secret and not current_user.verify_mfa_code(mfa_code):
            flash('The MFA code you entered is not valid. Please try again.', 'danger')
            return redirect(url_for('auth.user_settings'))
        if mfa_requested and current_user.mfa_secret and not current_user.mfa_enabled:
            current_user.mfa_enabled = True

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

        current_user.mfa_enabled = bool(current_user.mfa_secret) and current_user.mfa_enabled
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
