from datetime import datetime
from app.extensions import db


class Procurement(db.Model):
    __tablename__ = 'procurements'

    id = db.Column(db.Integer, primary_key=True)
    tender_number = db.Column(db.String(50), unique=True, nullable=False, index=True)
    title = db.Column(db.String(300), nullable=False)
    description = db.Column(db.Text)
    category = db.Column(db.String(30), nullable=False)  # works, services, consultancy, supplies, combination
    procurement_entity = db.Column(db.String(200))
    ppra_code = db.Column(db.String(50))
    ppra_sub_code = db.Column(db.String(20))
    method = db.Column(db.String(30), nullable=False)  # open_domestic, open_international, restricted, rfq, direct, rfp...
    evaluation_method = db.Column(db.String(30))        # pass_fail, scored, weighted, least_cost, quality_cost
    envelope_type = db.Column(db.String(10), default='single')  # single, dual
    estimated_value = db.Column(db.Numeric(15, 2), nullable=False)
    user_department = db.Column(db.String(150))

    submission_deadline = db.Column(db.DateTime)
    clarification_deadline = db.Column(db.DateTime)
    opening_scheduled_at = db.Column(db.DateTime)

    # Status follows SOAR Appendix C's bid status lifecycle.
    status = db.Column(db.String(30), default='draft', index=True)

    cancelled = db.Column(db.Boolean, default=False)
    cancelled_reason = db.Column(db.Text)
    cancelled_at = db.Column(db.DateTime)
    replacement_of_id = db.Column(db.Integer, db.ForeignKey('procurements.id'))

    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Tender Document Fee & Document Storage
    tender_fee = db.Column(db.Numeric(15, 2), default=0.00)

    # Requesting user/department internal forms
    form_d_file_path = db.Column(db.String(500))
    form_d_filename = db.Column(db.String(300))
    form_e_file_path = db.Column(db.String(500))
    form_e_filename = db.Column(db.String(300))

    # Bidder-facing tender documents (gated by payment verification)
    rfce_file_path = db.Column(db.String(500))
    rfce_filename = db.Column(db.String(300))
    itt_file_path = db.Column(db.String(500))
    itt_filename = db.Column(db.String(300))
    # Bidder-facing document that is free to view (no payment required),
    # e.g. a Request for Quotation document.
    rfq_file_path = db.Column(db.String(500))
    rfq_filename = db.Column(db.String(300))

    # Relationships
    lots = db.relationship('Lot', backref='procurement', lazy='dynamic', cascade='all, delete-orphan')
    submissions = db.relationship('Submission', backref='procurement', lazy='dynamic')
    criteria = db.relationship('EvaluationCriteria', backref='procurement', lazy='dynamic')
    evaluations = db.relationship('Evaluation', backref='procurement', lazy='dynamic')
    committee_members = db.relationship('CommitteeMember', backref='procurement', lazy='dynamic')
    communications = db.relationship('Communication', backref='procurement', lazy='dynamic')
    complaints = db.relationship('Complaint', backref='procurement', lazy='dynamic')
    award = db.relationship('Award', backref='procurement', uselist=False)
    replacement = db.relationship('Procurement', remote_side=[id], backref='replaced_by')

    def has_form_d(self):
        return bool(self.form_d_file_path and self.form_d_filename)

    def has_form_e(self):
        return bool(self.form_e_file_path and self.form_e_filename)

    def has_rfce(self):
        return bool(self.rfce_file_path and self.rfce_filename)

    def has_itt(self):
        return bool(self.itt_file_path and self.itt_filename)

    def has_rfq(self):
        return bool(self.rfq_file_path and self.rfq_filename)

    def has_tender_documents(self):
        return self.has_rfce() or self.has_itt() or self.has_rfq()

    @staticmethod
    def ppra_code_options():
        base_codes = ['100', '101', '102', '103', '104', '105', '106', '107', '108', '109', '110']
        sub_codes = ['00', '01', '02', '03', '04', '05', '06', '07', '08', '09', '10', '11', '12']
        all_codes = list(base_codes)
        for b in base_codes:
            for s in sub_codes:
                if s != '00':
                    all_codes.append(f"{b}-{s}")
        return all_codes

    @staticmethod
    def ppra_sub_code_options():
        return ['00', '01', '02', '03', '04', '05', '06', '07', '08', '09', '10', '11', '12']

    def full_ppra_code(self):
        code = (self.ppra_code or '').strip()
        if self.ppra_sub_code and self.ppra_sub_code not in ('00', 'none'):
            if code and not code.endswith(f'-{self.ppra_sub_code}'):
                return f'{code}-{self.ppra_sub_code}'
            return self.ppra_sub_code if not code else code
        return code

    def status_label(self):
        return self.status.replace('_', ' ').title()

    def bid_count(self):
        return self.submissions.filter_by(status='submitted').count()

    def committee_chair(self):
        return self.committee_members.filter_by(role='chair').first()

    def can_committee_member_access(self, committee_member):
        return bool(committee_member and committee_member.is_access_active())

    def can_transition_to_contract(self):
        if self.status not in ('award_published', 'cooling_off', 'complaint_hold', 'ready_for_contract'):
            return False

        if self.award and self.award.cooling_off_active():
            return False

        active_complaints = list(self.complaints) if hasattr(self, 'complaints') else []
        unresolved = [
            complaint for complaint in active_complaints
            if getattr(complaint, 'status', None) in ('received', 'under_review', 'escalated')
        ]
        return not unresolved

    def check_governance_rules(self, direct_threshold=500000, open_threshold=500000):
        result = {'errors': [], 'warnings': []}
        total_value = float(self.estimated_value or 0)

        lots = list(self.lots) if hasattr(self, 'lots') else []
        lot_total = 0.0
        for lot in lots:
            try:
                lot_total += float(lot.estimated_value or 0)
            except (TypeError, ValueError):
                continue

        if self.method == 'direct' and total_value > direct_threshold:
            result['errors'].append('direct_procurement_exceeds_threshold')

        if self.method in ('open_domestic', 'open_international', 'rfp', 'rfq') and total_value > open_threshold:
            result['warnings'].append('open_procurement_high_value_review')

        if len(lots) > 1 and total_value >= open_threshold:
            result['warnings'].append('lot_splitting_risk')

        if len(lots) > 1 and lot_total >= direct_threshold:
            result['warnings'].append('lot_splitting_risk')

        return result

    @classmethod
    def ensure_schema_columns(cls):
        from sqlalchemy import text
        for column_name, column_sql in {
            'procurement_entity': 'ALTER TABLE procurements ADD COLUMN procurement_entity VARCHAR(200)',
            'ppra_sub_code': 'ALTER TABLE procurements ADD COLUMN ppra_sub_code VARCHAR(20)',
            'clarification_deadline': 'ALTER TABLE procurements ADD COLUMN clarification_deadline DATETIME',
            'tender_fee': 'ALTER TABLE procurements ADD COLUMN tender_fee NUMERIC(15, 2) DEFAULT 0.00',
            'form_d_file_path': 'ALTER TABLE procurements ADD COLUMN form_d_file_path VARCHAR(500)',
            'form_d_filename': 'ALTER TABLE procurements ADD COLUMN form_d_filename VARCHAR(300)',
            'form_e_file_path': 'ALTER TABLE procurements ADD COLUMN form_e_file_path VARCHAR(500)',
            'form_e_filename': 'ALTER TABLE procurements ADD COLUMN form_e_filename VARCHAR(300)',
            'rfce_file_path': 'ALTER TABLE procurements ADD COLUMN rfce_file_path VARCHAR(500)',
            'rfce_filename': 'ALTER TABLE procurements ADD COLUMN rfce_filename VARCHAR(300)',
            'itt_file_path': 'ALTER TABLE procurements ADD COLUMN itt_file_path VARCHAR(500)',
            'itt_filename': 'ALTER TABLE procurements ADD COLUMN itt_filename VARCHAR(300)',
            'rfq_file_path': 'ALTER TABLE procurements ADD COLUMN rfq_file_path VARCHAR(500)',
            'rfq_filename': 'ALTER TABLE procurements ADD COLUMN rfq_filename VARCHAR(300)',
        }.items():
            try:
                db.session.execute(text(f'SELECT {column_name} FROM procurements LIMIT 1'))
            except Exception:
                db.session.execute(text(column_sql))
        db.session.commit()

    def __repr__(self):
        return f'<Procurement {self.tender_number}>'


class Lot(db.Model):
    """Optional sub-division of a procurement (SOAR FR-INIT-007: lot splitting)."""
    __tablename__ = 'lots'

    id = db.Column(db.Integer, primary_key=True)
    procurement_id = db.Column(db.Integer, db.ForeignKey('procurements.id'), nullable=False)
    lot_number = db.Column(db.String(20), nullable=False)
    description = db.Column(db.Text)
    estimated_value = db.Column(db.Numeric(15, 2))

    def __repr__(self):
        return f'<Lot {self.lot_number}>'
