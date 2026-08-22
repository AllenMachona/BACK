from datetime import datetime

from app.extensions import db


class BudgetEntry(db.Model):
    """A posted budget commitment, invoice, payment, or adjustment."""
    __tablename__ = 'budget_entries'

    id = db.Column(db.Integer, primary_key=True)
    procurement_id = db.Column(db.Integer, db.ForeignKey('procurements.id'), nullable=False, index=True)
    entry_type = db.Column(db.String(30), nullable=False, default='commitment')
    description = db.Column(db.String(300), nullable=False)
    amount = db.Column(db.Numeric(15, 2), nullable=False)
    reference = db.Column(db.String(100))
    entry_date = db.Column(db.Date, nullable=False, default=lambda: datetime.utcnow().date())
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    procurement = db.relationship('Procurement', backref=db.backref('budget_entries', lazy='dynamic', cascade='all, delete-orphan'))
    created_by = db.relationship('User', foreign_keys=[created_by_id])

    ENTRY_TYPES = ('commitment', 'invoice', 'payment', 'adjustment')

    @property
    def signed_amount(self):
        return -self.amount if self.entry_type == 'adjustment' else self.amount