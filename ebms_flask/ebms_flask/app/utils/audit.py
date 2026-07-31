"""Append-only audit logging (SOAR 8.3). Every write goes through log_action
so that "which routes write audit entries" is answered by grepping one
function name, not by trusting every route author to remember."""
import json
from flask import request
from flask_login import current_user
from app.extensions import db
from app.models.audit import AuditLog


def log_action(action, entity_type=None, entity_id=None, previous_value=None, new_value=None, reason=None):
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
