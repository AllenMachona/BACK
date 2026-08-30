from datetime import datetime

from app.extensions import db


PROCUREMENT_PLAN_STATUSES = ['upcoming', 'ongoing', 'cancelled', 'awarded']


class ProcurementPlanItem(db.Model):
    __tablename__ = 'procurement_plan_items'

    id = db.Column(db.Integer, primary_key=True)
    procurement_entity = db.Column(db.String(200), nullable=False)
    financial_year = db.Column(db.String(20), nullable=False, index=True)
    title = db.Column(db.String(300), nullable=False)
    description = db.Column(db.Text)
    category = db.Column(db.String(50), nullable=False)
    method = db.Column(db.String(50), nullable=False)
    estimated_value = db.Column(db.Numeric(15, 2), nullable=False)
    planned_quarter = db.Column(db.String(2), nullable=False)
    status = db.Column(db.String(20), nullable=False, default='upcoming', index=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    created_by = db.relationship('User', foreign_keys=[created_by_id])

    def status_label(self):
        labels = {
            'upcoming': 'Upcoming',
            'ongoing': 'Ongoing',
            'cancelled': 'Cancelled',
            'awarded': 'Awarded',
        }
        return labels.get(self.status, (self.status or 'upcoming').replace('_', ' ').title())