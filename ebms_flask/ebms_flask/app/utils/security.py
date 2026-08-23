"""
Security utilities for input sanitization, CSRF protection, and authorization checks.
"""

import re
import bleach
from functools import wraps
from flask import request, flash, redirect, url_for
from flask_login import current_user


# Allowed HTML tags for rich text inputs
ALLOWED_TAGS = ['b', 'i', 'em', 'strong', 'a', 'p', 'br', 'ul', 'ol', 'li', 'blockquote', 'code', 'pre']
ALLOWED_ATTRIBUTES = {'a': ['href', 'title'], 'code': ['class']}


def sanitize_html(text):
    """Sanitize HTML input to prevent XSS attacks."""
    if not text:
        return text
    return bleach.clean(text, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRIBUTES, strip=True)


def sanitize_string(text, max_length=None):
    """Remove special characters and normalize whitespace."""
    if not text:
        return text
    
    # Remove null bytes and control characters
    text = ''.join(char for char in text if ord(char) >= 32 or char in '\n\r\t')
    
    # Normalize whitespace
    text = ' '.join(text.split())
    
    # Enforce max length
    if max_length and len(text) > max_length:
        text = text[:max_length]
    
    return text


def is_safe_filename(filename):
    """Validate filename to prevent directory traversal attacks."""
    if not filename:
        return False
    
    # Reject path traversal attempts
    if '..' in filename or filename.startswith('/'):
        return False
    
    # Only allow alphanumeric, dash, underscore, and common file extensions
    return bool(re.match(r'^[\w\-. ]+$', filename))


def validate_email(email):
    """Validate email format."""
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(pattern, email)) and len(email) <= 120


def validate_password_strength(password):
    """
    Validate password meets minimum security requirements.
    Returns: (is_valid: bool, error_message: str or None)
    """
    from app.models.site_setting import SiteSetting
    minimum_length = int(float(SiteSetting.get('minimum_password_length', '10')))
    if not password or len(password) < minimum_length:
        return False, f'Password must be at least {minimum_length} characters long.'
    
    if SiteSetting.get('require_password_uppercase', 'true').lower() == 'true' and not any(c.isupper() for c in password):
        return False, 'Password must contain at least one uppercase letter.'
    
    if not any(c.islower() for c in password):
        return False, 'Password must contain at least one lowercase letter.'
    
    if SiteSetting.get('require_password_number', 'true').lower() == 'true' and not any(c.isdigit() for c in password):
        return False, 'Password must contain at least one number.'
    
    if SiteSetting.get('require_password_special', 'true').lower() == 'true' and not any(c in '!@#$%^&*()_+-=[]{}|;:,.<>?' for c in password):
        return False, 'Password must contain at least one special character (!@#$%^&*...).'
    
    # Check for common patterns
    common_patterns = ['password', '123456', 'qwerty', 'admin', 'letmein']
    if any(pattern in password.lower() for pattern in common_patterns):
        return False, 'Password contains a common pattern. Please use a more unique password.'
    
    return True, None


def require_role(*allowed_roles):
    """
    Decorator to require specific roles for a route.
    Usage: @require_role('admin', 'procurement_unit')
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                flash('Please log in to access this page.', 'danger')
                return redirect(url_for('auth.login'))
            
            if current_user.role.code not in allowed_roles:
                flash('You do not have permission to access this page.', 'danger')
                return redirect(url_for('dashboard.index'))
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def require_permission(permission_name):
    """
    Decorator to require a specific permission.
    Usage: @require_permission('can_approve_procurement')
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                flash('Please log in to access this page.', 'danger')
                return redirect(url_for('auth.login'))
            
            if not getattr(current_user.role, permission_name, False):
                flash('You do not have permission to perform this action.', 'danger')
                return redirect(url_for('dashboard.index'))
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def require_bidder():
    """Decorator to restrict to bidder role only."""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                flash('Please log in to access this page.', 'danger')
                return redirect(url_for('auth.login'))
            
            if not current_user.has_role('bidder'):
                flash('This page is for bidders only.', 'danger')
                return redirect(url_for('dashboard.index'))
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator
