from datetime import datetime, timedelta
from flask import Blueprint, render_template
from flask_login import login_required
from sqlalchemy import func
from app.extensions import db
from app.models.procurement import Procurement
from app.models.submission import Submission
from app.models.complaint import Complaint
from app.utils.decorators import permission_required

reports_bp = Blueprint('reports', __name__, url_prefix='/reports')


@reports_bp.route('/operational')
@login_required
@permission_required('can_view_all_records')
def operational():
    open_tenders = Procurement.query.filter(
        Procurement.status.in_(['published', 'submission_open'])
    ).count()

    soon_cutoff = datetime.utcnow() + timedelta(days=7)
    closing_soon = Procurement.query.filter(
        Procurement.status == 'submission_open',
        Procurement.submission_deadline.isnot(None),
        Procurement.submission_deadline <= soon_cutoff,
    ).count()

    total_submissions = Submission.query.filter_by(status='submitted').count()

    active_complaints = Complaint.query.filter(
        Complaint.status.in_(['received', 'under_review', 'escalated'])
    ).count()

    by_category = db.session.query(
        Procurement.category, func.count(Procurement.id), func.coalesce(func.sum(Procurement.estimated_value), 0)
    ).group_by(Procurement.category).all()

    by_method = db.session.query(
        Procurement.method, func.count(Procurement.id)
    ).group_by(Procurement.method).all()
    total_methods = sum(count for _, count in by_method) or 1

    overdue_closing = Procurement.query.filter(
        Procurement.status == 'submission_open',
        Procurement.submission_deadline.isnot(None),
        Procurement.submission_deadline < datetime.utcnow(),
    ).count()

    cancelled_count = Procurement.query.filter_by(cancelled=True).count()

    return render_template(
        'reports_operational.html',
        open_tenders=open_tenders,
        closing_soon=closing_soon,
        total_submissions=total_submissions,
        active_complaints=active_complaints,
        by_category=by_category,
        by_method=[(m, c, round(c / total_methods * 100)) for m, c in by_method],
        overdue_closing=overdue_closing,
        cancelled_count=cancelled_count,
    )
