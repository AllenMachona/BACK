from flask import Blueprint, render_template, redirect, url_for, jsonify, request, flash
from flask_login import login_required, current_user
from app.extensions import db
from app.models.notification import Notification
from app.models.user import User

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
            type='direct_message' if target_mode == 'user' else 'broadcast',
            title=title,
            body=f"{current_user.full_name()} says: {body}",
            is_read=False,
        )
        db.session.add(notification)

    db.session.commit()
    flash(f'Message sent to {len(recipients)} user(s).', 'success')
    return redirect(url_for('notifications.index'))


@notifications_bp.route('/unread-count')
@login_required
def unread_count():
    count = Notification.query.filter_by(user_id=current_user.id, is_read=False).count()
    return jsonify({'count': count})


@notifications_bp.route('/<int:notification_id>/read', methods=['POST'])
@login_required
def mark_read(notification_id):
    notification = Notification.query.get_or_404(notification_id)
    if notification.user_id != current_user.id:
        return jsonify({'error': 'Not found'}), 404
    notification.is_read = True
    db.session.commit()
    return redirect(url_for('notifications.index'))
