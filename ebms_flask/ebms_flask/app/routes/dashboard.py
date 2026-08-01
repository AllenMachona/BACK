from datetime import datetime, timedelta
from flask import Blueprint, render_template, redirect, url_for
from flask_login import login_required, current_user
from app.models.procurement import Procurement
from app.models.bidder import Bidder
from app.models.submission import Submission

dashboard_bp = Blueprint('dashboard', __name__)


@dashboard_bp.route('/')
def index():
    if not current_user.is_authenticated:
        return redirect(url_for('auth.login'))
    if current_user.has_role('bidder'):
        return redirect(url_for('bidders.portal'))
    return redirect(url_for('dashboard.dashboard'))


@dashboard_bp.route('/dashboard')
@login_required
def dashboard():
    active_tenders = Procurement.query.filter(
        Procurement.status.in_(['published', 'submission_open'])
    ).count()

    pending_evaluations = Procurement.query.filter(
        Procurement.status.in_(['compliance_evaluation', 'technical_evaluation', 'financial_evaluation'])
    ).count()

    registered_bidders = Bidder.query.count()

    since = datetime.utcnow() - timedelta(hours=24)
    recent_submissions = Submission.query.filter(Submission.submitted_at >= since).count()

    recent_procurements = Procurement.query.order_by(Procurement.updated_at.desc()).limit(6).all()

    return render_template(
        'dashboard.html',
        active_tenders=active_tenders,
        pending_evaluations=pending_evaluations,
        registered_bidders=registered_bidders,
        recent_submissions=recent_submissions,
        recent_procurements=recent_procurements,
    )
