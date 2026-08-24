"""Clarification visibility and access control service.

Manages which bidders can access which clarification documents.
Enforces backend access control to prevent IDOR vulnerabilities.
"""
from datetime import datetime
from flask_login import current_user
from app.extensions import db
from app.models.clarification import ClarificationVisibility, ClarificationAccess
from app.models.communication import Communication
from app.utils.audit_enhanced import log_clarification_visibility_change


class ClarificationAccessService:
    """Service for managing clarification visibility and access."""
    
    @staticmethod
    def can_bidder_view_clarification(communication_id, bidder_id):
        """Check if a bidder can view a clarification (server-side enforcement).
        
        THIS CHECK IS ALWAYS ENFORCED - NEVER TRUST FRONTEND.
        
        Args:
            communication_id: Communication ID
            bidder_id: Bidder ID
            
        Returns:
            True if bidder can view, False otherwise
        """
        # Get the communication
        comm = Communication.query.get(communication_id)
        if not comm:
            return False
        
        # Use the communication's built-in check
        return comm.can_bidder_view(bidder_id)

    @staticmethod
    def grant_clarification_access(communication_id, bidder_id, reason=None):
        """Grant a bidder access to a targeted clarification.
        
        Args:
            communication_id: Communication ID
            bidder_id: Bidder ID to grant access to
            reason: Reason for granting access
            
        Returns:
            ClarificationVisibility object
        """
        # Check if access already exists
        existing = ClarificationVisibility.query.filter_by(
            communication_id=communication_id,
            bidder_id=bidder_id
        ).first()
        
        if existing:
            if existing.revoked_at:
                # Re-grant revoked access
                existing.revoked_at = None
                existing.revoked_by_id = None
                existing.revocation_reason = None
                db.session.commit()
                visibility = existing
            else:
                # Already has access
                return existing
        else:
            # Create new access
            visibility = ClarificationVisibility(
                communication_id=communication_id,
                bidder_id=bidder_id,
                granted_by_id=current_user.id if current_user.is_authenticated else None
            )
            db.session.add(visibility)
            db.session.commit()
        
        # Audit log
        log_clarification_visibility_change(
            communication_id=communication_id,
            bidder_id=bidder_id,
            action='grant',
            reason=reason
        )
        
        return visibility

    @staticmethod
    def revoke_clarification_access(communication_id, bidder_id, reason=None):
        """Revoke a bidder's access to a clarification.
        
        Args:
            communication_id: Communication ID
            bidder_id: Bidder ID to revoke access from
            reason: Reason for revocation
            
        Returns:
            ClarificationVisibility object or None
        """
        visibility = ClarificationVisibility.query.filter_by(
            communication_id=communication_id,
            bidder_id=bidder_id
        ).filter(ClarificationVisibility.revoked_at.is_(None)).first()
        
        if not visibility:
            return None
        
        visibility.revoked_at = datetime.utcnow()
        visibility.revoked_by_id = current_user.id if current_user.is_authenticated else None
        visibility.revocation_reason = reason
        db.session.commit()
        
        # Audit log
        log_clarification_visibility_change(
            communication_id=communication_id,
            bidder_id=bidder_id,
            action='revoke',
            reason=reason
        )
        
        return visibility

    @staticmethod
    def get_clarification_recipients(communication_id):
        """Get all bidders who have access to a clarification.
        
        Args:
            communication_id: Communication ID
            
        Returns:
            List of active ClarificationVisibility objects
        """
        comm = Communication.query.get(communication_id)
        if not comm:
            return []
        
        if comm.visibility_type == 'public':
            # For public, return all active bidders
            from app.models.bidder import Bidder
            return Bidder.query.filter_by(active=True).all()
        else:
            # For targeted, return bidders with active access
            return ClarificationVisibility.query.filter_by(
                communication_id=communication_id
            ).filter(ClarificationVisibility.revoked_at == None).all()

    @staticmethod
    def log_access(communication_id, bidder_id, accessed_by_user_id, access_type='view'):
        """Log clarification access attempt.
        
        Args:
            communication_id: Communication ID
            bidder_id: Bidder ID
            accessed_by_user_id: User ID who accessed it
            access_type: 'view' or 'download'
        """
        access_log = ClarificationAccess(
            communication_id=communication_id,
            bidder_id=bidder_id,
            accessed_by_user_id=accessed_by_user_id,
            access_type=access_type,
            ip_address=None  # Could be set from request.remote_addr
        )
        db.session.add(access_log)
        db.session.commit()
        
        return access_log

    @staticmethod
    def get_access_log(communication_id, limit=50):
        """Get access log for a clarification.
        
        Args:
            communication_id: Communication ID
            limit: Maximum number of entries
            
        Returns:
            List of ClarificationAccess objects
        """
        return ClarificationAccess.query.filter_by(
            communication_id=communication_id
        ).order_by(ClarificationAccess.accessed_at.desc()).limit(limit).all()

    @staticmethod
    def convert_to_targeted(communication_id, reason=None):
        """Convert a public clarification to targeted.
        
        Existing access must be granted explicitly after the conversion.
        
        Args:
            communication_id: Communication ID
            reason: Reason for conversion
        """
        comm = Communication.query.get(communication_id)
        if not comm or comm.visibility_type != 'public':
            return False
        
        # Change visibility type
        comm.visibility_type = 'targeted'
        
        db.session.commit()
        return True

    @staticmethod
    def convert_to_public(communication_id, reason=None):
        """Convert a targeted clarification to public.
        
        Args:
            communication_id: Communication ID
            reason: Reason for conversion
        """
        comm = Communication.query.get(communication_id)
        if not comm or comm.visibility_type != 'targeted':
            return False
        
        # Change visibility type
        comm.visibility_type = 'public'
        
        # Clear all targeted access entries (they're no longer needed)
        visibilities = ClarificationVisibility.query.filter_by(
            communication_id=communication_id
        ).all()
        
        for vis in visibilities:
            db.session.delete(vis)
        
        db.session.commit()
        return True
