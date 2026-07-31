# Import order matters here only in that every model must be imported
# somewhere before db.create_all() / Alembic autogenerate runs, so that
# SQLAlchemy knows about all mapped classes and their relationships.
from app.models.role import Role
from app.models.user import User
from app.models.procurement import Procurement, Lot
from app.models.bidder import Bidder
from app.models.submission import Submission
from app.models.committee import CommitteeMember, EvaluationCriteria
from app.models.evaluation import Evaluation, ScoreSheet
from app.models.award import Award
from app.models.complaint import Complaint
from app.models.communication import Communication
from app.models.audit import AuditLog
from app.models.notification import Notification

__all__ = [
    'Role', 'User', 'Procurement', 'Lot', 'Bidder', 'Submission',
    'CommitteeMember', 'EvaluationCriteria', 'Evaluation', 'ScoreSheet',
    'Award', 'Complaint', 'Communication', 'AuditLog', 'Notification',
]
