from datetime import datetime
from app.extensions import db


class Communication(db.Model):
    """SOAR 7.6: questions, clarifications, addenda and notices — the single
    official channel through which anything communicated to bidders must pass.
    
    Enhanced to support:
    - visibility_type: 'public' (all bidders) or 'targeted' (selected bidders)
    - document versioning: tracks all versions of attached documents
    """
    __tablename__ = 'communications'

    id = db.Column(db.Integer, primary_key=True)
    procurement_id = db.Column(db.Integer, db.ForeignKey('procurements.id'), nullable=False)
    type = db.Column(db.String(20), nullable=False)  # question, clarification, addendum, notice, advertisement
    content = db.Column(db.Text, nullable=False)
    file_path = db.Column(db.String(500))
    original_filename = db.Column(db.String(255))

    from_user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    from_bidder_id = db.Column(db.Integer, db.ForeignKey('bidders.id'))  # set when a bidder asks a question
    is_public = db.Column(db.Boolean, default=True)
    
    # Visibility control (enhanced)
    # 'public' = all eligible bidders can see
    # 'targeted' = only selected bidders (via ClarificationVisibility) can see
    visibility_type = db.Column(db.String(20), default='public')

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    from_user = db.relationship('User', foreign_keys=[from_user_id])
    from_bidder = db.relationship('Bidder', foreign_keys=[from_bidder_id])

    @classmethod
    def ensure_schema_columns(cls):
        from sqlalchemy import text
        columns_to_add = {
            'file_path': 'ALTER TABLE communications ADD COLUMN file_path VARCHAR(500)',
            'original_filename': 'ALTER TABLE communications ADD COLUMN original_filename VARCHAR(255)',
            'visibility_type': "ALTER TABLE communications ADD COLUMN visibility_type VARCHAR(20) DEFAULT 'public'",
            'updated_at': 'ALTER TABLE communications ADD COLUMN updated_at DATETIME DEFAULT CURRENT_TIMESTAMP',
        }
        for column_name, column_sql in columns_to_add.items():
            try:
                db.session.execute(text(f'SELECT {column_name} FROM communications LIMIT 1'))
            except Exception:
                try:
                    db.session.execute(text(column_sql))
                except Exception:
                    pass  # Column might already exist
        db.session.commit()
    
    def can_bidder_view(self, bidder_id):
        """Check if a bidder can view this communication.
        
        - Public: all bidders can view
        - Targeted: only bidders in ClarificationVisibility can view
        
        This check is ALWAYS enforced server-side.
        """
        if self.visibility_type == 'public':
            return True
        
        # For targeted, check if bidder has explicit access
        from app.models.clarification import ClarificationVisibility
        access = ClarificationVisibility.query.filter_by(
            communication_id=self.id,
            bidder_id=bidder_id
        ).first()
        return access is not None and access.is_active()

    def __repr__(self):
        return f'<Communication {self.type} visibility={self.visibility_type}>'
