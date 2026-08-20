"""Enhanced messaging routes supporting direct, broadcast, and targeted messages.

Extends the existing notification system with:
- Targeted message sending (to specific users/bidders/roles)
- Comprehensive delivery and read tracking
- Message history and threading
- Professional messaging interface
"""
from flask import Blueprint, render_template, redirect, url_for, request, jsonify, flash
from flask_login import login_required, current_user
from datetime import datetime
from app.extensions import db
from app.models.message import Message, MessageRecipient
from app.models.user import User
from app.models.bidder import Bidder
from app.models.role import Role
from app.utils.messaging import MessagingService
from app.utils.audit_enhanced import log_message_delivery, log_message_read

messages_bp = Blueprint('messages', __name__, url_prefix='/messages')


@messages_bp.route('/')
@login_required
def inbox():
    """User's message inbox with unread count."""
    page = request.args.get('page', 1, type=int)
    per_page = 20
    filter_type = request.args.get('filter', '').strip()

    base = MessageRecipient.query.filter(
        MessageRecipient.user_id == current_user.id,
        MessageRecipient.archived_at.is_(None),
    )
    if filter_type == 'unread':
        base = base.filter(MessageRecipient.read_at.is_(None))

    user_messages = base.order_by(MessageRecipient.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False)

    unread_count = MessageRecipient.query.filter(
        MessageRecipient.user_id == current_user.id,
        MessageRecipient.read_at.is_(None),
        MessageRecipient.archived_at.is_(None),
    ).count()

    # Get available recipients for composition
    users = User.query.filter(User.id != current_user.id, User.is_active.is_(True)).order_by(
        User.first_name, User.last_name
    ).all()

    bidders = Bidder.query.filter_by(active=True, suspended=False).all()
    roles = Role.query.all()

    return render_template(
        'messages/inbox.html',
        messages=user_messages.items,
        total_messages=user_messages.total,
        pages=user_messages.pages,
        page=user_messages.page,
        unread_count=unread_count,
        users=users,
        bidders=bidders,
        roles=roles,
        filter=filter_type,
    )


@messages_bp.route('/send', methods=['POST'])
@login_required
def send_message():
    """Send a message (direct, broadcast, or targeted)."""
    subject = (request.form.get('subject') or '').strip()
    body = (request.form.get('body') or '').strip()
    message_type = (request.form.get('message_type') or 'direct').strip()
    
    if not subject or not body:
        flash('Subject and message body are required.', 'danger')
        return redirect(url_for('messages.inbox'))
    
    try:
        if message_type == 'direct':
            recipient_id = request.form.get('recipient_id', type=int)
            if not recipient_id:
                flash('Please select a recipient.', 'danger')
                return redirect(url_for('messages.inbox'))
            
            recipient = User.query.get(recipient_id)
            if not recipient:
                flash('Recipient not found.', 'danger')
                return redirect(url_for('messages.inbox'))
            
            message = MessagingService.send_direct_message(
                subject=subject,
                body=body,
                recipient_id=recipient_id,
                reason='Direct message from user interface'
            )
            flash(f'Message sent to {recipient.full_name()}.', 'success')
        
        elif message_type == 'broadcast':
            message = MessagingService.send_broadcast_message(
                subject=subject,
                body=body,
                reason='Broadcast message from user interface'
            )
            flash('Message broadcast to all users.', 'success')
        
        elif message_type == 'targeted':
            user_ids = request.form.getlist('target_users[]', type=int)
            bidder_ids = request.form.getlist('target_bidders[]', type=int)
            role_ids = request.form.getlist('target_roles[]', type=int)
            
            if not (user_ids or bidder_ids or role_ids):
                flash('Please select at least one target.', 'danger')
                return redirect(url_for('messages.inbox'))
            
            message = MessagingService.send_targeted_message(
                subject=subject,
                body=body,
                user_ids=user_ids if user_ids else None,
                bidder_ids=bidder_ids if bidder_ids else None,
                role_ids=role_ids if role_ids else None,
                reason='Targeted message from user interface'
            )
            flash('Message sent to selected recipients.', 'success')
        
        else:
            flash('Invalid message type.', 'danger')
            return redirect(url_for('messages.inbox'))
        
        return redirect(url_for('messages.inbox'))
    
    except Exception as e:
        flash(f'Error sending message: {str(e)}', 'danger')
        return redirect(url_for('messages.inbox'))


@messages_bp.route('/<int:message_id>')
@login_required
def view_message(message_id):
    """View a single message with full thread."""
    message_recipient = MessageRecipient.query.filter_by(
        message_id=message_id,
        user_id=current_user.id
    ).first_or_404()
    
    message = message_recipient.message
    
    # Mark as read if not already
    if not message_recipient.read_at:
        message_recipient.read_at = datetime.utcnow()
        db.session.commit()
        log_message_read(message_id, current_user.id)
    
    # Get thread (replies)
    replies = Message.query.filter_by(reply_to_id=message_id).order_by(
        Message.created_at.asc()
    ).all()
    
    return render_template(
        'messages/view.html',
        message=message,
        message_recipient=message_recipient,
        replies=replies
    )


@messages_bp.route('/<int:message_id>/mark-read', methods=['POST'])
@login_required
def mark_read(message_id):
    """Mark a message as read."""
    message_recipient = MessageRecipient.query.filter_by(
        message_id=message_id,
        user_id=current_user.id
    ).first_or_404()
    
    if not message_recipient.read_at:
        message_recipient.read_at = datetime.utcnow()
        db.session.commit()
        log_message_read(message_id, current_user.id)
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'status': 'success'})
    
    return redirect(url_for('messages.inbox'))


@messages_bp.route('/<int:message_id>/archive', methods=['POST'])
@login_required
def archive_message(message_id):
    """Archive a message."""
    message_recipient = MessageRecipient.query.filter_by(
        message_id=message_id,
        user_id=current_user.id
    ).first_or_404()
    
    message_recipient.archived_at = datetime.utcnow()
    db.session.commit()
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'status': 'success'})
    
    flash('Message archived.', 'success')
    return redirect(url_for('messages.inbox'))


@messages_bp.route('/unread-count')
@login_required
def unread_count_api():
    """Get unread message count (JSON API)."""
    count = MessageRecipient.query.filter(
        MessageRecipient.user_id == current_user.id,
        MessageRecipient.read_at == None,
        MessageRecipient.archived_at == None
    ).count()
    return jsonify({'count': count})


@messages_bp.route('/search')
@login_required
def search():
    """Search messages."""
    query_str = request.args.get('q', '').strip()
    
    if not query_str or len(query_str) < 2:
        flash('Search query must be at least 2 characters.', 'warning')
        return redirect(url_for('messages.inbox'))
    
    # Search in messages where user is recipient
    results = db.session.query(MessageRecipient, Message).join(
        Message, Message.id == MessageRecipient.message_id
    ).filter(
        MessageRecipient.user_id == current_user.id,
        (Message.subject.ilike(f'%{query_str}%')) |
        (Message.body.ilike(f'%{query_str}%'))
    ).order_by(Message.created_at.desc()).all()
    
    return render_template('messages/search_results.html', results=results, query=query_str)


@messages_bp.route('/<int:message_id>/reply', methods=['POST'])
@login_required
def reply_to_message(message_id):
    """Reply to a message."""
    message_recipient = MessageRecipient.query.filter_by(
        message_id=message_id,
        user_id=current_user.id
    ).first_or_404()
    
    message = message_recipient.message
    body = (request.form.get('body') or '').strip()
    
    if not body:
        flash('Reply message cannot be empty.', 'danger')
        return redirect(url_for('messages.view_message', message_id=message_id))
    
    # Create reply message
    reply_message = Message(
        sender_id=current_user.id,
        subject=f"Re: {message.subject}",
        body=body,
        message_type='direct',
        reply_to_id=message_id,
        procurement_id=message.procurement_id
    )
    db.session.add(reply_message)
    db.session.flush()
    
    # Send to original sender
    if message.sender_id:
        recipient = MessageRecipient(
            message_id=reply_message.id,
            user_id=message.sender_id,
            delivered_at=datetime.utcnow()
        )
        db.session.add(recipient)
    
    db.session.commit()
    
    flash('Reply sent successfully.', 'success')
    return redirect(url_for('messages.view_message', message_id=message_id))
