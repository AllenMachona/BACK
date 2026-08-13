from datetime import datetime, timedelta
from flask import Blueprint, render_template, redirect, url_for, request, abort
from flask_login import login_required, current_user
from sqlalchemy import func
from app.extensions import db
from app.models.procurement import Procurement
from app.models.bidder import Bidder
from app.models.submission import Submission

dashboard_bp = Blueprint('dashboard', __name__)

PUBLIC_PROCUREMENT_STATUSES = ['published', 'submission_open', 'clarification_period', 'award_published']


def _category_key(category_value):
    category = (category_value or '').strip().lower().replace('-', '_')
    if category in {'goods', 'supplies', 'materials'}:
        return 'goods'
    if category in {'works', 'construction'}:
        return 'works'
    if category in {'consultancy', 'services', 'professional_services'}:
        return 'consultancy'
    if category in {'non_consultancy', 'non_consultancy_services'}:
        return 'non_consultancy'
    return 'goods' if category in {'', 'all'} else category


def _build_category_counts(queryset):
    counts = {'goods': 0, 'works': 0, 'consultancy': 0, 'non_consultancy': 0}
    for tender in queryset:
        counts[_category_key(tender.category)] = counts.get(_category_key(tender.category), 0) + 1
    return counts


@dashboard_bp.route('/')
def index():
    if current_user.is_authenticated:
        if current_user.has_role('bidder'):
            return redirect(url_for('bidders.portal'))
        return redirect(url_for('dashboard.dashboard'))

    public_query = Procurement.query.filter(Procurement.status.in_(PUBLIC_PROCUREMENT_STATUSES))
    public_tenders = public_query.order_by(Procurement.submission_deadline.asc().nullslast()).limit(6).all()
    opened_tenders = public_query.filter(Procurement.status == 'submission_open').order_by(Procurement.submission_deadline.asc().nullslast()).limit(4).all()
    awarded_tenders = Procurement.query.filter(Procurement.status == 'award_published').order_by(Procurement.submission_deadline.asc().nullslast()).limit(3).all()
    annual_plan_tenders = public_query.filter(Procurement.status == 'published').order_by(Procurement.created_at.desc()).limit(3).all()
    current_tenders = Procurement.query.filter(Procurement.status.in_(['published', 'submission_open'])).order_by(Procurement.submission_deadline.asc().nullslast()).limit(4).all()
    category_counts = _build_category_counts(public_query.all())
    closing_soon = public_query.filter(
        Procurement.submission_deadline.isnot(None),
        Procurement.submission_deadline >= datetime.utcnow(),
        Procurement.submission_deadline <= datetime.utcnow() + timedelta(days=14),
    ).count()

    total_award_value = db.session.query(
        func.coalesce(func.sum(Procurement.estimated_value), 0)
    ).filter(Procurement.status == 'award_published').scalar() or 0

    stats = {
        'total_tenders': Procurement.query.count(),
        'procurement_entities': Procurement.query.filter(Procurement.procurement_entity.isnot(None)).distinct(Procurement.procurement_entity).count(),
        'current_tenders': Procurement.query.filter(Procurement.status.in_(['published', 'submission_open'])).count(),
        'closing_soon': closing_soon,
        'awarded_tenders': Procurement.query.filter(Procurement.status == 'award_published').count(),
        'total_award_value': float(total_award_value),
    }

    return render_template(
        'public_home.html',
        tenders=public_tenders,
        current_tenders=current_tenders,
        opened_tenders=opened_tenders,
        awarded_tenders=awarded_tenders,
        annual_plan_tenders=annual_plan_tenders,
        stats=stats,
        category_counts=category_counts,
    )


@dashboard_bp.route('/tenders')
def public_tenders():
    query = Procurement.query.filter(Procurement.status.in_(PUBLIC_PROCUREMENT_STATUSES))

    search_term = (request.args.get('q') or '').strip()
    category = (request.args.get('category') or 'all').strip().lower().replace('-', '_')
    entity = (request.args.get('entity') or '').strip()
    location = (request.args.get('location') or '').strip()
    deadline = (request.args.get('deadline') or 'all').strip().lower()
    sort = (request.args.get('sort') or 'deadline_asc').strip().lower()
    page = request.args.get('page', 1, type=int)
    page_size = 9

    if search_term:
        like_term = f'%{search_term}%'
        query = query.filter(
            (Procurement.title.ilike(like_term)) |
            (Procurement.tender_number.ilike(like_term)) |
            (Procurement.procurement_entity.ilike(like_term)) |
            (Procurement.user_department.ilike(like_term)) |
            (Procurement.description.ilike(like_term))
        )

    category_values = {'all': None, 'goods': ['goods', 'supplies'], 'works': ['works', 'construction'], 'consultancy': ['consultancy', 'services'], 'non_consultancy': ['non_consultancy', 'non_consultancy_services']}
    if category and category in category_values and category_values[category]:
        query = query.filter(Procurement.category.in_(category_values[category]))

    if entity:
        like_entity = f'%{entity}%'
        query = query.filter(
            (Procurement.procurement_entity.ilike(like_entity)) |
            (Procurement.user_department.ilike(like_entity))
        )

    if location:
        like_location = f'%{location}%'
        query = query.filter(
            (Procurement.procurement_entity.ilike(like_location)) |
            (Procurement.user_department.ilike(like_location)) |
            (Procurement.description.ilike(like_location))
        )

    if deadline == 'closing_soon':
        query = query.filter(
            Procurement.submission_deadline.isnot(None),
            Procurement.submission_deadline >= datetime.utcnow(),
            Procurement.submission_deadline <= datetime.utcnow() + timedelta(days=14),
        )
    elif deadline == 'open':
        query = query.filter(Procurement.status == 'submission_open')
    elif deadline == 'awarded':
        query = query.filter(Procurement.status == 'award_published')

    if sort == 'deadline_asc':
        query = query.order_by(Procurement.submission_deadline.asc().nullslast())
    elif sort == 'deadline_desc':
        query = query.order_by(Procurement.submission_deadline.desc().nullslast())
    elif sort == 'newest':
        query = query.order_by(Procurement.created_at.desc())
    elif sort == 'value_desc':
        query = query.order_by(Procurement.estimated_value.desc())
    else:
        query = query.order_by(Procurement.submission_deadline.asc().nullslast())

    total_results = query.count()
    total_pages = max((total_results + page_size - 1) // page_size, 1) if total_results else 1
    if page < 1:
        page = 1
    if page > total_pages:
        page = total_pages
    tenders = query.offset((page - 1) * page_size).limit(page_size).all()
    categories = ['all', 'goods', 'works', 'consultancy', 'non_consultancy']
    return render_template(
        'public_tenders.html',
        tenders=tenders,
        categories=categories,
        selected_category=category,
        selected_status=deadline,
        search_term=search_term,
        entity_filter=entity,
        location_filter=location,
        sort=sort,
        page=page,
        total_pages=total_pages,
        total_results=total_results,
    )


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
