"""Enhanced messaging system supporting direct, broadcast, and targeted messages."""
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
    reply_to_id = db.Column(db.Integer, db.ForeignKey('messages.id'))
    
    # Audit
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    sender = db.relationship('User', foreign_keys=[sender_id], backref='sent_messages')
    recipients = db.relationship('MessageRecipient', backref='message', lazy='dynamic', cascade='all, delete-orphan')
    # Self-referential relationship for message threading
    replies = db.relationship('Message', remote_side=[reply_to_id], backref=db.backref('parent_message', remote_side=[id]))
    
    def __repr__(self):
        return f'<Message {self.id} type={self.message_type}>'


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
