from datetime import datetime
from app.extensions import db


class Submission(db.Model):
    """A sealed bid submission (SOAR 7.7). File content is encrypted at rest
    via app.utils.crypto — this row only ever stores metadata and a path to
    the encrypted blob, never plaintext."""
    __tablename__ = 'submissions'

    id = db.Column(db.Integer, primary_key=True)
    procurement_id = db.Column(db.Integer, db.ForeignKey('procurements.id'), nullable=False)
    bidder_id = db.Column(db.Integer, db.ForeignKey('bidders.id'), nullable=False)
    envelope_type = db.Column(db.String(10), nullable=False)  # single, technical, financial

    file_path = db.Column(db.String(500))
    original_filename = db.Column(db.String(300))
    sha256_hash = db.Column(db.String(64))
    file_size_bytes = db.Column(db.Integer)

    compliance_document_path = db.Column(db.String(500))
    compliance_document_filename = db.Column(db.String(300))
    compliance_document_hash = db.Column(db.String(64))

    returnable_document_path = db.Column(db.String(500))
    returnable_document_filename = db.Column(db.String(300))
    returnable_document_hash = db.Column(db.String(64))

    version = db.Column(db.Integer, default=1)
    status = db.Column(db.String(20), default='submitted')  # submitted, replaced, withdrawn, late_rejected

    submitted_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow)
    receipt_code = db.Column(db.String(40), unique=True)

    declaration_accepted = db.Column(db.Boolean, default=False)

    submitted_by = db.relationship('User', foreign_keys=[submitted_by_id])

    def __repr__(self):
        return f'<Submission {self.receipt_code}>'
