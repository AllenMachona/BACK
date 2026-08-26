"""Enhanced audit system for comprehensive WHO+WHAT+WHEN+WHY tracking.

Extends the basic audit logging with structured helpers for tracking:
- Document operations (upload, replace, restore, download, view)
- Procurement state changes (open, close, cancel, restore)
- Message delivery and read status
- Permission/access changes
- Clarification visibility changes
- Version control operations
"""
import json
from datetime import datetime
from flask import request
from flask_login import current_user
from app.extensions import db
from app.models.audit import AuditLog
from app.models.history import ProcurementHistory, SubmissionHistory


def log_action(action, entity_type=None, entity_id=None, previous_value=None, new_value=None, reason=None):
    """Basic audit logging (append-only, never updated or deleted).
    
    Args:
        action: Action code (e.g., 'LOGIN_SUCCESS', 'DOCUMENT_UPLOAD', 'PROCUREMENT_PUBLISHED')
        entity_type: Type of entity affected (e.g., 'User', 'Procurement', 'Communication')
        entity_id: ID of entity affected
        previous_value: Previous state (JSON-serializable)
        new_value: New state (JSON-serializable)
        reason: Why this action was performed (required for sensitive actions)
    """
    try:
        entry = AuditLog(
            user_id=current_user.id if current_user.is_authenticated else None,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            previous_value=json.dumps(previous_value, default=str) if previous_value is not None else None,
            new_value=json.dumps(new_value, default=str) if new_value is not None else None,
            ip_address=request.remote_addr if request else None,
            reason=reason,
        )
        db.session.add(entry)
        db.session.commit()
    except Exception as exc:  # audit failures must never crash the calling request
        db.session.rollback()
        print(f"AUDIT LOG FAILURE: {exc}")


def log_document_operation(doc_type, entity_type, entity_id, operation, file_name=None, reason=None):
    """Log document-related operations with full context.
    
    Args:
        doc_type: Document type (e.g., 'itt', 'clarification', 'form_d')
        entity_type: Entity type (e.g., 'Procurement', 'Communication')
        entity_id: Entity ID
        operation: 'upload', 'replace', 'restore', 'download', 'view', 'delete'
        file_name: Name of the file
        reason: Why (especially important for restore/delete)
    """
    log_action(
        action=f'DOCUMENT_{operation.upper()}',
        entity_type=entity_type,
        entity_id=entity_id,
        new_value={'doc_type': doc_type, 'file_name': file_name},
        reason=reason
    )


def log_procurement_state_change(procurement_id, action, previous_status, new_status, reason=None):
    """Log procurement state transitions.
    
    Creates both an AuditLog entry and a ProcurementHistory entry for restore tracking.
    
    Args:
        procurement_id: Procurement ID
        action: Action (e.g., 'published', 'submission_closed', 'opening', 'cancelled', 'restored')
        previous_status: Previous status
        new_status: New status
        reason: Why the action was taken
    """
    # Create audit log
    log_action(
        action=f'PROCUREMENT_{action.upper()}',
        entity_type='Procurement',
        entity_id=procurement_id,
        previous_value={'status': previous_status},
        new_value={'status': new_status},
        reason=reason
    )
    
    # Create history entry for restore tracking
    try:
        history = ProcurementHistory.log_action(
            procurement_id=procurement_id,
            action=action,
            performed_by_id=current_user.id if current_user.is_authenticated else None,
            reason=reason,
            previous_status=previous_status,
            new_status=new_status
        )
        db.session.add(history)
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        print(f"PROCUREMENT HISTORY FAILURE: {exc}")


def log_message_delivery(message_id, recipient_count, message_type, reason=None):
    """Log message sent event."""
    log_action(
        action=f'MESSAGE_{message_type.upper()}_SENT',
        entity_type='Message',
        entity_id=message_id,
        new_value={'recipient_count': recipient_count},
        reason=reason
    )


def log_message_read(message_id, reader_id):
    """Log when a message is read."""
    log_action(
        action='MESSAGE_READ',
        entity_type='Message',
        entity_id=message_id,
        new_value={'reader_id': reader_id}
    )


def log_clarification_visibility_change(communication_id, bidder_id, action, reason=None):
    """Log clarification visibility changes (grant/revoke access).
    
    Args:
        communication_id: Communication/clarification ID
        bidder_id: Bidder ID (None if action affects all bidders)
        action: 'grant' or 'revoke'
        reason: Why the change was made
    """
    log_action(
        action=f'CLARIFICATION_{action.upper()}',
        entity_type='Communication',
        entity_id=communication_id,
        new_value={'bidder_id': bidder_id},
        reason=reason
    )


def log_document_access(doc_type, entity_id, access_type, reason=None):
    """Log document access (download, view).
    
    Args:
        doc_type: Document type
        entity_id: Entity ID
        access_type: 'download' or 'view'
        reason: Why accessed
    """
    log_action(
        action=f'DOCUMENT_{access_type.upper()}',
        entity_type='Document',
        entity_id=entity_id,
        new_value={'doc_type': doc_type},
        reason=reason
    )


def log_version_restore(document_type, entity_type, entity_id, version_number, reason=None):
    """Log document version restoration.
    
    Args:
        document_type: Type of document (e.g., 'itt')
        entity_type: Entity type (e.g., 'Procurement')
        entity_id: Entity ID
        version_number: Version being restored to
        reason: Why the version was restored
    """
    log_action(
        action='DOCUMENT_RESTORE',
        entity_type=entity_type,
        entity_id=entity_id,
        new_value={'document_type': document_type, 'version': version_number},
        reason=reason
    )


def log_permission_change(affected_user_id, permission_type, granted, reason=None):
    """Log permission/access changes.
    
    Args:
        affected_user_id: User whose permissions changed
        permission_type: Type of permission (e.g., 'document_access', 'committee_member')
        granted: True if granted, False if revoked
        reason: Why changed
    """
    log_action(
        action=f'PERMISSION_{"GRANTED" if granted else "REVOKED"}',
        entity_type='User',
        entity_id=affected_user_id,
        new_value={'permission_type': permission_type},
        reason=reason
    )


def log_report_export(report_type, filters=None, format_type='excel'):
    """Log report exports for audit trail.
    
    Args:
        report_type: Type of report (e.g., 'bidder_participation')
        filters: Applied filters
        format_type: Export format (e.g., 'excel', 'pdf')
    """
    log_action(
        action=f'REPORT_EXPORT_{format_type.upper()}',
        entity_type='Report',
        new_value={'report_type': report_type, 'filters': filters}
    )


def log_submission_change(submission_id, action, previous_status, new_status, reason=None):
    """Log submission state changes (replace, withdraw, restore).
    
    Args:
        submission_id: Submission ID
        action: 'submitted', 'replaced', 'withdrawn', 'restored'
        previous_status: Previous status
        new_status: New status
        reason: Why the change was made
    """
    # Create audit log
    log_action(
        action=f'SUBMISSION_{action.upper()}',
        entity_type='Submission',
        entity_id=submission_id,
        previous_value={'status': previous_status},
        new_value={'status': new_status},
        reason=reason
    )
    
    # Create history entry for tracking
    try:
        history = SubmissionHistory(
            submission_id=submission_id,
            action=action,
            previous_status=previous_status,
            new_status=new_status,
            reason=reason,
            performed_by_id=current_user.id if current_user.is_authenticated else None
        )
        db.session.add(history)
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        print(f"SUBMISSION HISTORY FAILURE: {exc}")


def get_entity_audit_trail(entity_type, entity_id, limit=100):
    """Retrieve the full audit trail for an entity.
    
    Args:
        entity_type: Type of entity
        entity_id: Entity ID
        limit: Maximum number of entries to return
        
    Returns:
        List of AuditLog entries in reverse chronological order
    """
    return AuditLog.query.filter_by(
        entity_type=entity_type,
        entity_id=entity_id
    ).order_by(AuditLog.created_at.desc()).limit(limit).all()


def get_user_actions(user_id, limit=100):
    """Retrieve all actions performed by a user.
    
    Args:
        user_id: User ID
        limit: Maximum number of entries
        
    Returns:
        List of AuditLog entries
    """
    return AuditLog.query.filter_by(
        user_id=user_id
    ).order_by(AuditLog.created_at.desc()).limit(limit).all()
