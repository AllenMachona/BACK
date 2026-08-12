# EBMS Botswana - Security Best Practices & Implementation

## Overview
This document outlines the security measures implemented in the EBMS Botswana e-procurement system.

## 1. Authentication & Authorization

### Login Security
- ✅ **Account Lockout**: After 5 failed login attempts, account is locked for 15 minutes
- ✅ **Session Management**: Secure session cookies with HttpOnly and Secure flags
- ✅ **Login Audit Logging**: All login attempts (success/failure) are logged with IP address
- ✅ **Last Login Tracking**: System tracks last login time and IP for security monitoring

### Password Security
- ✅ **Strong Password Policy**: 
  - Minimum 10 characters
  - At least one uppercase letter
  - At least one lowercase letter
  - At least one number
  - At least one special character (!@#$%^&*...)
  - Rejects common patterns (password, 123456, qwerty, admin, letmein)
- ✅ **Password Hashing**: Uses werkzeug.security with SHA256 + salt
- ✅ **Password Expiry**: Enforced password changes every 90 days
- ✅ **Password Reset**: Secure token-based password reset with expiry

### Registration Security
- ✅ **Role Restriction**: Public registration only allows "Bidder" role
- ✅ **Server-Side Validation**: Role selection is forced to bidder on server-side
- ✅ **Input Validation**: All fields are sanitized and validated
- ✅ **Duplicate Detection**: Prevents duplicate username/email registrations
- ✅ **Audit Logging**: All registration attempts (success/failure) are logged

## 2. Input & Output Security

### Input Sanitization
- ✅ **HTML Sanitization**: User input is sanitized to prevent XSS attacks
- ✅ **String Normalization**: Whitespace is normalized and control characters removed
- ✅ **Email Validation**: Email format validated against RFC 5322 pattern
- ✅ **Filename Validation**: File uploads validated to prevent directory traversal
- ✅ **SQL Injection Prevention**: Using SQLAlchemy ORM (parameterized queries)

### Output Encoding
- ✅ **XSS Protection**: Template auto-escaping enabled in Jinja2
- ✅ **HTML Escaping**: All user data escaped in templates

## 3. HTTP Security Headers

### Headers Implemented
```
X-Frame-Options: SAMEORIGIN          # Prevent clickjacking
X-Content-Type-Options: nosniff       # Prevent MIME sniffing
X-XSS-Protection: 1; mode=block       # Enable XSS protection
Referrer-Policy: strict-origin-when-cross-origin
Permissions-Policy: geolocation=(), microphone=(), camera=()
Strict-Transport-Security: max-age=31536000; includeSubDomains  # HSTS
Content-Security-Policy: [configured to prevent inline script/style]
```

## 4. Authorization & Access Control

### Role-Based Access Control (RBAC)
- ✅ **Role Definitions**: 10 predefined roles with specific permissions
- ✅ **Permission Checks**: All protected routes check user permissions
- ✅ **Decorators**: `@require_role()`, `@require_permission()`, `@require_bidder()`
- ✅ **Resource-Level Access**: Ensure users only access their own data

### Session Security
- ✅ **Session Timeout**: Sessions expire after inactivity
- ✅ **Secure Cookies**: HttpOnly and Secure flags enabled
- ✅ **CSRF Protection**: Forms use CSRF tokens
- ✅ **Session Regeneration**: Session ID regenerated after login

## 5. Data Security

### Audit Logging
- ✅ **Comprehensive Logging**: All sensitive actions logged with:
  - User ID
  - Action type
  - Entity type and ID
  - Timestamp
  - IP address (for login events)
  - Changes made (for updates)
- ✅ **Immutable Audit Log**: Audit records cannot be modified
- ✅ **Retention**: Audit logs retained for compliance

### Data Encryption
- ✅ **Password Hashing**: All passwords hashed with salt
- ✅ **Sensitive Fields**: Finance amounts and personal data encrypted at rest
- ✅ **Transit Encryption**: HTTPS enforced in production
- ✅ **Database Connection**: Connection string configured for SSL

## 6. Message/Communication Security

### Direct Messaging Security
- ✅ **Message Encryption**: Messages stored in database
- ✅ **Access Control**: Only recipient can view messages
- ✅ **Reply Verification**: Sender verification to prevent unauthorized replies
- ✅ **Audit Trail**: All messages logged with sender/recipient
- ✅ **XSS Prevention**: Message bodies sanitized to prevent script injection

## 7. File Upload Security

### Upload Validation
- ✅ **Whitelist Extensions**: Only approved file types allowed
- ✅ **File Size Limits**: Enforced maximum file sizes
- ✅ **Filename Sanitization**: Filenames validated to prevent traversal attacks
- ✅ **Content Type Verification**: Verify actual file type matches extension
- ✅ **Separate Storage**: Uploads stored outside web root
- ✅ **Access Control**: Downloads require authentication and authorization

## 8. User Profile Security

### Designation/Job Title Management
- ✅ **Unique Job Titles**: Each user assigned unique designation
- ✅ **Validation**: Job titles sanitized and normalized
- ✅ **Audit Trail**: Changes to job titles logged
- ✅ **Migration Script**: `scripts/ensure_unique_jobs.py` populates missing designations

## 9. Database Security

### Connection Security
- ✅ **Parameterized Queries**: All database queries use ORM
- ✅ **Connection Encryption**: SSL/TLS for database connections
- ✅ **Credentials Management**: Database credentials in environment variables

### Data Integrity
- ✅ **Foreign Keys**: Enforced referential integrity
- ✅ **Transactions**: Critical operations wrapped in transactions
- ✅ **Backups**: Regular backups with encryption

## 10. Infrastructure Security

### Application Hardening
- ✅ **HTTPS Only**: Production enforces HTTPS
- ✅ **Security Headers**: Comprehensive HTTP security headers
- ✅ **Error Handling**: Generic error messages (no stack traces to users)
- ✅ **Logging**: Detailed internal logging for debugging

### Deployment Security
- ✅ **Environment Variables**: Sensitive config in environment
- ✅ **Debug Mode**: Disabled in production
- ✅ **Secret Key**: Strong random secret key for session signing
- ✅ **CORS Configuration**: Restricted to trusted origins

## Security Scripts & Utilities

### Available Scripts

#### 1. Ensure Unique Jobs
```bash
python scripts/ensure_unique_jobs.py
```
Populates all users with unique job titles if missing.

#### 2. Database Migrations
```bash
python scripts/migrate_security_enhancements.py
```
Applies security-related database schema changes (sender_id, reply_to fields).

### Security Utilities

#### Input Sanitization
```python
from app.utils.security import sanitize_html, sanitize_string, validate_email

# HTML sanitization (for rich text)
clean_html = sanitize_html(user_input)

# String sanitization
clean_string = sanitize_string(user_input, max_length=100)

# Email validation
if not validate_email(email):
    flash('Invalid email address', 'danger')
```

#### Authorization Decorators
```python
from app.utils.security import require_role, require_permission, require_bidder

# Require specific roles
@app.route('/admin')
@require_role('system_administrator', 'procurement_unit')
def admin_panel():
    pass

# Require specific permission
@app.route('/approve')
@require_permission('can_approve_procurement')
def approve_procurement():
    pass

# Require bidder role only
@app.route('/bidder-portal')
@require_bidder()
def bidder_portal():
    pass
```

#### Password Strength Validation
```python
from app.utils.security import validate_password_strength

is_valid, error_msg = validate_password_strength(password)
if not is_valid:
    flash(error_msg, 'danger')
```

## Security Checklist for Deployment

- [ ] **Environment Variables Set**
  - `SECRET_KEY`: Strong random key
  - `DATABASE_URL`: Database connection string
  - `FLASK_ENV`: Set to 'production'
  - `REQUIRE_HTTPS`: Set to 'True'

- [ ] **Database Migrations Applied**
  - Run `python scripts/migrate_security_enhancements.py`
  - Run `python scripts/ensure_unique_jobs.py`

- [ ] **SSL/TLS Certificate**
  - Valid HTTPS certificate installed
  - Certificate renewed before expiry

- [ ] **Backup & Recovery**
  - Backups automated and encrypted
  - Recovery procedures tested

- [ ] **Monitoring & Alerting**
  - Error/security events logged
  - Log aggregation configured
  - Alerts for suspicious activities

- [ ] **User Access Verification**
  - All users have unique designations
  - Bidders correctly assigned bidder role
  - Admin users have appropriate permissions

## Security Testing Recommendations

1. **OWASP Top 10 Checks**
   - Injection (SQL, NoSQL, OS)
   - Broken Authentication
   - Sensitive Data Exposure
   - XML External Entities (XXE)
   - Broken Access Control
   - Security Misconfiguration
   - XSS
   - Insecure Deserialization
   - Using Components with Known Vulnerabilities
   - Insufficient Logging & Monitoring

2. **Penetration Testing**
   - Conduct annual security audit
   - Test all authentication mechanisms
   - Verify access control enforcement
   - Check for data exposure vulnerabilities

3. **Code Review**
   - Security-focused code reviews
   - Dependency vulnerability scanning
   - Static code analysis

## Incident Response

### Security Incident Reporting
Contact: security@ebms.bw

### Response Procedures
1. Identify and contain the incident
2. Log detailed incident information
3. Notify affected users if data exposed
4. Remediate and patch vulnerabilities
5. Post-incident review and improvements

## Compliance

This system complies with:
- OWASP Secure Coding Practices
- NIST Cybersecurity Framework
- ISO/IEC 27001 Information Security Standards
- Botswana Data Protection Laws

## Additional Resources

- [OWASP Top 10](https://owasp.org/www-project-top-ten/)
- [Flask Security Best Practices](https://flask.palletsprojects.com/en/2.0.x/security/)
- [SQLAlchemy Security](https://docs.sqlalchemy.org/en/14/core/sqlelements.html)

---

**Last Updated**: 2026-08-12
**Version**: 1.0
**Status**: Active Implementation
