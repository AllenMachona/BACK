"""Document versioning system to support Undo/Restore functionality.

Never permanently overwrites documents. Keeps Version 1, 2, 3, etc.
Allows authorized staff to restore previous versions with audit trail.
"""
from datetime import datetime
from app.extensions import db


class DocumentVersion(db.Model):
    """Immutable version history for all significant documents.
    
    Supports:
    - Tender documents (ITT, Form D, Form E)
    - Clarification documents
    - Procurement addenda
    - Any audit-critical file
    
    Never deletes previous versions. Each version is independently accessible
    and restorable.
    """
    __tablename__ = 'document_versions'

    id = db.Column(db.Integer, primary_key=True)
    
    # Document identification
    document_type = db.Column(db.String(50), nullable=False, index=True)  # itt, clarification, addendum, form_d, etc.
    entity_type = db.Column(db.String(50), nullable=False, index=True)    # procurement, communication, etc.
    entity_id = db.Column(db.Integer, nullable=False, index=True)         # procurement_id, communication_id, etc.
    
    # Version tracking
    version_number = db.Column(db.Integer, nullable=False)                # 1, 2, 3, ...
    is_current = db.Column(db.Boolean, default=True, index=True)          # Only one version is "current"
    
    # File storage
    file_path = db.Column(db.String(500), nullable=False)
    file_name = db.Column(db.String(300), nullable=False)
    file_size_bytes = db.Column(db.Integer)
    file_hash = db.Column(db.String(64))  # SHA-256
    
    # Who made this version
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    
    # Restoration information (if this version was restored)
    restored_from_version = db.Column(db.Integer)  # Version number of the version this was restored from
    restored_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))     # Who restored it
    restored_at = db.Column(db.DateTime)                                   # When it was restored
    restoration_reason = db.Column(db.Text)                                # Why it was restored
    
    # Metadata
    description = db.Column(db.Text)  # Change description
    
    # Relationships
    created_by = db.relationship('User', foreign_keys=[created_by_id], backref='created_document_versions')
    restored_by = db.relationship('User', foreign_keys=[restored_by_id], backref='restored_document_versions')
    
    def __repr__(self):
        return f'<DocumentVersion {self.document_type} v{self.version_number} {"(current)" if self.is_current else ""}>'

    @classmethod
    def create_version(cls, document_type, entity_type, entity_id, file_path, file_name, 
                      created_by_id, description=None, file_size_bytes=None, file_hash=None):
        """Create a new version of a document.
        
        Marks the previous version as not current (is_current=False).
        This preserves the entire history while marking what's active.
        """
        # Mark all previous versions as not current
        previous_versions = cls.query.filter_by(
            document_type=document_type,
            entity_type=entity_type,
            entity_id=entity_id,
            is_current=True
        ).all()
        
        version_number = 1
        if previous_versions:
            version_number = max(v.version_number for v in previous_versions) + 1
            for v in previous_versions:
                v.is_current = False
        
        new_version = cls(
            document_type=document_type,
            entity_type=entity_type,
            entity_id=entity_id,
            version_number=version_number,
            is_current=True,
            file_path=file_path,
            file_name=file_name,
            file_size_bytes=file_size_bytes,
            file_hash=file_hash,
            created_by_id=created_by_id,
            description=description,
        )
        db.session.add(new_version)
        return new_version

    @classmethod
    def restore_version(cls, document_type, entity_type, entity_id, version_number_to_restore,
                       restored_by_id, restoration_reason=None):
        """Restore a previous version as the current version.
        
        Creates a NEW version entry that points back to the restored version.
        The original version history is never erased.
        Returns the new version entry.
        """
        # Get the version to restore
        version_to_restore = cls.query.filter_by(
            document_type=document_type,
            entity_type=entity_type,
            entity_id=entity_id,
            version_number=version_number_to_restore
        ).first()
        
        if not version_to_restore:
            raise ValueError(f"Version {version_number_to_restore} not found")
        
        # Mark current version as not current
        current = cls.query.filter_by(
            document_type=document_type,
            entity_type=entity_type,
            entity_id=entity_id,
            is_current=True
        ).first()
        
        if current:
            current.is_current = False
        
        # Get next version number
        all_versions = cls.query.filter_by(
            document_type=document_type,
            entity_type=entity_type,
            entity_id=entity_id
        ).all()
        next_version_number = max((v.version_number for v in all_versions), default=0) + 1
        
        # Create new version that references the restored version
        restored_version = cls(
            document_type=document_type,
            entity_type=entity_type,
            entity_id=entity_id,
            version_number=next_version_number,
            is_current=True,
            file_path=version_to_restore.file_path,
            file_name=version_to_restore.file_name,
            file_size_bytes=version_to_restore.file_size_bytes,
            file_hash=version_to_restore.file_hash,
            created_by_id=restored_by_id,
            restored_from_version=version_number_to_restore,
            restored_by_id=restored_by_id,
            restored_at=datetime.utcnow(),
            restoration_reason=restoration_reason,
            description=f"Restored from version {version_number_to_restore}"
        )
        db.session.add(restored_version)
        return restored_version
