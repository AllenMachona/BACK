from datetime import datetime

from app.extensions import db
from app.models.procurement import Procurement


PROCUREMENT_PLAN_STATUSES = ['upcoming', 'ongoing', 'cancelled', 'awarded']


class ProcurementPlanItem(db.Model):
    __tablename__ = 'procurement_plan_items'

    id = db.Column(db.Integer, primary_key=True)
    procurement_entity = db.Column(db.String(200), nullable=False)
    financial_year = db.Column(db.String(20), nullable=False, index=True)
    title = db.Column(db.String(300), nullable=False)
    description = db.Column(db.Text)
    ppra_code = db.Column(db.String(50))
    ppra_sub_code = db.Column(db.String(20))
    ppra_description = db.Column(db.Text)
    category = db.Column(db.String(50), nullable=False)
    method = db.Column(db.String(50), nullable=False)
    estimated_value = db.Column(db.Numeric(15, 2), nullable=False)
    planned_quarter = db.Column(db.String(2), nullable=False)
    status = db.Column(db.String(20), nullable=False, default='upcoming', index=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    created_by = db.relationship('User', foreign_keys=[created_by_id])

    @staticmethod
    def ppra_code_options():
        return Procurement.ppra_code_options()

    @staticmethod
    def ppra_sub_code_options():
        return Procurement.ppra_sub_code_options()

    @staticmethod
    def ppra_code_labels():
        return Procurement.ppra_code_labels()

    @staticmethod
    def ppra_classification_lookup():
        return Procurement.ppra_classification_lookup()

    @staticmethod
    def ppra_sub_codes_for(code):
        return Procurement.ppra_sub_codes_for(code)

    @staticmethod
    def ppra_description_for(code, sub_code=None):
        return Procurement.ppra_description_for(code, sub_code)

    def ppra_label(self):
        code = (self.ppra_code or '').strip()
        if not code:
            return ''
        lookup = Procurement.ppra_classification_lookup()
        data = lookup.get(code.split('-', 1)[0], {})
        label = (data.get('label') or '').strip()
        sub_code = (self.ppra_sub_code or '').strip()
        if sub_code and sub_code not in ('00', 'none'):
            sub_description = (data.get('subcodes') or {}).get(sub_code)
            if sub_description:
                return f"{label} - {sub_description}" if label else str(sub_description)
        return label

    def full_ppra_code(self):
        code = (self.ppra_code or '').strip()
        if self.ppra_sub_code and self.ppra_sub_code not in ('00', 'none'):
            if code and not code.endswith(f'-{self.ppra_sub_code}'):
                return f'{code}-{self.ppra_sub_code}'
            return self.ppra_sub_code if not code else code
        return code

    @classmethod
    def ensure_schema_columns(cls):
        from sqlalchemy import text
        for column_name, column_sql in {
            'ppra_code': 'ALTER TABLE procurement_plan_items ADD COLUMN ppra_code VARCHAR(50)',
            'ppra_sub_code': 'ALTER TABLE procurement_plan_items ADD COLUMN ppra_sub_code VARCHAR(20)',
            'ppra_description': 'ALTER TABLE procurement_plan_items ADD COLUMN ppra_description TEXT',
        }.items():
            try:
                probe = f'SELECT {column_name} FROM procurement_plan_items LIMIT 1' if db.engine.name == 'sqlite' else f'SELECT TOP 1 {column_name} FROM procurement_plan_items'
                db.session.execute(text(probe))
            except Exception:
                if db.engine.name != 'sqlite':
                    column_sql = column_sql.replace(' ADD COLUMN ', ' ADD ')
                db.session.execute(text(column_sql))
        db.session.commit()

    def status_label(self):
        labels = {
            'upcoming': 'Upcoming',
            'ongoing': 'Ongoing',
            'cancelled': 'Cancelled',
            'awarded': 'Awarded',
        }
        return labels.get(self.status, (self.status or 'upcoming').replace('_', ' ').title())