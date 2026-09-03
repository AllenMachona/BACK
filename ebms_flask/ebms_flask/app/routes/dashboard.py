import json
import re
from datetime import datetime, timedelta
from flask import Blueprint, render_template, redirect, url_for, request, abort, flash
from flask_login import login_required, current_user
from sqlalchemy import case, func, or_
from app.extensions import db
from app.models.procurement import Procurement
from app.models.bidder import Bidder
from app.models.submission import Submission
from app.models.complaint import Complaint
from app.models.payment import BidderPayment
from app.models.award import Award
from app.models.budget_entry import BudgetEntry
from app.models.procurement_plan import ProcurementPlanItem, PROCUREMENT_PLAN_STATUSES
from app.models.evaluation import Evaluation
from app.models.evaluator_assignment import EvaluatorAssignment
from app.utils.decorators import role_required
from app.utils.evaluator_assignment import EvaluatorAssignmentService

dashboard_bp = Blueprint('dashboard', __name__)

PUBLIC_PROCUREMENT_STATUSES = ['published', 'submission_open', 'clarification_period', 'award_published']
FINANCIAL_YEAR_HINT = 'Financial year must use the format 2026/27, 2027/28, 2029/30, etc.'


def _generate_financial_year_options(start_year=None, years_ahead=8):
    current_year = start_year or datetime.utcnow().year
    options = []
    for year in range(current_year - 2, current_year + years_ahead):
        suffix = str((year + 1) % 100).zfill(2)
        options.append(f'{year}/{suffix}')
    return options


def _validate_financial_year(value):
    text = (value or '').strip()
    if not text:
        return None, 'Financial year is required.'
    if not re.fullmatch(r'\d{4}/\d{2}', text):
        return None, f'{FINANCIAL_YEAR_HINT} Example: 2026/27.'
    start_year, end_year = text.split('/')
    if int(end_year) != (int(start_year) % 100) + 1:
        return None, f'{FINANCIAL_YEAR_HINT} Example: 2026/27.'
    return text, None


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


@dashboard_bp.route('/about')
def about():
    return render_template('public_about.html')


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
    plans_query = ProcurementPlanItem.query.filter(ProcurementPlanItem.status.in_(PROCUREMENT_PLAN_STATUSES))
    selected_year = (request.args.get('year') or '').strip()
    selected_quarter = (request.args.get('quarter') or '').strip()
    selected_method = (request.args.get('method') or '').strip()
    selected_category = (request.args.get('category') or '').strip()
    selected_ppra_code = (request.args.get('ppra_code') or '').strip()
    query_text = (request.args.get('q') or '').strip()

    if selected_year:
        plans_query = plans_query.filter(ProcurementPlanItem.financial_year == selected_year)
    if selected_quarter:
        plans_query = plans_query.filter(ProcurementPlanItem.planned_quarter == selected_quarter)
    if selected_method:
        plans_query = plans_query.filter(ProcurementPlanItem.method == selected_method)
    if selected_category:
        plans_query = plans_query.filter(ProcurementPlanItem.category == selected_category)
    if selected_ppra_code:
        plans_query = plans_query.filter(
            or_(
                ProcurementPlanItem.ppra_code == selected_ppra_code,
                ProcurementPlanItem.ppra_code.like(f'{selected_ppra_code}-%')
            )
        )
    if query_text:
        like_term = f'%{query_text}%'
        plans_query = plans_query.filter(
            or_(
                ProcurementPlanItem.title.ilike(like_term),
                ProcurementPlanItem.procurement_entity.ilike(like_term),
                ProcurementPlanItem.description.ilike(like_term),
                ProcurementPlanItem.ppra_description.ilike(like_term)
            )
        )

    plans = plans_query.order_by(
        ProcurementPlanItem.financial_year.desc(),
        ProcurementPlanItem.procurement_entity.asc(),
        ProcurementPlanItem.planned_quarter.asc(),
    ).all()
    years = sorted({plan.financial_year for plan in plans_query.all()}, reverse=True)
    methods = sorted({plan.method for plan in plans_query.all() if plan.method})
    categories = sorted({plan.category for plan in plans_query.all() if plan.category})
    ppra_codes = ProcurementPlanItem.ppra_code_options()
    ppra_code_labels = ProcurementPlanItem.ppra_code_labels()

    return render_template(
        'public_procurement_plans.html',
        plans=plans,
        years=years,
        selected_year=selected_year,
        selected_quarter=selected_quarter,
        selected_method=selected_method,
        selected_category=selected_category,
        selected_ppra_code=selected_ppra_code,
        query_text=query_text,
        methods=methods,
        categories=categories,
        ppra_codes=ppra_codes,
        ppra_code_labels=ppra_code_labels,
    )


@dashboard_bp.route('/procurement-plans/manage', methods=['GET', 'POST'])
@login_required
@role_required('procurement_unit', 'finance_planning')
def manage_procurement_plans():
    ppra_codes = ProcurementPlanItem.ppra_code_options()
    ppra_sub_codes = ProcurementPlanItem.ppra_sub_code_options()
    ppra_code_labels = ProcurementPlanItem.ppra_code_labels()
    ppra_lookup = ProcurementPlanItem.ppra_classification_lookup()

    if request.method == 'POST':
        plan_id = request.form.get('plan_id', type=int)
        plan = ProcurementPlanItem.query.get(plan_id) if plan_id else None
        if plan_id and not plan:
            abort(404)
        try:
            estimated_value = float(request.form.get('estimated_value', ''))
        except ValueError:
            flash('Enter a valid estimated value.', 'danger')
            return redirect(url_for('dashboard.manage_procurement_plans'))

        financial_year, year_error = _validate_financial_year(request.form.get('financial_year'))
        if year_error:
            flash(year_error, 'danger')
            return redirect(url_for('dashboard.manage_procurement_plans'))

        status = (request.form.get('status') or 'upcoming').strip().lower()
        if status not in PROCUREMENT_PLAN_STATUSES:
            flash('Select a valid procurement plan status.', 'danger')
            return redirect(url_for('dashboard.manage_procurement_plans'))

        if not plan:
            plan = ProcurementPlanItem(created_by_id=current_user.id)
            db.session.add(plan)

        ppra_base = (request.form.get('ppra_code') or '').strip()
        ppra_sub_code = (request.form.get('ppra_sub_code') or '').strip()
        auto_ppra_description = ProcurementPlanItem.ppra_description_for(ppra_base, ppra_sub_code)
        ppra_description_input = (request.form.get('ppra_description') or '').strip()
        if not ppra_description_input:
            ppra_description_input = auto_ppra_description

        plan.procurement_entity = request.form.get('procurement_entity', '').strip()
        plan.financial_year = financial_year
        plan.title = request.form.get('title', '').strip()
        plan.description = (request.form.get('description') or ppra_description_input or auto_ppra_description).strip() if (request.form.get('description') or ppra_description_input or auto_ppra_description) else None
        plan.ppra_code = ppra_base
        plan.ppra_sub_code = ppra_sub_code if ppra_sub_code and ppra_sub_code not in ('00', 'none') else None
        plan.ppra_description = ppra_description_input or auto_ppra_description
        plan.category = request.form.get('category', '').strip()
        plan.method = request.form.get('method', '').strip()
        plan.estimated_value = estimated_value
        plan.planned_quarter = request.form.get('planned_quarter', '').strip()
        plan.status = status
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
    return render_template('procurement_plan_manage.html', plans=plans, financial_year_options=_generate_financial_year_options(),
                          ppra_codes=ppra_codes, ppra_sub_codes=ppra_sub_codes, ppra_code_labels=ppra_code_labels,
                          ppra_lookup=ppra_lookup, edit_plan=None)


@dashboard_bp.route('/procurement-plans/<int:plan_id>/edit', methods=['GET'])
@login_required
@role_required('procurement_unit', 'finance_planning')
def edit_procurement_plan(plan_id):
    plan = ProcurementPlanItem.query.get_or_404(plan_id)
    plans = ProcurementPlanItem.query.order_by(
        ProcurementPlanItem.financial_year.desc(), ProcurementPlanItem.created_at.desc()
    ).all()
    ppra_codes = ProcurementPlanItem.ppra_code_options()
    ppra_sub_codes = ProcurementPlanItem.ppra_sub_code_options()
    ppra_code_labels = ProcurementPlanItem.ppra_code_labels()
    ppra_lookup = ProcurementPlanItem.ppra_classification_lookup()
    return render_template('procurement_plan_manage.html', plans=plans, edit_plan=plan, financial_year_options=_generate_financial_year_options(),
                          ppra_codes=ppra_codes, ppra_sub_codes=ppra_sub_codes, ppra_code_labels=ppra_code_labels,
                          ppra_lookup=ppra_lookup)


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

    if current_user.has_role('finance_planning'):
        procurements = Procurement.query.order_by(Procurement.updated_at.desc()).all()
        awards = Award.query.all()
        entries = BudgetEntry.query.all()
        payments = BidderPayment.query.all()
        award_by_procurement = {award.procurement_id: award for award in awards}
        entries_by_procurement = {}
        for entry in entries:
            entries_by_procurement.setdefault(entry.procurement_id, []).append(entry)

        approved_budget = sum(float(procurement.estimated_value or 0) for procurement in procurements)
        awarded_value = sum(float(award.award_value or 0) for award in awards)
        posted_spend = sum(float(entry.signed_amount or 0) for entry in entries)
        pending_payments = [payment for payment in payments if payment.status == 'pending']
        rejected_payments = [payment for payment in payments if payment.status in ('rejected', 'resubmission_required')]
        remaining_budget = approved_budget - posted_spend
        utilization = (posted_spend / approved_budget * 100) if approved_budget else 0

        category_totals = {}
        exposure_rows = []
        for procurement in procurements:
            budget = float(procurement.estimated_value or 0)
            spend = sum(float(entry.signed_amount or 0) for entry in entries_by_procurement.get(procurement.id, []))
            category = (procurement.category or 'unclassified').replace('_', ' ').title()
            category_totals[category] = category_totals.get(category, 0) + budget
            exposure_rows.append({
                'procurement': procurement,
                'budget': budget,
                'spend': spend,
                'remaining': budget - spend,
                'utilization': (spend / budget * 100) if budget else 0,
                'award': award_by_procurement.get(procurement.id),
            })
        exposure_rows.sort(key=lambda row: row['remaining'])
        category_total = sum(category_totals.values()) or 1
        category_mix = [
            {'name': name, 'value': value, 'percent': round(value / category_total * 100, 1),
             'color': ['#2878bd', '#16805c', '#c4871d', '#875c9e'][index % 4]}
            for index, (name, value) in enumerate(sorted(category_totals.items(), key=lambda item: item[1], reverse=True))
        ]
        month_labels = []
        monthly_spend = []
        monthly_awards = []
        today = datetime.utcnow()
        for offset in range(5, -1, -1):
            month_number = today.month - offset
            year = today.year + (month_number - 1) // 12
            month = (month_number - 1) % 12 + 1
            month_labels.append(datetime(year, month, 1).strftime('%b'))
            monthly_spend.append(sum(float(entry.signed_amount or 0) for entry in entries if entry.entry_date and entry.entry_date.year == year and entry.entry_date.month == month))
            monthly_awards.append(sum(float(award.award_value or 0) for award in awards if award.decision_date and award.decision_date.year == year and award.decision_date.month == month))
        finance_warnings = [
            {'label': 'Payments awaiting verification', 'count': len(pending_payments), 'value': sum(float(payment.amount or 0) for payment in pending_payments), 'tone': 'warning', 'url': url_for('procurements.payment_verifications', status='pending')},
            {'label': 'Rejected or correction payments', 'count': len(rejected_payments), 'value': sum(float(payment.amount or 0) for payment in rejected_payments), 'tone': 'danger', 'url': url_for('procurements.payment_verifications', status='rejected')},
            {'label': 'Procurements over budget', 'count': sum(1 for row in exposure_rows if row['remaining'] < 0), 'value': sum(abs(row['remaining']) for row in exposure_rows if row['remaining'] < 0), 'tone': 'danger', 'url': url_for('reports.finance')},
            {'label': 'Awards without recorded value', 'count': sum(1 for award in awards if not award.award_value), 'value': 0, 'tone': 'warning', 'url': url_for('reports.awards')},
        ]
        return render_template('finance_dashboard.html', approved_budget=approved_budget, awarded_value=awarded_value,
            posted_spend=posted_spend, remaining_budget=remaining_budget, utilization=utilization,
            pending_payments=pending_payments, exposure_rows=exposure_rows[:8], category_mix=category_mix,
            month_labels=month_labels, monthly_spend=monthly_spend, monthly_awards=monthly_awards,
            finance_warnings=finance_warnings, max_finance_trend=max(monthly_spend + monthly_awards + [1]))

    if current_user.has_role('evaluator'):
        assignments = EvaluatorAssignmentService.for_user(current_user.id)
        evaluator_rows = []
        submitted_bid_total = 0
        evaluated_bid_total = 0
        needs_attention = 0
        for assignment in assignments:
            procurement = assignment.procurement
            allowed_envelopes = EvaluatorAssignment.SCOPE_ENVELOPES.get(assignment.document_scope, ())
            submitted_bids = {
                submission.bidder_id
                for submission in procurement.submissions.filter_by(status='submitted').all()
                if submission.envelope_type in allowed_envelopes
            }
            evaluations = Evaluation.query.filter_by(
                procurement_id=procurement.id,
                evaluator_id=current_user.id,
            ).all()
            evaluated_bids = {
                evaluation.bidder_id for evaluation in evaluations
                if evaluation.bidder_id in submitted_bids
            }
            submitted_bid_total += len(submitted_bids)
            evaluated_bid_total += len(evaluated_bids)
            remaining_bids = len(submitted_bids - evaluated_bids)
            if remaining_bids:
                needs_attention += 1
            evaluator_rows.append({
                'assignment': assignment,
                'procurement': procurement,
                'submitted_bids': len(submitted_bids),
                'evaluated_bids': len(evaluated_bids),
                'remaining_bids': remaining_bids,
            })

        evaluator_rows.sort(key=lambda row: (
            row['remaining_bids'] == 0,
            -(row['procurement'].updated_at.timestamp() if row['procurement'].updated_at else 0),
        ))
        evaluator_metrics = [
            {'label': 'Assigned tenders', 'value': len(assignments), 'note': 'Active evaluation assignments', 'icon': 'bi-clipboard2-check', 'tone': 'blue'},
            {'label': 'Bids in scope', 'value': submitted_bid_total, 'note': 'Submitted bidder records you can review', 'icon': 'bi-files', 'tone': 'gold'},
            {'label': 'Bidders evaluated', 'value': evaluated_bid_total, 'note': 'Bidders with your evaluation record', 'icon': 'bi-person-check', 'tone': 'green'},
            {'label': 'Needs attention', 'value': needs_attention, 'note': 'Assignments with remaining bidders', 'icon': 'bi-hourglass-split', 'tone': 'blue'},
        ]
        return render_template(
            'dashboard.html',
            evaluator_dashboard=True,
            evaluator_rows=evaluator_rows,
            evaluator_metrics=evaluator_metrics,
            evaluator_metric_max=max((metric['value'] for metric in evaluator_metrics), default=1) or 1,
        )

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
