from datetime import datetime
from app.extensions import db


class Bidder(db.Model):
    """A registered bidder company (SOAR 7.5). Portal users linking to this
    company are User rows with role_code == 'bidder' and bidder_id set."""
    __tablename__ = 'bidders'

    id = db.Column(db.Integer, primary_key=True)
    company_name = db.Column(db.String(200), nullable=False)
    ppra_registration_number = db.Column(db.String(50), unique=True)
    ppra_grade = db.Column(db.String(10))
    category = db.Column(db.String(50))  # matches PPRA registration category, e.g. WRK-EDU
    contact_email = db.Column(db.String(120), nullable=False)
    contact_phone = db.Column(db.String(20))

    registered_at = db.Column(db.DateTime, default=datetime.utcnow)
    registration_expiry = db.Column(db.Date)
    active = db.Column(db.Boolean, default=True)
    suspended = db.Column(db.Boolean, default=False)
    verified = db.Column(db.Boolean, default=False)

    # Relationships
    portal_users = db.relationship('User', backref='bidder', lazy='dynamic', foreign_keys='User.bidder_id')
    submissions = db.relationship('Submission', backref='bidder', lazy='dynamic')
    evaluations = db.relationship('Evaluation', backref='bidder', lazy='dynamic')
    complaints = db.relationship('Complaint', backref='bidder', lazy='dynamic')

    def registration_status(self):
        if self.suspended:
            return 'suspended'
        if self.registration_expiry and self.registration_expiry < datetime.utcnow().date():
            return 'expired'
        return 'active' if self.active else 'inactive'

    def get_payment_for_procurement(self, procurement_id):
        from app.models.payment import BidderPayment
        return BidderPayment.query.filter_by(bidder_id=self.id, procurement_id=procurement_id).order_by(BidderPayment.submitted_at.desc()).first()

    def has_document_access(self, procurement_id, doc_type=None):
        from app.models.payment import BidderDocumentAccess
        return BidderDocumentAccess.can_bidder_access(procurement_id, self.id, doc_type)

    def has_approved_payment_for_procurement(self, procurement_id):
        payment = self.get_payment_for_procurement(procurement_id)
        return bool(payment and payment.status == 'approved')

    def __repr__(self):
        return f'<Bidder {self.company_name}>'
