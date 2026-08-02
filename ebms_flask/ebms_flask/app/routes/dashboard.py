from datetime import datetime, timedelta
from flask import Blueprint, render_template, redirect, url_for, request, abort
from flask_login import login_required, current_user
from app.models.procurement import Procurement
from app.models.bidder import Bidder
from app.models.submission import Submission

dashboard_bp = Blueprint('dashboard', __name__)

PUBLIC_PROCUREMENT_STATUSES = ['published', 'submission_open', 'clarification_period', 'award_published']


@dashboard_bp.route('/')
def index():
    if current_user.is_authenticated:
        if current_user.has_role('bidder'):
            return redirect(url_for('bidders.portal'))
        return redirect(url_for('dashboard.dashboard'))

    public_tenders = Procurement.query.filter(
        Procurement.status.in_(PUBLIC_PROCUREMENT_STATUSES)
    ).order_by(Procurement.submission_deadline.asc().nullslast()).limit(6).all()

    stats = {
        'tenders': Procurement.query.filter(Procurement.status.in_(['published', 'submission_open'])).count(),
        'procurement_entities': Procurement.query.filter(Procurement.procurement_entity.isnot(None)).distinct(Procurement.procurement_entity).count(),
        'open_today': Procurement.query.filter(Procurement.status == 'submission_open').count(),
        'current_tenders': Procurement.query.filter(Procurement.status.in_(['published', 'submission_open'])).count(),
        'awarded_tenders': Procurement.query.filter(Procurement.status == 'award_published').count(),
    }

    return render_template('public_home.html', tenders=public_tenders, stats=stats)


@dashboard_bp.route('/tenders')
def public_tenders():
    query = Procurement.query.filter(Procurement.status.in_(PUBLIC_PROCUREMENT_STATUSES))

    search_term = (request.args.get('q') or '').strip()
    category = (request.args.get('category') or 'all').strip().lower()
    status_filter = (request.args.get('status') or 'all').strip().lower()

    if search_term:
        like_term = f'%{search_term}%'
        query = query.filter(
            (Procurement.title.ilike(like_term)) |
            (Procurement.tender_number.ilike(like_term)) |
            (Procurement.procurement_entity.ilike(like_term)) |
            (Procurement.description.ilike(like_term))
        )

    if category and category != 'all':
        query = query.filter(Procurement.category == category)

    if status_filter == 'current':
        query = query.filter(Procurement.status.in_(['published', 'submission_open']))
    elif status_filter == 'open':
        query = query.filter(Procurement.status == 'submission_open')
    elif status_filter == 'awarded':
        query = query.filter(Procurement.status == 'award_published')

    tenders = query.order_by(Procurement.submission_deadline.asc().nullslast()).all()
    categories = ['all', 'goods', 'works', 'services', 'consultancy', 'non_consultancy']
    return render_template('public_tenders.html', tenders=tenders, categories=categories,
                           selected_category=category, selected_status=status_filter, search_term=search_term)


@dashboard_bp.route('/tenders/<int:procurement_id>')
def public_tender_detail(procurement_id):
    procurement = Procurement.query.get_or_404(procurement_id)
    if procurement.status not in ('published', 'submission_open', 'clarification_period', 'award_published'):
        abort(404)
    return render_template('public_tender_detail.html', procurement=procurement)


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
