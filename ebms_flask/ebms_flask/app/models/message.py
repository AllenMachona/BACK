"""Enhanced messaging system supporting direct, broadcast, and targeted messages."""
import os
from datetime import datetime
from app.extensions import db


class Message(db.Model):
    """Extended messaging model supporting direct, broadcast, and targeted communications.
    
    Replaces the simplified Notification model for message-specific use cases.
    Maintains full chronological history with delivery/read tracking.
    """
    __tablename__ = 'messages'

    id = db.Column(db.Integer, primary_key=True)
    
    # Sender information
    sender_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    
    # Message content
    subject = db.Column(db.String(200), nullable=False)
    body = db.Column(db.Text, nullable=False)
    
    # Message type: 'direct' (one user), 'broadcast' (all), 'targeted' (selected users/groups)
    message_type = db.Column(db.String(20), nullable=False, default='direct')
    
    # Optional context
    procurement_id = db.Column(db.Integer, db.ForeignKey('procurements.id'))
    communication_id = db.Column(db.Integer, db.ForeignKey('communications.id'))
    
    # Attachments
    attachment_path = db.Column(db.String(500))
    attachment_filename = db.Column(db.String(255))
    
    # Threading
    # thread_id points at the ROOT message of the conversation. A brand-new
    # conversation's first message is itself the root (thread_id == own id);
    # every follow-up message in the thread shares that same thread_id.
    reply_to_id = db.Column(db.Integer, db.ForeignKey('messages.id'))
    thread_id = db.Column(db.Integer, db.ForeignKey('messages.id'), index=True)

    # Audit
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    sender = db.relationship('User', foreign_keys=[sender_id], backref='sent_messages')
    recipients = db.relationship('MessageRecipient', backref='message', lazy='dynamic', cascade='all, delete-orphan')
    # Multiple file attachments (documents + images).
    attachments = db.relationship(
        'MessageAttachment', back_populates='message', lazy='select',
        cascade='all, delete-orphan',
    )
    # Self-referential relationship for message threading.
    # reply_to_id and thread_id BOTH reference messages.id, so the foreign key
    # must be given explicitly to disambiguate the joins.
    replies = db.relationship(
        'Message',
        foreign_keys=[reply_to_id],
        backref=db.backref('parent_message', remote_side=[id]),
    )

    def thread_root_id(self):
        """ID of the root message for this message's conversation thread."""
        return self.thread_id or self.id

    def is_thread_root(self):
        return (self.id == (self.thread_id or self.id))

    def participant_user_ids(self):
        """Unique user IDs involved in this thread (senders + recipients)."""
        ids = {self.sender_id}
        thread_id = self.thread_root_id()
        from app.models.message import Message
        from app.models.message import MessageRecipient
        messages = Message.query.filter(
            Message.thread_id == thread_id
        ).all()
        for m in messages:
            if m.sender_id:
                ids.add(m.sender_id)
            for r in m.recipients.all():
                if r.user_id:
                    ids.add(r.user_id)
                if r.bidder_id:
                    # Bidder-targeted messages resolve via the bidder's users
                    from app.models.bidder import Bidder
                    bidder = Bidder.query.get(r.bidder_id)
                    if bidder and bidder.users:
                        ids.update(u.id for u in bidder.users)
        return ids

    @classmethod
    def ensure_schema_columns(cls):
        """Add the thread_id column to pre-existing SQLite databases and
        backfill root values so old one-off messages become conversation roots."""
        from sqlalchemy import text
        try:
            db.session.execute(text('SELECT thread_id FROM messages LIMIT 1'))
        except Exception:
            try:
                db.session.execute(text('ALTER TABLE messages ADD COLUMN thread_id INTEGER'))
                db.session.commit()
            except Exception:
                db.session.rollback()
                return

        try:
            rows = cls.query.all()
            changed = False
            for m in rows:
                if not m.thread_id:
                    if m.reply_to_id:
                        parent = cls.query.get(m.reply_to_id)
                        if parent:
                            m.thread_id = parent.thread_id if parent.thread_id else parent.id
                        else:
                            m.thread_id = m.id
                    else:
                        m.thread_id = m.id
                    changed = True
            if changed:
                db.session.commit()
        except Exception:
            db.session.rollback()

    def __repr__(self):
        return f'<Message {self.id} type={self.message_type} thread={self.thread_id}>'


class MessageRecipient(db.Model):
    """Tracks individual message recipients with delivery and read status.
    
    Supports flexible targeting:
    - user_id set: direct message to specific user
    - bidder_id set: message to all users of a bidder company
    - role_id set: message to all users with a specific role
    - None: broadcast to all active users
    """
    __tablename__ = 'message_recipients'

    id = db.Column(db.Integer, primary_key=True)
    message_id = db.Column(db.Integer, db.ForeignKey('messages.id'), nullable=False, index=True)
    
    # Target - at least one should be set for targeted messages
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    bidder_id = db.Column(db.Integer, db.ForeignKey('bidders.id'))
    role_id = db.Column(db.Integer, db.ForeignKey('roles.id'))
    
    # Delivery tracking
    delivered_at = db.Column(db.DateTime)  # When message was delivered to inbox
    read_at = db.Column(db.DateTime, index=True)  # When recipient opened message
    
    # Archive/deletion (soft delete)
    archived_at = db.Column(db.DateTime)  # Recipient-side archive
    
    # Audit
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    user = db.relationship('User', foreign_keys=[user_id], backref='received_messages')
    bidder = db.relationship('Bidder', foreign_keys=[bidder_id])
    role = db.relationship('Role', foreign_keys=[role_id])

    def is_unread(self):
        return self.read_at is None and self.delivered_at is not None

    def is_read(self):
        return self.read_at is not None

    def __repr__(self):
        return f'<MessageRecipient message={self.message_id} user={self.user_id} read={self.is_read()}>'


class MessageAttachment(db.Model):
    """A file attached to a message (documents like PDF/DOCX/XLSX, and images).

    Each message may carry zero or more attachments, stored under
    ``UPLOAD_FOLDER/message_attachments``. ``stored_name`` is the unique,
    sanitised filename on disk while ``filename`` preserves the original
    saved name shown to users in the UI.
    """
    __tablename__ = 'message_attachments'

    id = db.Column(db.Integer, primary_key=True)
    message_id = db.Column(db.Integer, db.ForeignKey('messages.id'), nullable=False, index=True)

    # Original user-facing filename (used for download_name)
    filename = db.Column(db.String(255), nullable=False)
    # Sanitised, unique name the file is actually stored under
    stored_name = db.Column(db.String(255), nullable=False)
    # MIME type (e.g. application/pdf) — used for safe serving + file-type icons
    file_type = db.Column(db.String(100), nullable=False, default='application/octet-stream')
    # Size in bytes (used for validation + UI display)
    file_size = db.Column(db.Integer, nullable=False, default=0)
    # Absolute path on disk
    storage_path = db.Column(db.String(500), nullable=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    message = db.relationship('Message', back_populates='attachments')

    @property
    def extension(self):
        return os.path.splitext(self.filename or '')[1].lstrip('.').lower()

    def __repr__(self):
        return f'<MessageAttachment {self.id} message={self.message_id} {self.filename}>'
