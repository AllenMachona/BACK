"""Notification dispatch: in-app Notification row + best-effort email.
If MAIL_SERVER isn't configured, emails are printed to the console instead
of failing outright — the app runs and demonstrates the workflow without
real SMTP credentials."""
from flask import current_app
from app.extensions import db
from app.models.notification import Notification


def send_email(to_address, subject, body):
    if not current_app.config.get('MAIL_CONFIGURED'):
        print(f"[MAILER — console fallback, MAIL_SERVER not configured]\nTo: {to_address}\nSubject: {subject}\n{body}\n")
        return False
    server = current_app.config['MAIL_SERVER']
    try:
        import smtplib
        from email.mime.text import MIMEText

        msg = MIMEText(body)
        msg['Subject'] = subject
        msg['From'] = current_app.config['MAIL_DEFAULT_SENDER']
        msg['To'] = to_address

        with smtplib.SMTP(server, current_app.config['MAIL_PORT']) as smtp:
            if current_app.config.get('MAIL_USE_TLS'):
                smtp.starttls()
            if current_app.config.get('MAIL_USERNAME'):
                smtp.login(current_app.config['MAIL_USERNAME'], current_app.config['MAIL_PASSWORD'])
            smtp.send_message(msg)
        return True
    except Exception as exc:
        print(f"Email send failed (non-fatal): {exc}")
        return False


def notify_user(user, notif_type, title, body, procurement_id=None, email=True):
    notification = Notification(
        user_id=user.id, type=notif_type, title=title, body=body, procurement_id=procurement_id,
    )
    db.session.add(notification)
    db.session.commit()

    if email and user.email:
        if send_email(user.email, title, body):
            notification.emailed_at = db.func.now()
            db.session.commit()
    return notification


def notify_bidders_on_procurement(procurement, notif_type, title, body):
    """Notify every portal user linked to a bidder who has submitted on this
    procurement (for post-submission events), or fall back to notifying
    every verified bidder for pre-submission events like deadline reminders."""
    from app.models.submission import Submission
    from app.models.bidder import Bidder
    from app.models.user import User

    bidder_ids = {s.bidder_id for s in procurement.submissions}
    if bidder_ids:
        users = User.query.filter(User.bidder_id.in_(bidder_ids)).all()
    else:
        users = User.query.join(Bidder, User.bidder_id == Bidder.id).filter(Bidder.verified.is_(True)).all()

    for u in users:
        notify_user(u, notif_type, title, body, procurement_id=procurement.id)
