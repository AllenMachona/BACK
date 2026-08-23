from datetime import datetime, timedelta
import os
from flask import Blueprint, render_template, redirect, url_for, request, flash, abort, current_app, send_from_directory
from flask_login import login_required, current_user
from sqlalchemy.exc import IntegrityError
from app.extensions import db
from app.models.user import User
from app.models.role import Role
from app.models.bidder_compliance import BidderComplianceDocument
from app.utils.notify import send_email
from app.utils.decorators import permission_required
from app.utils.audit import log_action
from app.models.site_setting import SiteSetting
from app.models.notification import Notification
from app.utils.security import validate_email

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')


@admin_bp.route('/settings', methods=['GET', 'POST'])
@login_required
@permission_required('can_admin_system')
def settings():
    SiteSetting.ensure_defaults()
    settings_rows = SiteSetting.query.order_by(SiteSetting.label).all()

    if request.method == 'POST':
        boolean_keys = {
            'maintenance_mode', 'allow_registration', 'supplier_approval_required',
            'supplier_verification_required', 'enable_email', 'enable_system_notifications',
            'enable_supplier_registration', 'enable_bid_submission', 'enable_notifications',
            'enable_audit_log', 'require_password_uppercase', 'require_password_number',
            'require_password_special',
        }
        numeric_keys = {
            'deadline_reminder_days', 'direct_procurement_threshold',
            'open_procurement_threshold', 'lot_splitting_warning_threshold',
            'max_upload_size_mb', 'session_lifetime_hours', 'login_max_attempts',
            'login_lockout_minutes', 'password_expiry_days', 'notification_retention_days',
            'approval_levels', 'bid_submission_deadline_min_hours', 'workflow_escalation_days',
            'smtp_port', 'minimum_password_length', 'document_retention_days',
        }
        for key, value in request.form.items():
            if key == 'csrf_token':
                continue
            setting = SiteSetting.query.filter_by(key=key).first()
            if not setting:
                continue
            value = value.strip()
            if key in boolean_keys and value not in {'true', 'false'}:
                flash(f'{setting.label} must be enabled or disabled.', 'danger')
                return redirect(url_for('admin.settings'))
            if key in numeric_keys:
                try:
                    number = float(value)
                    limits = {
                        'max_upload_size_mb': (1, 2048), 'session_lifetime_hours': (1, 168),
                        'login_max_attempts': (3, 20), 'login_lockout_minutes': (1, 1440),
                        'password_expiry_days': (1, 730), 'notification_retention_days': (30, 3650),
                        'minimum_password_length': (8, 128), 'smtp_port': (1, 65535),
                        'approval_levels': (1, 10), 'bid_submission_deadline_min_hours': (1, 8760),
                        'workflow_escalation_days': (1, 365), 'document_retention_days': (30, 36500),
                    }
                    minimum, maximum = limits.get(key, (0, 365 if key == 'deadline_reminder_days' else None))
                    if number < minimum or (maximum is not None and number > maximum):
                        raise ValueError
                except ValueError:
                    flash(f'{setting.label} must be a valid non-negative value.', 'danger')
                    return redirect(url_for('admin.settings'))
            if key in {'support_email', 'sender_email'} and value and not validate_email(value):
                flash(f'{setting.label} must be a valid email address.', 'danger')
                return redirect(url_for('admin.settings'))
            if key == 'enable_audit_log' and value != 'true':
                flash('Audit logging is mandatory and cannot be disabled.', 'danger')
                return redirect(url_for('admin.settings'))
            if key == 'email_encryption' and value not in {'none', 'tls', 'ssl'}:
                flash('Email Encryption must be none, tls, or ssl.', 'danger')
                return redirect(url_for('admin.settings'))
            setting.value = value
        db.session.commit()
        if 'max_upload_size_mb' in request.form:
            current_app.config['MAX_CONTENT_LENGTH'] = int(float(request.form['max_upload_size_mb'])) * 1024 * 1024
        if 'session_lifetime_hours' in request.form:
            current_app.permanent_session_lifetime = timedelta(hours=int(float(request.form['session_lifetime_hours'])))
        if 'smtp_host' in request.form:
            current_app.config['MAIL_SERVER'] = request.form['smtp_host'].strip()
        if 'smtp_port' in request.form:
            current_app.config['MAIL_PORT'] = int(float(request.form['smtp_port']))
        if 'email_encryption' in request.form:
            encryption = request.form['email_encryption']
            current_app.config['MAIL_USE_TLS'] = encryption == 'tls'
            current_app.config['MAIL_USE_SSL'] = encryption == 'ssl'
        if 'sender_email' in request.form:
            current_app.config['MAIL_DEFAULT_SENDER'] = request.form['sender_email'].strip()
        current_app.config['MAIL_CONFIGURED'] = bool(
            current_app.config.get('MAIL_SERVER') and current_app.config.get('MAIL_DEFAULT_SENDER')
        )
        log_action('SYSTEM_SETTINGS_UPDATED', entity_type='SiteSetting',
                   new_value={key: request.form.get(key) for key in request.form if key != 'csrf_token'})
        flash('System settings updated successfully.', 'success')
        return redirect(url_for('admin.settings'))

    mail_status = {
        'configured': bool(current_app.config.get('MAIL_CONFIGURED')),
        'server': current_app.config.get('MAIL_SERVER') or 'Not configured',
        'sender': current_app.config.get('MAIL_DEFAULT_SENDER') or 'Not configured',
        'username_set': bool(current_app.config.get('MAIL_USERNAME')),
    }
    try:
        db.session.execute(db.text('SELECT 1'))
        database_status = 'Connected'
    except Exception:
        database_status = 'Unavailable'
    upload_folder = current_app.config.get('UPLOAD_FOLDER')
    upload_status = 'Available' if upload_folder and os.path.isdir(upload_folder) and os.access(upload_folder, os.W_OK) else 'Unavailable'
    encryption_status = 'Configured' if current_app.config.get('SUBMISSION_ENCRYPTION_KEY') else 'Missing'

    return render_template('admin_settings.html', settings_rows=settings_rows,
                           mail_status=mail_status, database_status=database_status,
                           upload_folder=upload_folder, upload_status=upload_status,
                           encryption_status=encryption_status)


@admin_bp.route('/settings/test-email', methods=['POST'])
@login_required
@permission_required('can_admin_system')
def test_email():
    recipient = request.form.get('recipient', '').strip().lower() or current_user.email
    if not validate_email(recipient):
        flash('Enter a valid test email address.', 'danger')
        return redirect(url_for('admin.settings'))
    if not current_app.config.get('MAIL_CONFIGURED'):
        flash('Email is not configured. Set MAIL_SERVER and MAIL_DEFAULT_SENDER in the deployment environment.', 'warning')
        return redirect(url_for('admin.settings'))
    sent = send_email(recipient, 'EBMS test email',
                      'This is a test email from EBMS. SMTP configuration is working.')
    if sent:
        flash(f'Test email sent to {recipient}.', 'success')
    else:
        flash('Test email failed. Check the server logs for the SMTP provider response.', 'danger')
    log_action('SYSTEM_TEST_EMAIL', entity_type='User', entity_id=current_user.id,
               new_value={'recipient': recipient, 'sent': sent})
    return redirect(url_for('admin.settings'))


@admin_bp.route('/maintenance/unlock-users', methods=['POST'])
@login_required
@permission_required('can_admin_system')
def unlock_users():
    count = User.query.filter(User.locked_until.isnot(None)).update({
        'locked_until': None, 'failed_login_attempts': 0,
    }, synchronize_session=False)
    db.session.commit()
    log_action('ADMIN_UNLOCKED_USERS', entity_type='User', new_value={'count': count})
    flash(f'{count} locked account(s) were unlocked.', 'success')
    return redirect(url_for('admin.settings'))


@admin_bp.route('/maintenance/clear-notifications', methods=['POST'])
@login_required
@permission_required('can_admin_system')
def clear_old_notifications():
    from datetime import timedelta
    retention_days = int(float(SiteSetting.get('notification_retention_days', '365')))
    cutoff = datetime.utcnow() - timedelta(days=retention_days)
    count = Notification.query.filter(
        Notification.created_at < cutoff, Notification.is_read == True
    ).delete(synchronize_session=False)
    db.session.commit()
    log_action('ADMIN_CLEARED_NOTIFICATIONS', entity_type='Notification', new_value={
        'count': count, 'retention_days': retention_days,
    })
    flash(f'{count} old read notification(s) were removed.', 'success')
    return redirect(url_for('admin.settings'))


@admin_bp.route('/users')
@login_required
@permission_required('can_admin_system')
def users():
    all_users = User.query.order_by(User.last_name).all()
    compliance_queue = BidderComplianceDocument.query.filter_by(status='pending').order_by(
        BidderComplianceDocument.submitted_at.asc()
    ).all()
    roles = Role.query.all()

    role_distribution = []
    for role in roles:
        count = User.query.filter_by(role_id=role.id).count()
        if count:
            role_distribution.append((role.name, count))

    mfa_enabled = User.query.filter_by(mfa_enabled=True).count()
    mfa_disabled = User.query.filter_by(mfa_enabled=False).count()
    locked = User.query.filter(User.locked_until.isnot(None), User.locked_until > datetime.utcnow()).count()

    return render_template(
        'admin_users.html', users=all_users, roles=roles,
        role_distribution=role_distribution, mfa_enabled=mfa_enabled,
        mfa_disabled=mfa_disabled, locked=locked, compliance_queue=compliance_queue,
    )


@admin_bp.route('/users/create', methods=['POST'])
@login_required
@permission_required('can_admin_system')
def create_user():
    role = Role.query.get(request.form.get('role_id', type=int))
    if not role:
        flash('Select a valid role.', 'danger')
        return redirect(url_for('admin.users'))

    username = request.form.get('username', '').strip()
    email = request.form.get('email', '').strip().lower()
    if not username or not email or not request.form.get('password'):
        flash('Username, email, and password are required.', 'danger')
        return redirect(url_for('admin.users'))

    if User.query.filter((User.username == username) | (User.email == email)).first():
        flash('A user with that username or email already exists.', 'danger')
        return redirect(url_for('admin.users'))

    if role.code == 'bidder':
        flash('Bidder accounts must be created through public registration.', 'danger')
        return redirect(url_for('admin.users'))

    user = User(
        username=username,
        email=email,
        first_name=request.form['first_name'],
        last_name=request.form['last_name'],
        department=request.form.get('department'),
        designation=request.form.get('designation'),
        role_id=role.id,
        created_by=current_user.id,
    )
    user.set_password(request.form['password'])
    db.session.add(user)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        flash('A user with that username or email already exists.', 'danger')
        return redirect(url_for('admin.users'))

    log_action('USER_CREATED', entity_type='User', entity_id=user.id, new_value={'username': user.username, 'role': role.code})
    flash(f'User {user.username} created.', 'success')
    return redirect(url_for('admin.users'))


@admin_bp.route('/users/<int:user_id>/toggle-active', methods=['POST'])
@login_required
@permission_required('can_admin_system')
def toggle_active(user_id):
    user = User.query.get_or_404(user_id)
    user.is_active = not user.is_active
    db.session.commit()
    log_action('USER_ACTIVE_TOGGLED', entity_type='User', entity_id=user.id, new_value={'is_active': user.is_active})
    flash(f'{user.username} is now {"active" if user.is_active else "deactivated"}.', 'success')
    return redirect(url_for('admin.users'))


@admin_bp.route('/bidder-compliance/<int:document_id>/download')
@login_required
@permission_required('can_admin_system')
def download_bidder_compliance(document_id):
    document = BidderComplianceDocument.query.get_or_404(document_id)
    directory, filename = os.path.split(document.file_path)
    return send_from_directory(directory, filename, as_attachment=True, download_name=document.original_filename)


@admin_bp.route('/bidder-compliance/<int:document_id>/review', methods=['POST'])
@login_required
@permission_required('can_admin_system')
def review_bidder_compliance(document_id):
    document = BidderComplianceDocument.query.get_or_404(document_id)
    decision = request.form.get('decision')
    notes = request.form.get('notes', '').strip()
    if decision not in {'approved', 'rejected'}:
        flash('Select a valid compliance decision.', 'danger')
        return redirect(url_for('admin.users'))
    if decision == 'rejected' and not notes:
        flash('A rejection reason is required.', 'danger')
        return redirect(url_for('admin.users'))

    user = document.bidder.portal_users.first()
    document.status = decision
    document.review_notes = notes or None
    document.reviewed_at = datetime.utcnow()
    document.reviewed_by_id = current_user.id
    document.bidder.active = decision == 'approved'
    document.bidder.verified = decision == 'approved'
    if user:
        user.is_active = decision == 'approved'
    db.session.commit()

    if user:
        outcome = 'activated' if decision == 'approved' else 'rejected'
        template_key = 'email_template_account_approved' if decision == 'approved' else 'email_template_account_rejected'
        template_text = SiteSetting.get(template_key, '')
        body = (
            f'Hello {user.full_name()},\n\n{template_text or f"Your EBMS Botswana bidder account has been {outcome}."}\n'
            f'{"You may now sign in and use the bidder portal." if decision == "approved" else f"Reason: {notes}"}\n\n'
            'Regards,\nEBMS Botswana System Administration'
        )
        email_sent = send_email(user.email, f'EBMS Botswana bidder account {outcome}', body)
    else:
        email_sent = False
    log_action('BIDDER_COMPLIANCE_REVIEWED', entity_type='BidderComplianceDocument', entity_id=document.id,
               new_value={'decision': decision, 'user_id': user.id if user else None})
    if email_sent:
        flash(f'Bidder account {decision}; notification email sent.', 'success')
    elif not current_app.config.get('MAIL_CONFIGURED'):
        flash(
            f'Bidder account {decision}, but email was not sent: configure '
            'MAIL_SERVER and MAIL_DEFAULT_SENDER in ebms_flask/.env, then restart the server.',
            'warning',
        )
    else:
        flash(
            f'Bidder account {decision}, but email delivery failed. '
            'Check the SMTP username and Gmail App Password in ebms_flask/.env.',
            'warning',
        )
    return redirect(url_for('admin.users'))
