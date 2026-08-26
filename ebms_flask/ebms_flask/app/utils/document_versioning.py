"""Document versioning service for Undo/Restore functionality.

Handles creating, managing, and restoring document versions.
Ensures no version is ever permanently deleted - complete audit trail maintained.
"""
import os
from datetime import datetime
from flask_login import current_user
from app.extensions import db
from app.models.document_version import DocumentVersion
from app.utils.audit_enhanced import log_document_operation, log_version_restore


class DocumentVersioningService:
    """Service for managing document versions with complete history."""
    
    @staticmethod
    def create_version(document_type, entity_type, entity_id, file_path, file_name,
                      description=None, file_size_bytes=None, file_hash=None):
        """Create a new document version.
        
        Marks previous version as not current, preserves all history.
        
        Args:
            document_type: Type of document (e.g., 'itt', 'clarification', 'form_d')
            entity_type: Entity type (e.g., 'Procurement', 'Communication')
            entity_id: Entity ID
            file_path: Path to the file
            file_name: File name
            description: Change description
            file_size_bytes: File size in bytes
            file_hash: SHA-256 hash of the file
            
        Returns:
            DocumentVersion object
        """
        new_version = DocumentVersion.create_version(
            document_type=document_type,
            entity_type=entity_type,
            entity_id=entity_id,
            file_path=file_path,
            file_name=file_name,
            created_by_id=current_user.id if current_user.is_authenticated else None,
            description=description,
            file_size_bytes=file_size_bytes,
            file_hash=file_hash
        )
        db.session.commit()
        
        # Audit log
        log_document_operation(
            doc_type=document_type,
            entity_type=entity_type,
            entity_id=entity_id,
            operation='upload' if new_version.version_number == 1 else 'replace',
            file_name=file_name,
            reason=description
        )
        
        return new_version

    @staticmethod
    def get_current_version(document_type, entity_type, entity_id):
        """Get the current version of a document.
        
        Args:
            document_type: Type of document
            entity_type: Entity type
            entity_id: Entity ID
            
        Returns:
            DocumentVersion object or None
        """
        return DocumentVersion.query.filter_by(
            document_type=document_type,
            entity_type=entity_type,
            entity_id=entity_id,
            is_current=True
        ).first()

    @staticmethod
    def get_version_history(document_type, entity_type, entity_id):
        """Get all versions of a document in chronological order.
        
        Args:
            document_type: Type of document
            entity_type: Entity type
            entity_id: Entity ID
            
        Returns:
            List of DocumentVersion objects
        """
        return DocumentVersion.query.filter_by(
            document_type=document_type,
            entity_type=entity_type,
            entity_id=entity_id
        ).order_by(DocumentVersion.version_number.asc()).all()

    @staticmethod
    def get_version(document_type, entity_type, entity_id, version_number):
        """Get a specific version.
        
        Args:
            document_type: Type of document
            entity_type: Entity type
            entity_id: Entity ID
            version_number: Version number to retrieve
            
        Returns:
            DocumentVersion object or None
        """
        return DocumentVersion.query.filter_by(
            document_type=document_type,
            entity_type=entity_type,
            entity_id=entity_id,
            version_number=version_number
        ).first()

    @staticmethod
    def restore_version(document_type, entity_type, entity_id, version_number, reason=None):
        """Restore a previous document version.
        
        Creates a NEW version that duplicates the restored version's content.
        Original version history is NEVER erased.
        
        Args:
            document_type: Type of document
            entity_type: Entity type
            entity_id: Entity ID
            version_number: Version to restore from
            reason: Why the version is being restored
            
        Returns:
            New DocumentVersion object
            
        Raises:
            ValueError: If version not found
        """
        restored_version = DocumentVersion.restore_version(
            document_type=document_type,
            entity_type=entity_type,
            entity_id=entity_id,
            version_number_to_restore=version_number,
            restored_by_id=current_user.id if current_user.is_authenticated else None,
            restoration_reason=reason
        )
        db.session.commit()
        
        # Audit log
        log_version_restore(
            document_type=document_type,
            entity_type=entity_type,
            entity_id=entity_id,
            version_number=version_number,
            reason=reason
        )
        
        return restored_version

    @staticmethod
    def get_file_path(version):
        """Get the full file path for a version.
        
        Args:
            version: DocumentVersion object
            
        Returns:
            Full path to the file
        """
        return version.file_path if version else None

    @staticmethod
    def file_exists(version):
        """Check if the file for a version still exists.
        
        Args:
            version: DocumentVersion object
            
        Returns:
            True if file exists, False otherwise
        """
        if not version or not version.file_path:
            return False
        return os.path.exists(version.file_path)

    @staticmethod
    def get_version_download_info(document_type, entity_type, entity_id, version_number=None):
        """Get download information for a specific version.
        
        Args:
            document_type: Type of document
            entity_type: Entity type
            entity_id: Entity ID
            version_number: Specific version (None = current)
            
        Returns:
            Dict with file_path, file_name, version_number, or None
        """
        if version_number:
            version = DocumentVersioningService.get_version(
                document_type, entity_type, entity_id, version_number
            )
        else:
            version = DocumentVersioningService.get_current_version(
                document_type, entity_type, entity_id
            )
        
        if not version or not DocumentVersioningService.file_exists(version):
            return None
        
        return {
            'file_path': version.file_path,
            'file_name': version.file_name,
            'version_number': version.version_number,
            'is_current': version.is_current,
            'created_at': version.created_at,
            'file_size_bytes': version.file_size_bytes
        }
