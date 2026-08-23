"""Notification dispatch: in-app Notification row + best-effort email.
If MAIL_SERVER isn't configured, emails are printed to the console instead
of failing outright — the app runs and demonstrates the workflow without
real SMTP credentials."""
from flask import current_app
from app.extensions import db
from app.models.notification import Notification


def send_email(to_address, subject, body):
    from app.models.site_setting import SiteSetting
    if SiteSetting.get('enable_email', 'true').lower() != 'true':
        current_app.logger.info('Email disabled by administrator: %s', subject)
        return False
    if not current_app.config.get('MAIL_CONFIGURED'):
        current_app.logger.warning(
            'Email skipped: configure MAIL_SERVER and MAIL_DEFAULT_SENDER to send %s to %s',
            subject, to_address,
        )
        return False
    server = current_app.config['MAIL_SERVER']
    try:
        import smtplib
        from email.mime.text import MIMEText
        from email.header import Header

        msg = MIMEText(body)
        msg['Subject'] = subject
        sender_name = SiteSetting.get('email_sender_name', '').strip()
        sender = current_app.config['MAIL_DEFAULT_SENDER']
        msg['From'] = f'{Header(sender_name, "utf-8")} <{sender}>' if sender_name else sender
        msg['To'] = to_address

        smtp_class = smtplib.SMTP_SSL if current_app.config.get('MAIL_USE_SSL') else smtplib.SMTP
        with smtp_class(
            server,
            current_app.config['MAIL_PORT'],
            timeout=current_app.config.get('MAIL_TIMEOUT', 20),
        ) as smtp:
            if current_app.config.get('MAIL_USE_TLS') and not current_app.config.get('MAIL_USE_SSL'):
                smtp.starttls()
            if current_app.config.get('MAIL_USERNAME'):
                smtp.login(
                    current_app.config['MAIL_USERNAME'],
                    current_app.config['MAIL_PASSWORD'].replace(' ', ''),
                )
            smtp.send_message(msg)
        return True
    except Exception:
        current_app.config['MAIL_LAST_ERROR'] = 'SMTP delivery failed. Check the SMTP username and App Password.'
        current_app.logger.exception('Email delivery failed for %s', to_address)
        return False


def notify_user(user, notif_type, title, body, procurement_id=None, email=True):
    from app.models.site_setting import SiteSetting
    if SiteSetting.get('enable_notifications', 'true').lower() != 'true':
        return None
    notification = Notification(
        user_id=user.id, type=notif_type, title=title, body=body, procurement_id=procurement_id,
    )
    db.session.add(notification)
    db.session.commit()

    if email and user.email and SiteSetting.get('enable_email', 'true').lower() == 'true':
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
        users = User.query.join(Bidder, User.bidder_id == Bidder.id).filter(Bidder.verified == True).all()

    for u in users:
        notify_user(u, notif_type, title, body, procurement_id=procurement.id)
