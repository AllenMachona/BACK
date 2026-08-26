import json
from datetime import datetime, timedelta
from flask import Blueprint, render_template, redirect, url_for, request, abort, flash
from flask_login import login_required, current_user
from sqlalchemy import case, func
from app.extensions import db
from app.models.procurement import Procurement
from app.models.bidder import Bidder
from app.models.submission import Submission
from app.models.complaint import Complaint
from app.models.payment import BidderPayment
from app.models.procurement_plan import ProcurementPlanItem
from app.utils.decorators import role_required

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


def _deadline_order(descending=False):
    """Order scheduled procurements before records without a deadline."""
    deadline = Procurement.submission_deadline
    direction = deadline.desc() if descending else deadline.asc()
    return case((deadline.is_(None), 1), else_=0).asc(), direction


@dashboard_bp.route('/')
def index():
    if current_user.is_authenticated:
        if current_user.has_role('system_admin'):
            return redirect(url_for('reports.index'))
        if current_user.has_role('bidder') or current_user.bidder_id:
            return redirect(url_for('bidders.portal'))
        return redirect(url_for('dashboard.dashboard'))

    public_query = Procurement.query.filter(Procurement.status.in_(PUBLIC_PROCUREMENT_STATUSES))
    public_tenders = public_query.order_by(*_deadline_order()).limit(6).all()
    opened_tenders = public_query.filter(Procurement.status == 'submission_open').order_by(*_deadline_order()).limit(4).all()
    awarded_tenders = Procurement.query.filter(Procurement.status == 'award_published').order_by(*_deadline_order()).limit(3).all()
    annual_plan_tenders = public_query.filter(Procurement.status == 'published').order_by(Procurement.created_at.desc()).limit(3).all()
    current_tenders = Procurement.query.filter(Procurement.status.in_(['published', 'submission_open'])).order_by(*_deadline_order()).limit(4).all()
    category_counts = _build_category_counts(public_query.all())
    closing_soon = public_query.filter(
        Procurement.submission_deadline.isnot(None),
        Procurement.submission_deadline >= datetime.utcnow(),
        Procurement.submission_deadline <= datetime.utcnow() + timedelta(days=14),
    ).count()

    total_award_value = db.session.query(
        func.coalesce(func.sum(Procurement.estimated_value), 0)
    ).filter(Procurement.status == 'award_published').scalar() or 0

    procurement_entities = [
        {'name': tender.procurement_entity or 'Public Entity', 'count': 1}
        for tender in public_query.distinct(Procurement.procurement_entity).all()
        if tender.procurement_entity
    ]

    stats = {
        'total_tenders': Procurement.query.count(),
        'procurement_entities': len(procurement_entities),
        'current_tenders': Procurement.query.filter(Procurement.status.in_(['published', 'submission_open'])).count(),
        'closing_soon': closing_soon,
        'awarded_tenders': Procurement.query.filter(Procurement.status == 'award_published').count(),
        'total_award_value': float(total_award_value),
    }

    tender_cards = []
    for tender in current_tenders:
        category = _category_key(tender.category)
        tender_cards.append({
            'id': tender.id,
            'title': tender.title,
            'entity': tender.procurement_entity or 'Procurement Entity',
            'logoUrl': '',
            'invitationDate': tender.created_at.strftime('%Y-%m-%d') if tender.created_at else 'TBA',
            'submissionDeadline': tender.submission_deadline.strftime('%Y-%m-%d %H:%M') if tender.submission_deadline else 'TBA',
            'number': tender.tender_number or 'N/A',
            'category': category,
            'tags': [
                {'label': 'Open', 'style': 'green'} if tender.status == 'submission_open' else {'label': 'Published', 'style': 'neutral'},
                {'label': category.replace('_', ' ').title(), 'style': 'orange'}
            ],
            'detailsUrl': url_for('dashboard.public_tender_detail', procurement_id=tender.id),
        })

    return render_template(
        'public_home.html',
        tenders=public_tenders,
        current_tenders=current_tenders,
        opened_tenders=opened_tenders,
        awarded_tenders=awarded_tenders,
        annual_plan_tenders=annual_plan_tenders,
        stats=stats,
        category_counts=category_counts,
        procurement_entities=procurement_entities,
        tender_cards_json=json.dumps(tender_cards),
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
        query = query.order_by(*_deadline_order())
    elif sort == 'deadline_desc':
        query = query.order_by(*_deadline_order(descending=True))
    elif sort == 'newest':
        query = query.order_by(Procurement.created_at.desc())
    elif sort == 'value_desc':
        query = query.order_by(Procurement.estimated_value.desc())
    else:
        query = query.order_by(*_deadline_order())

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


@dashboard_bp.route('/procurement-plans')
def public_procurement_plans():
    plans = ProcurementPlanItem.query.filter_by(status='published').order_by(
        ProcurementPlanItem.financial_year.desc(),
        ProcurementPlanItem.procurement_entity.asc(),
        ProcurementPlanItem.planned_quarter.asc(),
    ).all()
    years = sorted({plan.financial_year for plan in plans}, reverse=True)
    selected_year = (request.args.get('year') or '').strip()
    if selected_year:
        plans = [plan for plan in plans if plan.financial_year == selected_year]
    return render_template('public_procurement_plans.html', plans=plans, years=years, selected_year=selected_year)


@dashboard_bp.route('/procurement-plans/manage', methods=['GET', 'POST'])
@login_required
@role_required('procurement_unit')
def manage_procurement_plans():
    if request.method == 'POST':
        plan_id = request.form.get('plan_id', type=int)
        plan = ProcurementPlanItem.query.get(plan_id) if plan_id else None
        if plan_id and not plan:
            abort(404)
        if request.form.get('action') == 'publish':
            plan.status = 'published'
            db.session.commit()
            flash('Procurement plan published successfully.', 'success')
            return redirect(url_for('dashboard.manage_procurement_plans'))
        try:
            estimated_value = float(request.form.get('estimated_value', ''))
        except ValueError:
            flash('Enter a valid estimated value.', 'danger')
            return redirect(url_for('dashboard.manage_procurement_plans'))

        if not plan:
            plan = ProcurementPlanItem(created_by_id=current_user.id)
            db.session.add(plan)
        plan.procurement_entity = request.form.get('procurement_entity', '').strip()
        plan.financial_year = request.form.get('financial_year', '').strip()
        plan.title = request.form.get('title', '').strip()
        plan.description = request.form.get('description', '').strip()
        plan.category = request.form.get('category', '').strip()
        plan.method = request.form.get('method', '').strip()
        plan.estimated_value = estimated_value
        plan.planned_quarter = request.form.get('planned_quarter', '').strip()
        plan.status = 'published' if request.form.get('status') == 'published' else 'draft'
        if not all((plan.procurement_entity, plan.financial_year, plan.title,
                    plan.category, plan.method, plan.planned_quarter)):
            flash('Complete all required procurement plan fields.', 'danger')
            return redirect(url_for('dashboard.manage_procurement_plans'))
        db.session.add(plan)
        db.session.commit()
        flash('Procurement plan item saved successfully.', 'success')
        return redirect(url_for('dashboard.manage_procurement_plans'))

    plans = ProcurementPlanItem.query.order_by(
        ProcurementPlanItem.financial_year.desc(), ProcurementPlanItem.created_at.desc()
    ).all()
    return render_template('procurement_plan_manage.html', plans=plans)


@dashboard_bp.route('/procurement-plans/<int:plan_id>/edit', methods=['GET'])
@login_required
@role_required('procurement_unit')
def edit_procurement_plan(plan_id):
    plan = ProcurementPlanItem.query.get_or_404(plan_id)
    plans = ProcurementPlanItem.query.order_by(
        ProcurementPlanItem.financial_year.desc(), ProcurementPlanItem.created_at.desc()
    ).all()
    return render_template('procurement_plan_manage.html', plans=plans, edit_plan=plan)


@dashboard_bp.route('/tenders/<int:procurement_id>')
def public_tender_detail(procurement_id):
    procurement = Procurement.query.get_or_404(procurement_id)
    if procurement.status not in ('published', 'submission_open', 'clarification_period', 'award_published'):
        abort(404)
    if current_user.is_authenticated and (current_user.has_role('bidder') or current_user.bidder_id):
        return redirect(url_for('bidders.workspace', procurement_id=procurement.id))
    return render_template('public_tender_detail.html', procurement=procurement)


@dashboard_bp.route('/dashboard')
@login_required
def dashboard():
    if current_user.has_role('bidder') or current_user.bidder_id:
        return redirect(url_for('bidders.portal'))

    active_tenders = Procurement.query.filter(
        Procurement.status.in_(['published', 'submission_open'])
    ).count()

    pending_evaluations = Procurement.query.filter(
        Procurement.status.in_(['compliance_evaluation', 'technical_evaluation', 'financial_evaluation'])
    ).count()

    registered_bidders = Bidder.query.count()

    since = datetime.utcnow() - timedelta(hours=24)
    recent_submissions = Submission.query.filter(Submission.submitted_at >= since).count()
    metric_max = max(active_tenders, pending_evaluations, registered_bidders, recent_submissions, 1)
    dashboard_metrics = [
        {'label': 'Active Tenders', 'value': active_tenders, 'note': 'Published and open for submission',
         'icon': 'bi-file-earmark-text', 'tone': 'blue', 'url': url_for('reports.operational')},
        {'label': 'Pending Evaluations', 'value': pending_evaluations, 'note': 'Awaiting committee action',
         'icon': 'bi-hourglass-split', 'tone': 'gold', 'url': url_for('reports.operational')},
        {'label': 'Registered Bidders', 'value': registered_bidders, 'note': 'Active supplier registry',
         'icon': 'bi-people', 'tone': 'green', 'url': url_for('reports.bidder_registry')},
        {'label': 'Recent Submissions', 'value': recent_submissions, 'note': 'Received in the last 24 hours',
         'icon': 'bi-inbox', 'tone': 'blue', 'url': url_for('reports.bidder_participation')},
    ]

    recent_procurements = Procurement.query.order_by(Procurement.updated_at.desc()).limit(6).all()

    status_rows = db.session.query(
        Procurement.status, func.count(Procurement.id)
    ).group_by(Procurement.status).order_by(func.count(Procurement.id).desc()).all()
    category_rows = db.session.query(
        Procurement.category, func.count(Procurement.id)
    ).group_by(Procurement.category).order_by(func.count(Procurement.id).desc()).all()
    status_total = sum(count for _, count in status_rows) or 1
    category_total = sum(count for _, count in category_rows) or 1
    chart_colors = ['#1e88d6', '#2d6a35', '#d7952b', '#875c9e', '#c94b4b']
    status_segments = []
    segment_start = 0
    for index, (_, count) in enumerate(status_rows):
        segment_end = segment_start + (count / status_total * 100)
        status_segments.append(f'{chart_colors[index % len(chart_colors)]} {segment_start:.2f}% {segment_end:.2f}%')
        segment_start = segment_end
    status_gradient = ', '.join(status_segments) or '#e9eef1 0 100%'
    overdue_tenders = Procurement.query.filter(
        Procurement.status == 'submission_open',
        Procurement.submission_deadline.isnot(None),
        Procurement.submission_deadline < datetime.utcnow(),
    ).count()
    closing_soon = Procurement.query.filter(
        Procurement.status == 'submission_open',
        Procurement.submission_deadline.isnot(None),
        Procurement.submission_deadline >= datetime.utcnow(),
        Procurement.submission_deadline <= datetime.utcnow() + timedelta(days=7),
    ).count()
    pending_payments = BidderPayment.query.filter_by(status='pending').count()
    active_complaints = Complaint.query.filter(
        Complaint.status.in_(['received', 'under_review', 'escalated'])
    ).count()
    dashboard_alerts = [
        {'label': 'Overdue submission windows', 'count': overdue_tenders, 'tone': 'danger',
         'icon': 'bi-alarm', 'url': url_for('procurements.list_procurements', status='submission_open')},
        {'label': 'Tenders closing within 7 days', 'count': closing_soon, 'tone': 'warning',
         'icon': 'bi-hourglass-split', 'url': url_for('procurements.list_procurements', status='submission_open')},
        {'label': 'Payments awaiting verification', 'count': pending_payments, 'tone': 'info',
         'icon': 'bi-credit-card-2-front', 'url': url_for('procurements.payment_verifications')},
        {'label': 'Active complaints', 'count': active_complaints, 'tone': 'danger',
         'icon': 'bi-exclamation-octagon', 'url': url_for('reports.complaints')},
    ]

    return render_template(
        'dashboard.html',
        active_tenders=active_tenders,
        pending_evaluations=pending_evaluations,
        registered_bidders=registered_bidders,
        recent_submissions=recent_submissions,
        dashboard_metrics=dashboard_metrics,
        metric_max=metric_max,
        recent_procurements=recent_procurements,
        status_rows=status_rows,
        status_total=status_total,
        status_gradient=status_gradient,
        category_rows=category_rows,
        category_total=category_total,
        dashboard_alerts=dashboard_alerts,
    )
