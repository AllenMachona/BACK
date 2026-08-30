#!/usr/bin/env python
"""
Delete all Evaluator Assignment Test Tender records and associated uploads folders.
This script removes test data while preserving user-created procurements.
"""
import os
import sys
import shutil
from pathlib import Path

# Add parent directory to path to import app
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.extensions import db
from app.models import Procurement, Notification
from app.models.submission import Submission
from app.models.evaluator_assignment import EvaluatorAssignment
from app.models.evaluation import Evaluation
from app.models.committee import CommitteeMember
from app.models.communication import Communication
from app.models.complaint import Complaint
from app.models.award import Award
from app.models.clarification import ClarificationVisibility, ClarificationAccess
from app.models.history import ProcurementHistory, SubmissionHistory
from app.models.evaluator_feedback import EvaluatorFeedback
from app.models.payment import BidderPayment, BidderDocumentAccess
from app.models.bidder_compliance import BidderComplianceDocument
from app.models.budget_entry import BudgetEntry
from app.models.procurement_plan import ProcurementPlanItem

def delete_test_tenders():
    """Delete all Evaluator Assignment Test Tender records and folders."""
    app = create_app()
    
    with app.app_context():
        # Find all procurements with "Evaluator Assignment Test Tender" in title
        test_tenders = Procurement.query.filter(
            Procurement.title.ilike('%Evaluator Assignment Test Tender%')
        ).all()
        
        if not test_tenders:
            print("✓ No Evaluator Assignment Test Tender records found.")
            return
        
        print(f"\nFound {len(test_tenders)} Evaluator Assignment Test Tender records to delete:")
        
        tender_numbers = []
        tender_ids = []
        for tender in test_tenders:
            print(f"  - {tender.tender_number}: {tender.title}")
            tender_numbers.append(tender.tender_number)
            tender_ids.append(tender.id)
        
        print("\nDeleting related records...")
        
        # Delete in this order to respect foreign key constraints
        for tender_id in tender_ids:
            # 1. Delete evaluator feedback
            try:
                EvaluatorFeedback.query.filter(EvaluatorFeedback.procurement_id == tender_id).delete()
            except:
                pass
            
            # 2. Delete evaluator assignments
            try:
                EvaluatorAssignment.query.filter(EvaluatorAssignment.procurement_id == tender_id).delete()
            except:
                pass
            
            # 3. Delete evaluations
            try:
                Evaluation.query.filter(Evaluation.procurement_id == tender_id).delete()
            except:
                pass
            
            # 4. Delete submissions (and related submission history)
            try:
                submissions = Submission.query.filter(Submission.procurement_id == tender_id).all()
                for sub in submissions:
                    SubmissionHistory.query.filter(SubmissionHistory.submission_id == sub.id).delete()
                Submission.query.filter(Submission.procurement_id == tender_id).delete()
            except:
                pass
            
            # 5. Delete committee members
            try:
                CommitteeMember.query.filter(CommitteeMember.procurement_id == tender_id).delete()
            except:
                pass
            
            # 6. Delete communications
            try:
                Communication.query.filter(Communication.procurement_id == tender_id).delete()
            except:
                pass
            
            # 7. Delete complaints
            try:
                Complaint.query.filter(Complaint.procurement_id == tender_id).delete()
            except:
                pass
            
            # 8. Delete clarifications
            try:
                ClarificationVisibility.query.filter(ClarificationVisibility.procurement_id == tender_id).delete()
                ClarificationAccess.query.filter(ClarificationAccess.procurement_id == tender_id).delete()
            except:
                pass
            
            # 9. Delete awards
            try:
                Award.query.filter(Award.procurement_id == tender_id).delete()
            except:
                pass
            
            # 10. Delete procurement history
            try:
                ProcurementHistory.query.filter(ProcurementHistory.procurement_id == tender_id).delete()
            except:
                pass
            
            # 11. Delete notifications
            try:
                Notification.query.filter(Notification.procurement_id == tender_id).delete()
            except:
                pass
            
            # 12. Delete payments and document access
            try:
                BidderDocumentAccess.query.filter(BidderDocumentAccess.procurement_id == tender_id).delete()
            except:
                pass
            
            # 13. Delete bidder compliance documents
            try:
                BidderComplianceDocument.query.filter(BidderComplianceDocument.procurement_id == tender_id).delete()
            except:
                pass
            
            # 14. Delete budget entries
            try:
                BudgetEntry.query.filter(BudgetEntry.procurement_id == tender_id).delete()
            except:
                pass
            
            # 15. Delete procurement plan items
            try:
                ProcurementPlanItem.query.filter(ProcurementPlanItem.procurement_id == tender_id).delete()
            except:
                pass
        
        db.session.commit()
        print("✓ Related records deleted.")
        
        # Delete procurement records
        print("\nDeleting procurement records...")
        for tender in test_tenders:
            try:
                db.session.delete(tender)
                print(f"  ✓ Deleted record: {tender.tender_number}")
            except Exception as e:
                print(f"  ✗ Error deleting {tender.tender_number}: {e}")
        
        db.session.commit()
        print("✓ Database records deleted successfully.")
        
        # Delete associated folders
        print("\nDeleting associated upload folders...")
        uploads_dir = Path(__file__).parent.parent / "uploads"
        
        for tender_num in tender_numbers:
            # Look for folders matching the tender number pattern
            for folder in uploads_dir.iterdir():
                if folder.is_dir() and tender_num in folder.name and "Evaluator_Assignment_Test_Tender" in folder.name:
                    try:
                        shutil.rmtree(folder)
                        print(f"  ✓ Deleted folder: {folder.name}")
                    except Exception as e:
                        print(f"  ✗ Error deleting folder {folder.name}: {e}")
        
        print("\n✓ Cleanup completed successfully!")
        print("\nYour personal procurements have been preserved.")

if __name__ == '__main__':
    delete_test_tenders()
