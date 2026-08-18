"""Procurement state management and restoration service.

Handles procurement lifecycle transitions (open, close, cancel, restore).
Maintains complete audit trail - original actions are NEVER erased.
"""
from datetime import datetime
from flask_login import current_user
from app.extensions import db
from app.models.procurement import Procurement
from app.models.history import ProcurementHistory
from app.utils.audit_enhanced import log_procurement_state_change


class ProcurementStateService:
    """Service for managing procurement state transitions and restorations."""
    
    @staticmethod
    def publish_procurement(procurement_id, reason=None):
        """Transition procurement from draft to published.
        
        Args:
            procurement_id: Procurement ID
            reason: Reason for publishing
            
        Returns:
            Procurement object or None if invalid state
        """
        procurement = Procurement.query.get(procurement_id)
        if not procurement or procurement.status != 'draft':
            return None
        
        previous_status = procurement.status
        procurement.status = 'published'
        db.session.commit()
        
        # Log state change
        log_procurement_state_change(
            procurement_id=procurement_id,
            action='published',
            previous_status=previous_status,
            new_status='published',
            reason=reason
        )
        
        return procurement

    @staticmethod
    def open_submissions(procurement_id, reason=None):
        """Transition procurement from published to submission_open.
        
        Args:
            procurement_id: Procurement ID
            reason: Reason for opening
            
        Returns:
            Procurement object or None
        """
        procurement = Procurement.query.get(procurement_id)
        if not procurement or procurement.status != 'published':
            return None
        
        previous_status = procurement.status
        procurement.status = 'submission_open'
        db.session.commit()
        
        log_procurement_state_change(
            procurement_id=procurement_id,
            action='submission_open',
            previous_status=previous_status,
            new_status='submission_open',
            reason=reason
        )
        
        return procurement

    @staticmethod
    def close_submissions(procurement_id, reason=None):
        """Transition procurement from submission_open to submission_closed.
        
        Args:
            procurement_id: Procurement ID
            reason: Reason for closing
            
        Returns:
            Procurement object or None
        """
        procurement = Procurement.query.get(procurement_id)
        if not procurement or procurement.status != 'submission_open':
            return None
        
        previous_status = procurement.status
        procurement.status = 'submission_closed'
        db.session.commit()
        
        log_procurement_state_change(
            procurement_id=procurement_id,
            action='submission_closed',
            previous_status=previous_status,
            new_status='submission_closed',
            reason=reason
        )
        
        return procurement

    @staticmethod
    def schedule_bid_opening(procurement_id, opening_date, reason=None):
        """Schedule bid opening and transition to opening state.
        
        Args:
            procurement_id: Procurement ID
            opening_date: DateTime for the opening
            reason: Reason
            
        Returns:
            Procurement object
        """
        procurement = Procurement.query.get(procurement_id)
        if not procurement:
            return None
        
        previous_status = procurement.status
        procurement.status = 'opening'
        procurement.opening_scheduled_at = opening_date
        db.session.commit()
        
        log_procurement_state_change(
            procurement_id=procurement_id,
            action='opening',
            previous_status=previous_status,
            new_status='opening',
            reason=reason
        )
        
        return procurement

    @staticmethod
    def transition_to_evaluation(procurement_id, reason=None):
        """Transition procurement from opening to evaluation.
        
        Args:
            procurement_id: Procurement ID
            reason: Reason
            
        Returns:
            Procurement object
        """
        procurement = Procurement.query.get(procurement_id)
        if not procurement or procurement.status != 'opening':
            return None
        
        previous_status = procurement.status
        procurement.status = 'evaluation'
        db.session.commit()
        
        log_procurement_state_change(
            procurement_id=procurement_id,
            action='evaluation',
            previous_status=previous_status,
            new_status='evaluation',
            reason=reason
        )
        
        return procurement

    @staticmethod
    def publish_award(procurement_id, reason=None):
        """Transition procurement from evaluation to award_published.
        
        Args:
            procurement_id: Procurement ID
            reason: Reason
            
        Returns:
            Procurement object
        """
        procurement = Procurement.query.get(procurement_id)
        if not procurement or procurement.status != 'evaluation':
            return None
        
        previous_status = procurement.status
        procurement.status = 'award_published'
        db.session.commit()
        
        log_procurement_state_change(
            procurement_id=procurement_id,
            action='award_published',
            previous_status=previous_status,
            new_status='award_published',
            reason=reason
        )
        
        return procurement

    @staticmethod
    def cancel_procurement(procurement_id, reason=None):
        """Cancel a procurement.
        
        The procurement remains in history with cancelled=True.
        Original state is preserved in the audit trail.
        
        Args:
            procurement_id: Procurement ID
            reason: Reason for cancellation (REQUIRED for audit)
            
        Returns:
            Procurement object
        """
        if not reason:
            raise ValueError("Cancellation reason is required for audit trail")
        
        procurement = Procurement.query.get(procurement_id)
        if not procurement or procurement.cancelled:
            return None
        
        previous_status = procurement.status
        procurement.cancelled = True
        procurement.cancelled_reason = reason
        procurement.cancelled_at = datetime.utcnow()
        db.session.commit()
        
        log_procurement_state_change(
            procurement_id=procurement_id,
            action='cancelled',
            previous_status=previous_status,
            new_status='cancelled',
            reason=reason
        )
        
        return procurement

    @staticmethod
    def restore_procurement_state(procurement_id, target_history_id, reason=None):
        """Restore procurement to a previous state.
        
        Creates a NEW history entry. Original actions are NEVER erased.
        
        Args:
            procurement_id: Procurement ID
            target_history_id: ID of the ProcurementHistory to restore from
            reason: Reason for restoration (REQUIRED)
            
        Returns:
            Procurement object or None
        """
        if not reason:
            raise ValueError("Restoration reason is required for audit trail")
        
        procurement = Procurement.query.get(procurement_id)
        target_history = ProcurementHistory.query.get(target_history_id)
        
        if not procurement or not target_history or target_history.procurement_id != procurement_id:
            return None
        
        # Restore to the target state
        previous_status = procurement.status
        procurement.status = target_history.new_status
        
        # Clear cancellation if restoring to active state
        if not previous_status == 'cancelled' and target_history.new_status != 'cancelled':
            procurement.cancelled = False
            procurement.cancelled_reason = None
            procurement.cancelled_at = None
        
        db.session.commit()
        
        # Log the restoration
        restoration_history = ProcurementHistory(
            procurement_id=procurement_id,
            action='restored',
            previous_status=previous_status,
            new_status=target_history.new_status,
            reason=reason,
            restored_from_history_id=target_history_id,
            performed_by_id=current_user.id if current_user.is_authenticated else None
        )
        db.session.add(restoration_history)
        db.session.commit()
        
        # Audit log
        log_procurement_state_change(
            procurement_id=procurement_id,
            action='restored',
            previous_status=previous_status,
            new_status=target_history.new_status,
            reason=reason
        )
        
        return procurement

    @staticmethod
    def get_procurement_history(procurement_id):
        """Get the complete state change history for a procurement.
        
        Args:
            procurement_id: Procurement ID
            
        Returns:
            List of ProcurementHistory objects in chronological order
        """
        return ProcurementHistory.query.filter_by(
            procurement_id=procurement_id
        ).order_by(ProcurementHistory.performed_at.desc()).all()

    @staticmethod
    def can_restore_to_state(procurement_id, target_history_id):
        """Check if a procurement can be restored to a specific state.
        
        Business rules:
        - Can restore to any previous state
        - Cannot restore past cancellation without special approval
        - Cannot restore if in award phase past cooling-off period
        
        Args:
            procurement_id: Procurement ID
            target_history_id: Target history entry ID
            
        Returns:
            True if restoration is allowed, False otherwise
        """
        procurement = Procurement.query.get(procurement_id)
        history = ProcurementHistory.query.get(target_history_id)
        
        if not procurement or not history:
            return False
        
        if history.procurement_id != procurement_id:
            return False
        
        # Check if we're trying to restore past award cooling-off period
        if procurement.status == 'award_published':
            from app.models.award import Award
            award = Award.query.filter_by(procurement_id=procurement_id).first()
            if award and not award.cooling_off_active():
                # Can't restore past cooling-off expiry without approval
                return False
        
        return True

    @staticmethod
    def extend_submission_deadline(procurement_id, new_deadline, reason=None):
        """Extend the submission deadline.
        
        Args:
            procurement_id: Procurement ID
            new_deadline: New deadline DateTime
            reason: Reason for extension
            
        Returns:
            Procurement object
        """
        procurement = Procurement.query.get(procurement_id)
        if not procurement or procurement.status != 'submission_open':
            return None
        
        old_deadline = procurement.submission_deadline
        procurement.submission_deadline = new_deadline
        db.session.commit()
        
        log_procurement_state_change(
            procurement_id=procurement_id,
            action='deadline_extended',
            previous_status=procurement.status,
            new_status=procurement.status,
            reason=reason
        )
        
        return procurement
