"""Role-based access control decorators (SOAR Section 5, Appendix A)."""
from functools import wraps
from flask import abort
from flask_login import current_user


def role_required(*role_codes):
    """Restrict a view to users whose role.code is in role_codes."""
    def decorator(view_func):
        @wraps(view_func)
        def wrapped(*args, **kwargs):
            if not current_user.is_authenticated:
                abort(401)
            if not current_user.role or current_user.role.code not in role_codes:
                abort(403)
            return view_func(*args, **kwargs)
        return wrapped
    return decorator


def permission_required(flag_name):
    """Restrict a view based on a Role permission flag, e.g. 'can_evaluate'."""
    def decorator(view_func):
        @wraps(view_func)
        def wrapped(*args, **kwargs):
            if not current_user.is_authenticated:
                abort(401)
            if not current_user.role or not getattr(current_user.role, flag_name, False):
                abort(403)
            return view_func(*args, **kwargs)
        return wrapped
    return decorator
