"""Enhanced messaging routes supporting persistent threaded conversations.

Messages are grouped into conversation threads (rooted by ``thread_id`` on the
Message model). Both participants receive a recipient row so every message --
sent or received -- persists in each participant's inbox and survives reloads.

- Persistent conversation threads tied to a procurement (context preserved)
- Principle sends via AJAX with pending/error states and validation
- JSON polling endpoint for near-real-time message updates
- Accurate, dynamic unread counts per thread and globally
- Paginated, thread-grouped inbox
"""
from collections import OrderedDict
from flask import Blueprint, render_template, redirect, url_for, request, jsonify, flash, abort, current_app, send_from_directory
from flask_login import login_required, current_user
from datetime import datetime
from werkzeug.utils import secure_filename
import os
import secrets
from app.extensions import db
from app.models.message import Message, MessageRecipient, MessageAttachment
from app.models.user import User
from app.models.bidder import Bidder
from app.models.role import Role
from app.utils.messaging import MessagingService
from app.utils.audit_enhanced import log_message_delivery, log_message_read

messages_bp = Blueprint('messages', __name__, url_prefix='/messages')

# ---------------------------------------------------------------------------
# Attachment policy (reuses the existing UPLOAD_FOLDER pattern from
# procurements: subfolder + token-prefixed secure_filename)
# ---------------------------------------------------------------------------
# Max file size per attachment: 10 MB
MAX_MESSAGE_ATTACHMENT_BYTES = 10 * 1024 * 1024
# Max number of files per message
MAX_MESSAGE_ATTACHMENTS = 5
ALLOWED_MESSAGE_ATTACHMENT_EXTS = {
    'pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx',
    'txt', 'csv', 'png', 'jpg', 'jpeg', 'gif', 'webp',
}


def _attachment_ext(filename):
    return os.path.splitext(filename or '')[1].lstrip('.').lower()


def _save_message_attachment(file_storage):
    """Validate and persist one message attachment.

    Mirrors the procurement-document upload pattern (secure_filename +
    ``UPLOAD_FOLDER/<subfolder>`` + a random token prefix). Returns a dict
    describing the stored file, or raises ValueError on validation failure.
    """
    if not file_storage or not file_storage.filename:
        return None

    original = file_storage.filename
    ext = _attachment_ext(original)
    if ext not in ALLOWED_MESSAGE_ATTACHMENT_EXTS:
        raise ValueError(
            f"File type '.{ext}' is not allowed. Use one of: "
            + ', '.join(sorted(ALLOWED_MESSAGE_ATTACHMENT_EXTS))
        )

    file_storage.seek(0, os.SEEK_END)
    size = file_storage.tell()
    file_storage.seek(0)
    if size > MAX_MESSAGE_ATTACHMENT_BYTES:
        raise ValueError(
            f'"{original}" exceeds the {MAX_MESSAGE_ATTACHMENT_BYTES // (1024 * 1024)} MB attachment limit.'
        )

    att_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'message_attachments')
    os.makedirs(att_dir, exist_ok=True)
    stored_name = secure_filename(f"{current_user.id}_{secrets.token_hex(4)}_{original}")
    filepath = os.path.join(att_dir, stored_name)
    file_storage.save(filepath)

    return {
        'filename': original,
        'stored_name': stored_name,
        'storage_path': filepath,
        'file_type': file_storage.mimetype or 'application/octet-stream',
        'file_size': size,
    }


def _link_attachments(message_id, saved_attachments):
    """Persist MessageAttachment rows for a newly saved message."""
    for att in saved_attachments or []:
        db.session.add(MessageAttachment(
            message_id=message_id,
            filename=att['filename'],
            stored_name=att['stored_name'],
            file_type=att['file_type'],
            file_size=att['file_size'],
            storage_path=att['storage_path'],
        ))


def _delete_saved_files(saved_attachments):
    for att in saved_attachments or []:
        try:
            os.remove(att['storage_path'])
        except OSError:
            pass


def _all_recipient_snapshot(message):
    """List of recipient details for a message (excludes the sender self-copy).

    Returns (count, [ {name, role, read, read_at}, ... ]).
    """
    details = []
    for r in (message.recipients.all() if hasattr(message.recipients, 'all') else message.recipients):
        user = r.user
        if user is None or r.user_id == message.sender_id:
            continue
        details.append({
            'name': user.full_name(),
            'role': user.role.name if user.role else '—',
            'username': user.username,
            'read': r.read_at is not None,
            'read_at': r.read_at.strftime('%d %b %Y, %I:%M %p') if r.read_at else None,
            'delivered_at': r.delivered_at.strftime('%d %b %Y, %I:%M %p') if r.delivered_at else None,
        })
    return details


def _message_read_state(message):
    """Return whether every recipient has read a sent message."""
    recipients = [
        r for r in (message.recipients.all() if hasattr(message.recipients, 'all') else message.recipients)
        if r.user_id != message.sender_id
    ]
    return {
        'has_recipients': bool(recipients),
        'all_read': bool(recipients) and all(r.read_at is not None for r in recipients),
    }


def _is_thread_participant(thread_id, user_id):
    """Check whether a user is a participant (sender or recipient) in a thread."""
    messages = Message.query.filter(Message.thread_id == thread_id).all()
    if not messages:
        return False
    if any(m.sender_id == user_id for m in messages):
        return True
    ids = [m.id for m in messages]
    return MessageRecipient.query.filter(
        MessageRecipient.message_id.in_(ids),
        MessageRecipient.user_id == user_id,
        MessageRecipient.archived_at.is_(None),
    ).first() is not None


def _can_view_thread(thread_id):
    """Allow message managers to open threads found by global search."""
    return _is_thread_participant(thread_id, current_user.id) or bool(
        current_user.role and current_user.role.can_view_all_records
    )


def _thread_messages(thread_id):
    """Ordered list of messages in a thread (oldest first)."""
    return Message.query.filter(Message.thread_id == thread_id).order_by(
        Message.created_at.asc(), Message.id.asc()
    ).all()


def _root_message(messages):
    """The root/original message of a thread."""
    if not messages:
        return None
    return next((m for m in messages if m.id == (m.thread_id or m.id)), None) or messages[0]


def _mark_thread_read(thread_id, user_id):
    """Mark all of a user's unread recipient rows within a thread as read."""
    ids = [m.id for m in _thread_messages(thread_id)]
    if not ids:
        return
    rows = MessageRecipient.query.filter(
        MessageRecipient.message_id.in_(ids),
        MessageRecipient.user_id == user_id,
        MessageRecipient.read_at.is_(None),
    ).all()
    if rows:
        for r in rows:
            r.read_at = datetime.utcnow()
        db.session.commit()
        for r in rows:
            log_message_read(r.message_id, user_id)


@messages_bp.route('/')
@login_required
def inbox():
    """User's threaded message inbox with accurate unread counts."""
    page = request.args.get('page', 1, type=int)
    per_page = 10
    filter_type = request.args.get('filter', '').strip()

    base = MessageRecipient.query.filter(
        MessageRecipient.user_id == current_user.id,
        MessageRecipient.archived_at.is_(None),
    ).order_by(MessageRecipient.created_at.desc()).all()

    if filter_type == 'unread':
        base = [r for r in base if r.read_at is None]

    # Group recipient rows by their conversation thread root
    grouped = OrderedDict()
    for rec in base:
        root_id = rec.message.thread_root_id()
        grouped.setdefault(root_id, []).append(rec)

    conversations = []
    for root_id, recs in grouped.items():
        msgs = _thread_messages(root_id)
        root = _root_message(msgs) or recs[0].message
        last = msgs[-1] if msgs else recs[0].message
        unread = sum(1 for r in recs if r.read_at is None)

        if root.message_type == 'broadcast':
            label = 'Broadcast'
        elif root.message_type == 'targeted':
            label = 'Targeted'
        else:
            # The other participant (the party we are not)
            other_ids = [m.sender_id for m in msgs if m.sender_id != current_user.id]
            other_ids += [r.user_id for r in recs if r.user_id != current_user.id]
            other_ids = [uid for uid in other_ids if uid]
            other = User.query.get(other_ids[-1]) if other_ids else None
            label = other.full_name() if other else 'Unknown'

        conversations.append({
            'thread_id': root_id,
            'subject': root.subject,
            'label': label,
            'is_broadcast': root.message_type == 'broadcast',
            'is_targeted': root.message_type == 'targeted',
            'last_body': 'This message was unsent.' if last.unsent_at else last.body,
            'last_at': last.created_at,
            'unread': unread,
            'message_count': len(msgs),
            'procurement_id': root.procurement_id,
        })

    # Newest activity first
    conversations.sort(key=lambda c: c['last_at'], reverse=True)

    total = len(conversations)
    pages = max((total + per_page - 1) // per_page, 1) if total else 1
    page = min(max(page, 1), pages)
    start = (page - 1) * per_page
    page_items = conversations[start:start + per_page]

    unread_count = MessageRecipient.query.filter(
        MessageRecipient.user_id == current_user.id,
        MessageRecipient.read_at.is_(None),
        MessageRecipient.archived_at.is_(None),
    ).count()

    # Available recipients for composition
    all_users = User.query.filter(User.id != current_user.id, User.is_active == True).order_by(
        User.first_name, User.last_name
    ).all()
    all_bidders = Bidder.query.filter_by(active=True, suspended=False).all()
    all_roles = Role.query.all()

    return render_template(
        'messages/inbox.html',
        conversations=page_items,
        total_messages=total,
        pages=pages,
        page=page,
        unread_count=unread_count,
        all_users=all_users,
        all_bidders=all_bidders,
        all_roles=all_roles,
        filter=filter_type,
        prefill_procurement_id=request.args.get('procurement_id', type=int),
    )


@messages_bp.route('/send', methods=['POST'])
@login_required
def send_message():
    """Send a message (direct, broadcast, or targeted) as a new thread.

    Returns JSON for AJAX submissions so the UI can show pending/error states.
    """
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    subject = (request.form.get('subject') or '').strip()
    body = (request.form.get('body') or '').strip()
    message_type = (request.form.get('message_type') or 'direct').strip()
    procurement_id = request.form.get('procurement_id', type=int)

    def _fail(message):
        if is_ajax:
            return jsonify({'status': 'error', 'message': message}), 400
        flash(message, 'danger')
        return redirect(url_for('messages.inbox'))

    if not subject or not body:
        return _fail('Subject and message body are required.')

    saved_attachments = []
    try:
        # Persist + validate uploaded files (documents/images). Raise ValueError
        # on disallowed type / oversize; cleanup any already-saved files on error.
        uploads = request.files.getlist('attachments')
        if len(uploads) > MAX_MESSAGE_ATTACHMENTS:
            return _fail(f'You can attach at most {MAX_MESSAGE_ATTACHMENTS} files per message.')
        for f in uploads:
            saved = _save_message_attachment(f)
            if saved:
                saved_attachments.append(saved)

        if message_type == 'direct':
            recipient_id = request.form.get('recipient_user_id', type=int) or \
                request.form.get('recipient_id', type=int)
            if not recipient_id:
                return _fail('Please select a recipient.')

            recipient = User.query.get(recipient_id)
            if not recipient:
                return _fail('Recipient not found.')

            message = MessagingService.send_direct_message(
                subject=subject,
                body=body,
                recipient_id=recipient_id,
                procurement_id=procurement_id,
                reason='Direct message from user interface',
            )

        elif message_type == 'broadcast':
            message = MessagingService.send_broadcast_message(
                subject=subject,
                body=body,
                procurement_id=procurement_id,
                reason='Broadcast message from user interface',
            )

        elif message_type == 'targeted':
            user_ids = request.form.getlist('user_ids', type=int)
            bidder_ids = request.form.getlist('bidder_ids', type=int)
            role_ids = request.form.getlist('role_ids', type=int)
            # Backwards-compatible field names
            if not (user_ids or bidder_ids or role_ids):
                bidder_ids = request.form.getlist('target_bidders[]', type=int)
                role_ids = request.form.getlist('target_roles[]', type=int)
                user_ids = request.form.getlist('target_users[]', type=int)

            if not (user_ids or bidder_ids or role_ids):
                return _fail('Please select at least one target.')

            message = MessagingService.send_targeted_message(
                subject=subject,
                body=body,
                user_ids=user_ids or None,
                bidder_ids=bidder_ids or None,
                role_ids=role_ids or None,
                procurement_id=procurement_id,
                reason='Targeted message from user interface',
            )

        else:
            return _fail('Invalid message type.')

        # Link uploaded files to the newly-created message (multiple allowed).
        _link_attachments(message.id, saved_attachments)
        if saved_attachments:
            db.session.commit()

        if is_ajax:
            return jsonify({
                'status': 'ok',
                'message': 'Message sent.',
                'thread_id': message.thread_root_id(),
                'message_id': message.id,
            })

        flash('Message sent successfully.', 'success')
        return redirect(url_for('messages.thread_view', thread_id=message.thread_root_id()))

    except Exception as e:
        _delete_saved_files(saved_attachments)
        db.session.rollback()
        return _fail(f'Error sending message: {str(e)}')


@messages_bp.route('/thread/<int:thread_id>')
@login_required
def thread_view(thread_id):
    """Display a full conversation thread."""
    if not _can_view_thread(thread_id):
        abort(404)

    thread_msgs = _thread_messages(thread_id)
    root = _root_message(thread_msgs)
    if root is None:
        abort(404)

    # Opening the thread marks its messages as read
    _mark_thread_read(thread_id, current_user.id)

    # Per-message recipient snapshots for messages the current user sent
    # (broadcast/targeted/direct) so the sender can see who received it + status.
    recipient_map = {}
    for m in thread_msgs:
        if m.sender_id == current_user.id:
            recipient_map[m.id] = _all_recipient_snapshot(m)

    return render_template(
        'messages/view.html',
        thread_msgs=thread_msgs,
        root=root,
        thread_id=thread_id,
        recipient_map=recipient_map,
    )


@messages_bp.route('/thread/<int:thread_id>/messages')
@login_required
def thread_messages_api(thread_id):
    """JSON list of messages in a thread, used by the polling poll."""
    if not _can_view_thread(thread_id):
        return jsonify({'error': 'Not found'}), 404

    thread_msgs = _thread_messages(thread_id)
    return jsonify({'messages': [
        {
            'id': m.id,
            'sender_id': m.sender_id,
            'sender': m.sender.full_name() if m.sender else 'Unknown',
            'role': m.sender.role.name if m.sender and m.sender.role else 'User',
            'body': 'This message was unsent.' if m.unsent_at else m.body,
            'unsent': m.unsent_at is not None,
            'is_mine': m.sender_id == current_user.id,
            'read_state': _message_read_state(m) if m.sender_id == current_user.id else None,
            'created_at': m.created_at.strftime('%d %b %Y, %I:%M %p'),
            'attachments': [] if m.unsent_at else [
                {
                    'id': a.id,
                    'filename': a.filename,
                    'file_type': a.file_type,
                    'file_size': a.file_size,
                    'url': url_for('messages.download_attachment', attachment_id=a.id),
                }
                for a in m.attachments
            ],
        }
        for m in thread_msgs
    ]})


@messages_bp.route('/attachment/<int:attachment_id>/download')
@login_required
def download_attachment(attachment_id):
    """Download a message attachment (participants only)."""
    attachment = MessageAttachment.query.get_or_404(attachment_id)
    message = attachment.message
    if message.unsent_at:
        abort(404)
    if not _can_view_thread(message.thread_root_id()):
        abort(403)

    try:
        return send_from_directory(
            os.path.dirname(attachment.storage_path) or '.',
            os.path.basename(attachment.storage_path),
            as_attachment=True,
            download_name=attachment.filename,
            mimetype=attachment.file_type,
        )
    except OSError:
        abort(404)


@messages_bp.route('/preview')
@login_required
def preview():
    """Recent messages for the current user, for the nav-preview dropdown.

    Returns up to 8 recent threads (sent + received) with a short text
    snippet, sender, timestamp and unread state.
    """
    limit = request.args.get('limit', 8, type=int)
    limit = max(1, min(limit, 15))

    # Inbound (recipient rows) + outbound (sent) messages, newest first.
    inbound = [
        (r.created_at or r.message.created_at, r)
        for r in MessageRecipient.query.filter_by(
            user_id=current_user.id, archived_at=None
        ).all()
        if r.message is not None
    ]
    outbound = [
        (m.created_at, m) for m in Message.query.filter_by(
            sender_id=current_user.id
        ).all()
    ]

    # Collapse by thread root, keep most recent activity per thread.
    threads = {}
    for ts, r in inbound:
        m = r.message
        root_id = m.thread_root_id()
        item = {
            'is_outbound': False,
            'sender': m.sender.full_name() if m.sender else 'Unknown',
            'sender_role': m.sender.role.name if m.sender and m.sender.role else 'User',
            'subject': m.subject,
            'body': 'This message was unsent.' if m.unsent_at else m.body,
            'ts': ts,
            'created_fmt': m.created_at.strftime('%d %b, %I:%M %p'),
            'unread': r.read_at is None,
            'type': m.message_type,
            'thread_id': root_id,
        }
        if root_id not in threads or ts >= threads[root_id]['ts']:
            threads[root_id] = item

    for ts, m in outbound:
        root_id = m.thread_root_id()
        item = {
            'is_outbound': True,
            'sender': 'You',
            'sender_role': current_user.role.name if current_user.role else 'User',
            'subject': m.subject,
            'body': m.body,
            'ts': ts,
            'created_fmt': m.created_at.strftime('%d %b, %I:%M %p'),
            'unread': False,
            'type': m.message_type,
            'thread_id': root_id,
        }
        if root_id not in threads or ts >= threads[root_id]['ts']:
            threads[root_id] = item

    items = list(threads.values())
    items.sort(key=lambda x: x['ts'], reverse=True)
    items = items[:limit]

    for it in items:
        it.pop('ts', None)
        snippet = (it.get('body') or '').strip()
        it['snippet'] = snippet[:140] + ('…' if len(snippet) > 140 else '')

    return jsonify({'items': items})


@messages_bp.route('/thread/<int:thread_id>/reply', methods=['POST'])
@login_required
def reply_thread(thread_id):
    """Append a reply to a conversation thread (form + AJAX)."""
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    if not _is_thread_participant(thread_id, current_user.id):
        abort(404)

    thread_msgs = _thread_messages(thread_id)
    root = _root_message(thread_msgs)
    if root is None:
        abort(404)

    body = (request.form.get('body') or '').strip()

    def _fail(message):
        if is_ajax:
            return jsonify({'status': 'error', 'message': message}), 400
        flash(message, 'danger')
        return redirect(url_for('messages.thread_view', thread_id=thread_id))


    if not body:
        return _fail('Reply message cannot be empty.')

    saved_attachments = []
    try:
        uploads = request.files.getlist('attachments')
        if len(uploads) > MAX_MESSAGE_ATTACHMENTS:
            return _fail(f'You can attach at most {MAX_MESSAGE_ATTACHMENTS} files per message.')
        for f in uploads:
            saved = _save_message_attachment(f)
            if saved:
                saved_attachments.append(saved)

        reply = Message(
            sender_id=current_user.id,
            subject=f"Re: {root.subject}",
            body=body,
            message_type='direct',
            reply_to_id=root.id,
            thread_id=root.thread_root_id(),
            procurement_id=root.procurement_id,
        )
        db.session.add(reply)
        db.session.flush()

        _link_attachments(reply.id, saved_attachments)

        # Deliver to every other participant; keep a read self-copy
        participant_ids = root.participant_user_ids()
        now = datetime.utcnow()
        for uid in participant_ids:
            if uid == current_user.id:
                continue
            db.session.add(MessageRecipient(
                message_id=reply.id,
                user_id=uid,
                delivered_at=now,
            ))
        db.session.add(MessageRecipient(
            message_id=reply.id,
            user_id=current_user.id,
            delivered_at=now,
            read_at=now,
        ))

        db.session.commit()
        log_message_delivery(reply.id, max(len(participant_ids) - 1, 1), 'direct', 'Thread reply')

        if is_ajax:
            return jsonify({
                'status': 'ok',
                'message': 'Reply sent.',
                'message_id': reply.id,
                'sender': current_user.full_name(),
                'created_at': reply.created_at.strftime('%d %b %Y, %I:%M %p'),
                'attachments': [
                    {
                        'id': a.id,
                        'filename': a.filename,
                        'file_type': a.file_type,
                        'file_size': a.file_size,
                        'url': url_for('messages.download_attachment', attachment_id=a.id),
                    }
                    for a in reply.attachments
                ],
            })

        flash('Reply sent successfully.', 'success')
        return redirect(url_for('messages.thread_view', thread_id=thread_id))
    except Exception as e:
        _delete_saved_files(saved_attachments)
        db.session.rollback()
        return _fail(f'Error sending reply: {str(e)}')


@messages_bp.route('/<int:message_id>/unsend', methods=['POST'])
@login_required
def unsend_message(message_id):
    """Retract a message sent by the current user while retaining its history."""
    message = Message.query.get_or_404(message_id)
    if message.sender_id != current_user.id:
        abort(403)
    if not message.unsent_at:
        for attachment in message.attachments:
            try:
                os.remove(attachment.storage_path)
            except OSError:
                pass
            db.session.delete(attachment)
        message.unsent_at = datetime.utcnow()
        db.session.commit()

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'status': 'success', 'message': 'Message unsent.'})

    flash('Message unsent.', 'success')
    return redirect(url_for('messages.thread_view', thread_id=message.thread_root_id()))


@messages_bp.route('/<int:message_id>')
@login_required
def view_message(message_id):
    """Legacy route: redirect a message id to its conversation thread."""
    message = Message.query.get_or_404(message_id)
    return redirect(url_for('messages.thread_view', thread_id=message.thread_root_id()))


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

    term = f'%{query_str}%'
    matching_users = User.query.filter(
        User.is_active == True,
        (User.first_name.ilike(term)) |
        (User.last_name.ilike(term)) |
        (User.username.ilike(term)) |
        (User.email.ilike(term))
    ).order_by(User.first_name, User.last_name).all()
    matching_user_ids = [user.id for user in matching_users]
    message_text = Message.subject.ilike(term) | Message.body.ilike(term)
    user_match = Message.sender_id.in_(matching_user_ids) if matching_user_ids else False
    if matching_user_ids:
        user_match = user_match | Message.recipients.any(
            MessageRecipient.user_id.in_(matching_user_ids)
        )

    # Management users can search every message; other users remain limited
    # to messages they sent or received.
    search_filter = message_text | user_match
    if not (current_user.role and current_user.role.can_view_all_records):
        search_filter = search_filter & (
            (Message.sender_id == current_user.id) |
            Message.recipients.any(MessageRecipient.user_id == current_user.id)
        )

    messages = db.session.query(Message).filter(search_filter).distinct().order_by(
        Message.created_at.desc()
    ).all()
    results = [('global', message) for message in messages]

    return render_template(
        'messages/search_results.html',
        results=results,
        matching_users=matching_users,
        query=query_str,
    )


@messages_bp.route('/<int:message_id>/reply', methods=['POST'])
@login_required
def reply_to_message(message_id):
    """Legacy reply route: resolve the thread then reply within it."""
    message = Message.query.get_or_404(message_id)
    return reply_thread(message.thread_root_id())
