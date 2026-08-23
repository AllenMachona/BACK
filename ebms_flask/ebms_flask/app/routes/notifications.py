from flask import Blueprint, render_template, redirect, url_for, jsonify, request, flash
from flask_login import login_required, current_user
from app.extensions import db
from app.models.notification import Notification
from app.models.user import User
from app.utils.audit import log_action

notifications_bp = Blueprint('notifications', __name__, url_prefix='/notifications')


@notifications_bp.route('/')
@login_required
def index():
    items = Notification.query.filter_by(user_id=current_user.id).order_by(
        Notification.created_at.desc()
    ).limit(50).all()
    users = User.query.filter(User.id != current_user.id).order_by(User.first_name.asc(), User.last_name.asc()).all()
    return render_template('notifications.html', notifications=items, users=users)


@notifications_bp.route('/send', methods=['POST'])
@login_required
def send_message():
    title = (request.form.get('title') or 'Message from ' + current_user.full_name()).strip()
    body = (request.form.get('body') or '').strip()
    if not body:
        flash('Write a message before sending it.', 'danger')
        return redirect(url_for('notifications.index'))

    target_mode = request.form.get('target_mode', 'user')
    recipients = []

    if target_mode == 'all':
        recipients = User.query.filter(User.id != current_user.id).all()
    else:
        target_user_id = request.form.get('recipient_id')
        if not target_user_id:
            flash('Choose a recipient before sending a direct message.', 'danger')
            return redirect(url_for('notifications.index'))
        recipient = User.query.get(target_user_id)
        if not recipient or recipient.id == current_user.id:
            flash('That user cannot receive this message.', 'danger')
            return redirect(url_for('notifications.index'))
        recipients = [recipient]

    for user in recipients:
        notification = Notification(
            user_id=user.id,
            sender_id=current_user.id,
            type='direct_message' if target_mode == 'user' else 'broadcast',
            title=title,
            body=body,
            is_read=False,
        )
        db.session.add(notification)
        log_action('MESSAGE_SENT', entity_type='Notification', 
                  reason=f'to {user.username}')

    db.session.commit()
    flash(f'Message sent to {len(recipients)} user(s).', 'success')
    return redirect(url_for('notifications.index'))


@notifications_bp.route('/<int:notification_id>/reply', methods=['POST'])
@login_required
def reply_to_message(notification_id):
    """Reply to a specific message"""
    original_message = Notification.query.get_or_404(notification_id)
    
    # SECURITY: Only the recipient can reply to a message
    if original_message.user_id != current_user.id:
        flash('You cannot reply to this message.', 'danger')
        log_action('UNAUTHORIZED_REPLY_ATTEMPT', entity_type='Notification', 
                  entity_id=notification_id)
        return redirect(url_for('notifications.index'))
    
    body = (request.form.get('body') or '').strip()
    if not body:
        flash('Write a message before sending it.', 'danger')
        return redirect(url_for('notifications.index'))
    
    # Send reply back to original sender
    if original_message.sender_id:
        reply_notification = Notification(
            user_id=original_message.sender_id,
            sender_id=current_user.id,
            type='direct_message',
            title=f"Re: {original_message.title}",
            body=body,
            reply_to=original_message.id,
            is_read=False,
        )
        db.session.add(reply_notification)
        log_action('MESSAGE_REPLY_SENT', entity_type='Notification',
                  reason=f'reply to message {notification_id}')
        db.session.commit()
        flash('Reply sent successfully.', 'success')
    else:
        flash('Cannot reply to this message (original sender not found).', 'danger')
    
    return redirect(url_for('notifications.index'))


@notifications_bp.route('/unread-count')
@login_required
def unread_count():
    count = Notification.query.filter_by(user_id=current_user.id, is_read=False).count()
    return jsonify({'count': count})


@notifications_bp.route('/mark-all-read', methods=['POST'])
@login_required
def mark_all_read():
    count = Notification.query.filter_by(
        user_id=current_user.id,
        is_read=False,
    ).update({'is_read': True}, synchronize_session=False)
    db.session.commit()
    log_action('NOTIFICATIONS_MARKED_ALL_READ', entity_type='Notification', new_value={'count': count})
    flash(f'{count} notification(s) marked as read.', 'success')
    return redirect(url_for('notifications.index'))


@notifications_bp.route('/preview')
@login_required
def preview():
    """Recent notifications for the current user, for the bell preview dropdown."""
    limit = request.args.get('limit', 8, type=int)
    limit = max(1, min(limit, 15))
    items = Notification.query.filter_by(user_id=current_user.id).order_by(
        Notification.created_at.desc()
    ).limit(limit).all()

    result = []
    for n in items:
        snippet = (n.body or '').strip()
        result.append({
            'id': n.id,
            'type': n.type,
            'subject': n.title,
            'snippet': snippet[:140] + ('…' if len(snippet) > 140 else ''),
            'sender': n.sender.full_name() if n.sender else 'System',
            'created_fmt': n.created_at.strftime('%d %b, %I:%M %p'),
            'read': n.is_read,
            'read_url': url_for('notifications.mark_read', notification_id=n.id),
            'url': url_for('notifications.index'),
        })

    return jsonify({'items': result})


@notifications_bp.route('/<int:notification_id>/read', methods=['POST'])
@login_required
def mark_read(notification_id):
    notification = Notification.query.get_or_404(notification_id)
    if notification.user_id != current_user.id:
        return jsonify({'error': 'Not found'}), 404
    notification.is_read = True
    db.session.commit()
    log_action('MESSAGE_READ', entity_type='Notification', entity_id=notification_id)
    return redirect(url_for('notifications.index'))
