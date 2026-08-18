"""Targeted messaging service supporting direct, broadcast, and targeted communications.

Handles message creation, recipient management, delivery tracking, and read status.
"""
from datetime import datetime
from flask_login import current_user
from app.extensions import db
from app.models.message import Message, MessageRecipient
from app.models.user import User
from app.models.bidder import Bidder
from app.models.role import Role
from app.utils.audit_enhanced import log_message_delivery, log_message_read


class MessagingService:
    """Service for sending and managing messages with comprehensive delivery tracking."""
    
    @staticmethod
    def send_direct_message(subject, body, recipient_id, attachment_path=None, 
                           attachment_filename=None, procurement_id=None, reason=None):
        """Send a direct message to a single user.
        
        Args:
            subject: Message subject
            body: Message body
            recipient_id: ID of the recipient user
            attachment_path: Optional file path
            attachment_filename: Optional file name
            procurement_id: Optional related procurement
            reason: Optional reason for audit
            
        Returns:
            Message object
        """
        message = Message(
            sender_id=current_user.id,
            subject=subject,
            body=body,
            message_type='direct',
            attachment_path=attachment_path,
            attachment_filename=attachment_filename,
            procurement_id=procurement_id,
        )
        db.session.add(message)
        db.session.flush()  # Get message ID
        
        # Add recipient
        recipient = MessageRecipient(
            message_id=message.id,
            user_id=recipient_id,
            delivered_at=datetime.utcnow()
        )
        db.session.add(recipient)
        db.session.commit()
        
        # Audit log
        log_message_delivery(message.id, 1, 'direct', reason)
        
        return message

    @staticmethod
    def send_broadcast_message(subject, body, attachment_path=None, 
                              attachment_filename=None, procurement_id=None, reason=None):
        """Send a broadcast message to all active users.
        
        Args:
            subject: Message subject
            body: Message body
            attachment_path: Optional file path
            attachment_filename: Optional file name
            procurement_id: Optional related procurement
            reason: Optional reason for audit
            
        Returns:
            Message object
        """
        message = Message(
            sender_id=current_user.id,
            subject=subject,
            body=body,
            message_type='broadcast',
            attachment_path=attachment_path,
            attachment_filename=attachment_filename,
            procurement_id=procurement_id,
        )
        db.session.add(message)
        db.session.flush()
        
        # Get all active users except sender
        recipients = User.query.filter(
            User.is_active == True,
            User.id != current_user.id
        ).all()
        
        # Add recipients
        for recipient_user in recipients:
            recipient = MessageRecipient(
                message_id=message.id,
                user_id=recipient_user.id,
                delivered_at=datetime.utcnow()
            )
            db.session.add(recipient)
        
        db.session.commit()
        
        # Audit log
        log_message_delivery(message.id, len(recipients), 'broadcast', reason)
        
        return message

    @staticmethod
    def send_targeted_message(subject, body, user_ids=None, bidder_ids=None, role_ids=None,
                             attachment_path=None, attachment_filename=None, 
                             procurement_id=None, reason=None):
        """Send a targeted message to selected users, bidders, or roles.
        
        Args:
            subject: Message subject
            body: Message body
            user_ids: List of user IDs to target
            bidder_ids: List of bidder IDs (sends to all users of those bidders)
            role_ids: List of role IDs (sends to all users with those roles)
            attachment_path: Optional file path
            attachment_filename: Optional file name
            procurement_id: Optional related procurement
            reason: Optional reason for audit
            
        Returns:
            Message object
        """
        message = Message(
            sender_id=current_user.id,
            subject=subject,
            body=body,
            message_type='targeted',
            attachment_path=attachment_path,
            attachment_filename=attachment_filename,
            procurement_id=procurement_id,
        )
        db.session.add(message)
        db.session.flush()
        
        # Collect all target users
        target_user_ids = set()
        
        # Direct user IDs
        if user_ids:
            target_user_ids.update(user_ids)
        
        # Users of target bidders
        if bidder_ids:
            bidder_users = User.query.filter(
                User.bidder_id.in_(bidder_ids),
                User.is_active == True
            ).all()
            target_user_ids.update(u.id for u in bidder_users)
        
        # Users with target roles
        if role_ids:
            role_users = User.query.filter(
                User.role_id.in_(role_ids),
                User.is_active == True
            ).all()
            target_user_ids.update(u.id for u in role_users)
        
        # Remove sender
        target_user_ids.discard(current_user.id)
        
        # Add recipients
        for user_id in target_user_ids:
            recipient = MessageRecipient(
                message_id=message.id,
                user_id=user_id,
                delivered_at=datetime.utcnow()
            )
            db.session.add(recipient)
        
        db.session.commit()
        
        # Audit log
        log_message_delivery(message.id, len(target_user_ids), 'targeted', reason)
        
        return message

    @staticmethod
    def get_user_inbox(user_id, unread_only=False, limit=50):
        """Get messages for a user.
        
        Args:
            user_id: User ID
            unread_only: If True, only return unread messages
            limit: Maximum number to return
            
        Returns:
            List of MessageRecipient objects with related Message data
        """
        query = MessageRecipient.query.filter(
            MessageRecipient.user_id == user_id,
            MessageRecipient.archived_at == None
        )
        
        if unread_only:
            query = query.filter(MessageRecipient.read_at == None)
        
        return query.order_by(MessageRecipient.created_at.desc()).limit(limit).all()

    @staticmethod
    def mark_as_read(message_recipient_id, user_id):
        """Mark a message as read.
        
        Args:
            message_recipient_id: ID of the MessageRecipient entry
            user_id: ID of the reading user (for security check)
            
        Returns:
            MessageRecipient object or None if unauthorized
        """
        recipient = MessageRecipient.query.get(message_recipient_id)
        
        if not recipient or recipient.user_id != user_id:
            return None
        
        if recipient.read_at is None:
            recipient.read_at = datetime.utcnow()
            db.session.commit()
            
            # Audit log
            log_message_read(recipient.message_id, user_id)
        
        return recipient

    @staticmethod
    def archive_message(message_recipient_id, user_id):
        """Archive a message (soft delete from user's inbox).
        
        Args:
            message_recipient_id: ID of the MessageRecipient entry
            user_id: ID of the user
            
        Returns:
            MessageRecipient object or None if unauthorized
        """
        recipient = MessageRecipient.query.get(message_recipient_id)
        
        if not recipient or recipient.user_id != user_id:
            return None
        
        recipient.archived_at = datetime.utcnow()
        db.session.commit()
        
        return recipient

    @staticmethod
    def get_unread_count(user_id):
        """Get count of unread messages for a user.
        
        Args:
            user_id: User ID
            
        Returns:
            Number of unread messages
        """
        return MessageRecipient.query.filter(
            MessageRecipient.user_id == user_id,
            MessageRecipient.read_at == None,
            MessageRecipient.archived_at == None
        ).count()
