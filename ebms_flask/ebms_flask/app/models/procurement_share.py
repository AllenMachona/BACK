from datetime import datetime
from app.extensions import db


class ProcurementShare(db.Model):
    __tablename__ = 'procurement_shares'
    __table_args__ = (
        db.UniqueConstraint('procurement_id', 'recipient_id', name='uq_procurement_share_recipient'),
    )

    id = db.Column(db.Integer, primary_key=True)
    procurement_id = db.Column(db.Integer, db.ForeignKey('procurements.id'), nullable=False, index=True)
    recipient_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    shared_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    folder_name = db.Column(db.String(120), nullable=False, default='Shared procurements')
    status = db.Column(db.String(20), nullable=False, default='active', index=True)
    shared_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    revoked_at = db.Column(db.DateTime)
    revoked_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))

    procurement = db.relationship('Procurement', backref=db.backref('smartshare_grants', lazy='dynamic'))
    recipient = db.relationship('User', foreign_keys=[recipient_id], backref=db.backref('smartshare_received', lazy='dynamic'))
    shared_by = db.relationship('User', foreign_keys=[shared_by_id], backref=db.backref('smartshare_sent', lazy='dynamic'))
    revoked_by = db.relationship('User', foreign_keys=[revoked_by_id])

    @classmethod
    def active_for(cls, procurement_id, recipient_id):
        return cls.query.filter_by(
            procurement_id=procurement_id,
            recipient_id=recipient_id,
            status='active',
        ).first()

    @classmethod
    def has_access(cls, procurement_id, recipient_id):
        return cls.active_for(procurement_id, recipient_id) is not None

    def revoke(self, revoked_by):
        self.status = 'revoked'
        self.revoked_at = datetime.utcnow()
        self.revoked_by_id = revoked_by.id
