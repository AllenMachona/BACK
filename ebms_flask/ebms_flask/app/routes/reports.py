from datetime import datetime, timedelta
from flask import Blueprint, render_template, send_file, request, flash, redirect, url_for
from flask_login import login_required, current_user
from sqlalchemy import func, distinct
from app.extensions import db
from app.models.procurement import Procurement
from app.models.submission import Submission
from app.models.bidder import Bidder
from app.models.complaint import Complaint
from app.models.audit import AuditLog
from app.models.award import Award
from app.models.evaluation import Evaluation
from app.models.payment import BidderPayment
from app.models.communication import Communication
from app.models.budget_entry import BudgetEntry
from app.models.message import Message
from app.models.bidder_compliance import BidderComplianceDocument
from app.models.bidder_performance import BidderPerformance
from app.models.history import ProcurementHistory
from app.models.request import FormDRequest, FormERequest, FormDERequest
from app.models.role import Role
from app.models.user import User
from app.utils.decorators import permission_required
from app.utils.reports import ReportsService, ExcelExportService

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

    def pie_gradient(rows, color_set):
        total = sum(row[1] for row in rows) or 1
        segments = []
        start = 0.0
        for index, row in enumerate(rows):
            end = start + (row[1] / total * 100)
            segments.append(f'{color_set[index % len(color_set)]} {start:.2f}% {end:.2f}%')
            start = end
        return ', '.join(segments) or '#e9eef1 0 100%'

    category_gradient = pie_gradient(by_category, ['#1e88d6', '#2d6a35', '#d7952b', '#875c9e', '#c94b4b'])
    method_gradient = pie_gradient(by_method, ['#1e88d6', '#2d6a35', '#d7952b', '#875c9e', '#c94b4b'])
    attention_items = [
        {'label': 'Overdue submission windows', 'count': overdue_closing, 'tone': 'danger',
         'icon': 'bi-alarm', 'url': url_for('procurements.list_procurements', status='submission_open')},
        {'label': 'Deadlines within 7 days', 'count': closing_soon, 'tone': 'warning',
         'icon': 'bi-hourglass-split', 'url': url_for('procurements.list_procurements', status='submission_open')},
        {'label': 'Active complaints requiring review', 'count': active_complaints, 'tone': 'danger',
         'icon': 'bi-exclamation-octagon', 'url': url_for('reports.complaints')},
        {'label': 'Cancelled procurements', 'count': cancelled_count, 'tone': 'muted',
         'icon': 'bi-archive', 'url': url_for('reports.operational')},
    ]

    today = datetime.utcnow().date()
    month_keys = []
    year, month = today.year, today.month
    for offset in range(11, -1, -1):
        month_number = month - offset
        month_year = year + (month_number - 1) // 12
        month_value = (month_number - 1) % 12 + 1
        month_keys.append((month_year, month_value))
    month_labels = [datetime(y, m, 1).strftime('%b %y') for y, m in month_keys]
    procurement_trend = {key: {'count': 0, 'value': 0.0} for key in month_keys}
    submission_trend = {key: 0 for key in month_keys}
    award_trend = {key: 0 for key in month_keys}
    for procurement in Procurement.query.all():
        if procurement.created_at:
            key = (procurement.created_at.year, procurement.created_at.month)
            if key in procurement_trend:
                procurement_trend[key]['count'] += 1
                procurement_trend[key]['value'] += float(procurement.estimated_value or 0)
    for submission in Submission.query.all():
        if submission.submitted_at:
            key = (submission.submitted_at.year, submission.submitted_at.month)
            if key in submission_trend:
                submission_trend[key] += 1
    for award in Award.query.all():
        if award.decision_date:
            key = (award.decision_date.year, award.decision_date.month)
            if key in award_trend:
                award_trend[key] += 1
    procurement_counts = [procurement_trend[key]['count'] for key in month_keys]
    procurement_values = [procurement_trend[key]['value'] for key in month_keys]
    submission_counts = [submission_trend[key] for key in month_keys]
    award_counts = [award_trend[key] for key in month_keys]
    trend_max = max(procurement_counts + submission_counts + award_counts + [1])
    value_max = max(procurement_values + [1])

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
        month_labels=month_labels,
        procurement_counts=procurement_counts,
        procurement_values=procurement_values,
        submission_counts=submission_counts,
        award_counts=award_counts,
        trend_max=trend_max,
        value_max=value_max,
        category_gradient=category_gradient,
        method_gradient=method_gradient,
        attention_items=attention_items,
    )


@reports_bp.route('/bidder-participation')
@login_required
@permission_required('can_view_all_records')
def bidder_participation():
    """Bidder participation report."""
    # Get filter parameters
    procurement_id = request.args.get('procurement_id', type=int)
    bidder_id = request.args.get('bidder_id', type=int)
    status = request.args.get('status', type=str)
    
    filters = {}
    if procurement_id:
        filters['procurement_id'] = procurement_id
    if bidder_id:
        filters['bidder_id'] = bidder_id
    if status:
        filters['status'] = status
    
    report_data = ReportsService.generate_bidder_participation_report(filters)
    
    # Get filter options for the form
    from app.models.bidder import Bidder
    procurements = Procurement.query.all()
    bidders = Bidder.query.filter_by(active=True).all()
    statuses = ['submitted', 'replaced', 'withdrawn', 'late_rejected']
    
    return render_template(
        'reports/bidder_participation.html',
        data=report_data,
        procurements=procurements,
        bidders=bidders,
        statuses=statuses,
        filters=filters
    )


@reports_bp.route('/bidder-participation/export')
@login_required
@permission_required('can_view_all_records')
def export_bidder_participation():
    """Export bidder participation report to Excel."""
    procurement_id = request.args.get('procurement_id', type=int)
    bidder_id = request.args.get('bidder_id', type=int)
    status = request.args.get('status', type=str)
    
    filters = {}
    if procurement_id:
        filters['procurement_id'] = procurement_id
    if bidder_id:
        filters['bidder_id'] = bidder_id
    if status:
        filters['status'] = status
    
    excel_file = ExcelExportService.export_bidder_participation_report(filters)
    
    if not excel_file:
        flash('Unable to generate report.', 'danger')
        return redirect(url_for('reports.bidder_participation'))
    
    return send_file(
        excel_file,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=f'bidder_participation_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.xlsx'
    )


@reports_bp.route('/procurement-summary')
@login_required
@permission_required('can_view_all_records')
def procurement_summary():
    """Procurement summary report."""
    status = request.args.get('status', type=str)
    category = request.args.get('category', type=str)
    
    filters = {}
    if status:
        filters['status'] = status
    if category:
        filters['category'] = category
    
    report_data = ReportsService.generate_procurement_summary_report(filters)
    
    # Get filter options
    statuses = [status for (status,) in db.session.query(Procurement.status).distinct().order_by(Procurement.status).all() if status]
    categories = [category for (category,) in db.session.query(Procurement.category).filter(
        Procurement.category.isnot(None)
    ).distinct().order_by(Procurement.category).all()]
    
    return render_template(
        'reports/procurement_summary.html',
        data=report_data,
        statuses=statuses,
        categories=categories,
        filters=filters
    )


@reports_bp.route('/procurement-summary/export')
@login_required
@permission_required('can_view_all_records')
def export_procurement_summary():
    """Export procurement summary report to Excel."""
    status = request.args.get('status', type=str)
    category = request.args.get('category', type=str)
    
    filters = {}
    if status:
        filters['status'] = status
    if category:
        filters['category'] = category
    
    excel_file = ExcelExportService.export_procurement_summary_report(filters)
    
    if not excel_file:
        flash('Unable to generate report.', 'danger')
        return redirect(url_for('reports.procurement_summary'))
    
    return send_file(
        excel_file,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=f'procurement_summary_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.xlsx'
    )


@reports_bp.route('/audit-trail')
@login_required
@permission_required('can_view_all_records')
def audit_trail():
    """Audit trail report."""
    user_id = request.args.get('user_id', type=int)
    action = request.args.get('action', type=str)
    entity_type = request.args.get('entity_type', type=str)
    page = request.args.get('page', 1, type=int)

    query = AuditLog.query
    if user_id:
        query = query.filter(AuditLog.user_id == user_id)
    if action:
        query = query.filter(AuditLog.action.like(f"%{action}%"))
    if entity_type:
        query = query.filter(AuditLog.entity_type == entity_type)

    filters = {}
    if user_id:
        filters['user_id'] = user_id
    if action:
        filters['action'] = action
    if entity_type:
        filters['entity_type'] = entity_type

    audit_logs = query.order_by(AuditLog.created_at.desc()).paginate(
        page=page, per_page=25, error_out=False)

    # Get filter options
    from app.models.user import User
    users = User.query.order_by(User.first_name, User.last_name).all()
    from sqlalchemy.sql import distinct
    actions = db.session.query(distinct(AuditLog.action)).all()
    entity_types = db.session.query(distinct(AuditLog.entity_type)).all()

    return render_template(
        'reports/audit_trail.html',
        audit_logs=audit_logs.items,
        page=audit_logs.page,
        pages=audit_logs.pages,
        users=users,
        actions=[a[0] for a in actions if a[0]],
        entity_types=[e[0] for e in entity_types if e[0]],
        filters=filters
    )


@reports_bp.route('/audit-trail/export')
@login_required
@permission_required('can_view_all_records')
def export_audit_trail():
    """Export audit trail report to Excel."""
    action = request.args.get('action', type=str)
    entity_type = request.args.get('entity_type', type=str)
    
    filters = {}
    if action:
        filters['action'] = action
    if entity_type:
        filters['entity_type'] = entity_type
    
    excel_file = ExcelExportService.export_audit_report(filters)
    
    if not excel_file:
        flash('Unable to generate report.', 'danger')
        return redirect(url_for('reports.audit_trail'))
    
    return send_file(
        excel_file,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=f'audit_trail_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.xlsx'
    )


@reports_bp.route('/complaints')
@login_required
@permission_required('can_view_all_records')
def complaints():
    """Complaints report."""
    status = request.args.get('status', type=str)
    procurement_id = request.args.get('procurement_id', type=int)
    
    filters = {}
    if status:
        filters['status'] = status
    if procurement_id:
        filters['procurement_id'] = procurement_id
    
    report_data = ReportsService.generate_complaints_report(filters)
    
    # Get filter options
    statuses = [s.status for s in Complaint.query.distinct(Complaint.status).all()]
    procurements = Procurement.query.all()
    
    return render_template(
        'reports/complaints.html',
        data=report_data,
        statuses=statuses,
        procurements=procurements,
        filters=filters
    )


@reports_bp.route('/complaints/export')
@login_required
@permission_required('can_view_all_records')
def export_complaints():
    """Export complaints report to Excel."""
    status = request.args.get('status', type=str)
    procurement_id = request.args.get('procurement_id', type=int)
    
    filters = {}
    if status:
        filters['status'] = status
    if procurement_id:
        filters['procurement_id'] = procurement_id
    
    excel_file = ExcelExportService.export_complaints_report(filters)
    
    if not excel_file:
        flash('Unable to generate report.', 'danger')
        return redirect(url_for('reports.complaints'))
    
    return send_file(
        excel_file,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=f'complaints_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.xlsx'
    )


# ======================================================================
# REPORTS CENTRE — catalogue that gathers every report in the system
# ======================================================================

BADGE_CLASSES = {
    'draft': 'badge-secondary',
    'published': 'badge-primary',
    'submission_open': 'badge-info',
    'submission_closed': 'badge-warning',
    'opening': 'badge-warning',
    'evaluation': 'badge-warning',
    'award_published': 'badge-success',
    'awarded': 'badge-success',
    'concluded': 'badge-success',
    'completed': 'badge-info',
    'cancelled': 'badge-danger',
    'approved': 'badge-success',
    'pending': 'badge-warning',
    'rejected': 'badge-danger',
    'resubmission_required': 'badge-info',
    'received': 'badge-warning',
    'under_review': 'badge-warning',
    'upheld': 'badge-danger',
    'dismissed': 'badge-secondary',
    'escalated': 'badge-danger',
    'submitted': 'badge-primary',
    'replaced': 'badge-info',
    'withdrawn': 'badge-secondary',
    'late_rejected': 'badge-danger',
    'active': 'badge-success',
    'inactive': 'badge-secondary',
    'suspended': 'badge-danger',
    'expired': 'badge-danger',
    'verified': 'badge-success',
    'unverified': 'badge-warning',
    'converted': 'badge-success',
    'satisfactory': 'badge-success',
    'needs_improvement': 'badge-warning',
    'public': 'badge-success',
    'targeted': 'badge-warning',
    'yes': 'badge-success',
    'no': 'badge-secondary',
    'available': 'badge-success',
    'insufficient': 'badge-danger',
    'commitment': 'badge-primary',
    'invoice': 'badge-warning',
    'payment': 'badge-success',
    'adjustment': 'badge-secondary',
    'direct': 'badge-primary',
    'broadcast': 'badge-info',
    'question': 'badge-info',
    'clarification': 'badge-primary',
    'addendum': 'badge-warning',
    'notice': 'badge-secondary',
    'advertisement': 'badge-success',
}

REPORT_CATALOG = [
    {
        'name': 'Procurement & Tenders',
        'icon': 'bi-briefcase',
        'reports': [
            {'key': 'operational', 'count_key': 'operational', 'title': 'Operational Snapshot',
             'desc': 'Live system KPIs, pipeline health and compliance indicators.', 'icon': 'bi-graph-up-arrow'},
            {'key': 'tender_register', 'count_key': 'procurements', 'title': 'Tender Register',
             'desc': 'Every tender in the system with deadlines and lifecycle metrics.', 'icon': 'bi-journal-text'},
            {'key': 'procurement_summary', 'count_key': 'procurements', 'title': 'Procurement Summary',
             'desc': 'Lifecycle progress of every procurement with values and deadlines.', 'icon': 'bi-table'},
            {'key': 'procurement_history', 'count_key': 'history', 'title': 'Procurement History',
             'desc': 'Who published, opened, closed or cancelled what and when.', 'icon': 'bi-clock-history'},
            {'key': 'requests', 'count_key': 'requests', 'title': 'Request Pipeline',
             'desc': 'Form D / Form E requisitions and their conversion status.', 'icon': 'bi-inbox'},
        ],
    },
    {
        'name': 'Bidders & Participation',
        'icon': 'bi-people',
        'reports': [
            {'key': 'bidder_participation', 'count_key': 'participations', 'title': 'Bidder Participation',
             'desc': 'Which bidders submitted to which tenders, with outcomes.', 'icon': 'bi-person-check'},
            {'key': 'bidder_registry', 'count_key': 'bidders', 'title': 'Bidder Registry',
             'desc': 'Registered bidder companies, grades and registration status.', 'icon': 'bi-buildings'},
            {'key': 'submission_activity', 'count_key': 'submissions', 'title': 'Submission Activity',
             'desc': 'Submitted, replaced and withdrawn sealed bids with receipts.', 'icon': 'bi-inboxes'},
            {'key': 'compliance', 'count_key': 'compliance', 'title': 'Compliance Documents',
             'desc': 'Bidder compliance document submissions and reviews.', 'icon': 'bi-file-earmark-check'},
        ],
    },
    {
        'name': 'Evaluation, Award & Performance',
        'icon': 'bi-clipboard-check',
        'reports': [
            {'key': 'evaluations', 'count_key': 'evaluations', 'title': 'Evaluation Results',
             'desc': 'Scoring, consensus scores and pass/fail outcomes.', 'icon': 'bi-clipboard-data'},
            {'key': 'awards', 'count_key': 'awards', 'title': 'Awards & Contracts',
             'desc': 'Award decisions, cooling-off periods and contract conclusion.', 'icon': 'bi-trophy'},
            {'key': 'bidder_performance', 'count_key': 'performance', 'title': 'Bidder Performance',
             'desc': 'Post-award performance reviews of winning bidders.', 'icon': 'bi-graph-up-arrow'},
        ],
    },
    {
        'name': 'Finance & Payments',
        'icon': 'bi-wallet2',
        'reports': [
            {'key': 'payments', 'count_key': 'payments', 'title': 'Payment Verification',
             'desc': 'Tender-document payments and their verification status.', 'icon': 'bi-credit-card'},
            {'key': 'budget', 'count_key': 'budget_entries', 'title': 'Budget & Expenditure',
             'desc': 'Commitments, invoices and payments against procurements.', 'icon': 'bi-cash-stack'},
        ],
    },
    {
        'name': 'Communication & Oversight',
        'icon': 'bi-shield-check',
        'reports': [
            {'key': 'communications', 'count_key': 'communications', 'title': 'Communications & Clarifications',
             'desc': 'Notices, addenda and clarifications issued to bidders.', 'icon': 'bi-chat-left-text'},
            {'key': 'messages', 'count_key': 'messages', 'title': 'Messaging Activity',
             'desc': 'Internal message volume, delivery and read status.', 'icon': 'bi-envelope-open'},
            {'key': 'complaints', 'count_key': 'complaints', 'title': 'Complaints & Reviews',
             'desc': 'Complaints, reviews and appeals with resolutions.', 'icon': 'bi-exclamation-triangle'},
            {'key': 'audit_trail', 'count_key': 'audit_logs', 'title': 'Audit Trail',
             'desc': 'Complete record of every system action and change.', 'icon': 'bi-ui-checks-grid'},
            {'key': 'users', 'count_key': 'users', 'title': 'Users & Accounts',
             'desc': 'All system accounts, roles, activity and access status.', 'icon': 'bi-person-badge'},
        ],
    },
]

def _badge_for(value):
    """Return the CSS badge class for a status value (or a default badge)."""
    key = str(value or '').strip().lower()
    return BADGE_CLASSES.get(key, 'badge-secondary')


@reports_bp.route('/')
@login_required
@permission_required('can_view_all_records')
def index():
    """Reports Centre — every report in the system gathered on one page."""
    soon_cutoff = datetime.utcnow() + timedelta(days=7)
    open_statuses = ['preparation', 'published', 'submission_open', 'clarification_period']

    request_count = (
        FormDRequest.query.count() + FormERequest.query.count() + FormDERequest.query.count()
    )

    counts = {
        'operational': Procurement.query.filter(Procurement.status.in_(open_statuses)).count(),
        'procurements': Procurement.query.count(),
        'history': ProcurementHistory.query.count(),
        'requests': request_count,
        'participations': Submission.query.filter_by(status='submitted').count(),
        'bidders': Bidder.query.count(),
        'submissions': Submission.query.count(),
        'compliance': BidderComplianceDocument.query.count(),
        'evaluations': Evaluation.query.count(),
        'awards': Award.query.count(),
        'performance': BidderPerformance.query.count(),
        'payments': BidderPayment.query.count(),
        'budget_entries': BudgetEntry.query.count(),
        'communications': Communication.query.count(),
        'messages': Message.query.count(),
        'complaints': Complaint.query.count(),
        'audit_logs': AuditLog.query.count(),
        'users': User.query.count(),
        'pending_payments': BidderPayment.query.filter_by(status='pending').count(),
        'closing_soon': Procurement.query.filter(
            Procurement.status == 'submission_open',
            Procurement.submission_deadline.isnot(None),
            Procurement.submission_deadline <= soon_cutoff,
            Procurement.submission_deadline >= datetime.utcnow(),
        ).count(),
        'pending_evaluations': Evaluation.query.filter_by(consensus_reached=False).count(),
    }

    return render_template(
        'reports/index.html',
        catalog=REPORT_CATALOG,
        counts=counts,
        badge_for=_badge_for,
        active_nav='reports',
    )

# ======================================================================
# GENERIC TABLE REPORTS — one shared template renders every new report
# ======================================================================

def _arg(name):
    return (request.args.get(name) or '').strip() or None


def _arg_int(name):
    return request.args.get(name, type=int) or None


def _arg_date(name):
    value = (request.args.get(name) or '').strip()
    if value:
        try:
            return datetime.strptime(value, '%Y-%m-%d')
        except (ValueError, TypeError):
            return None
    return None


def _add_date_filters(filters):
    start, end = _arg_date('start_date'), _arg_date('end_date')
    if start:
        filters['start_date'] = start
    if end:
        filters['end_date'] = end
    return filters


_PROC_STATUSES = [('draft', 'Draft'), ('preparation', 'Preparation'), ('internal_review', 'Internal Review'),
                  ('approved_for_publication', 'Approved for Publication'), ('published', 'Published'),
                  ('submission_open', 'Submission Open'), ('clarification_period', 'Clarification Period'),
                  ('submission_closed', 'Submission Closed'), ('opening', 'Opening'), ('evaluation', 'Evaluation'),
                  ('award_published', 'Award Published'), ('concluded', 'Concluded'), ('cancelled', 'Cancelled')]

_CATEGORIES = [('works', 'Works'), ('services', 'Services'), ('consultancy', 'Consultancy'),
               ('supplies', 'Supplies'), ('combination', 'Combination')]

_METHODS = [('open_domestic', 'Open Domestic'), ('open_international', 'Open International'),
            ('restricted', 'Restricted'), ('rfq', 'Request for Quotation'),
            ('direct', 'Direct'), ('rfp', 'Request for Proposal')]


def _proc_options():
    return [(p.id, f'{p.tender_number} — {p.title}') for p in Procurement.query.order_by(Procurement.tender_number).all()]


def _bidder_options():
    return [(b.id, b.company_name) for b in Bidder.query.order_by(Bidder.company_name).all()]


def _make_filter_select(name, label, options, all_label):
    return {'name': name, 'label': label, 'type': 'select', 'options': options, 'placeholder': all_label}


def _make_date_filter(name, label):
    return {'name': name, 'label': label, 'type': 'date'}


def _register_table_report(key, title, subtitle, icon, columns, filter_builder, parse_filters,
                           generator, exporter, stats):
    """Register a standard table report view plus its Excel export route."""
    def view():
        filters = parse_filters()
        rows = generator(filters)
        stats_cards = [{'label': label, 'value': fn(rows)} for label, fn in stats]
        defs = filter_builder()
        current = {f['name']: (request.args.get(f['name']) or '') for f in defs}
        return render_template(
            'reports/table_report.html',
            active_nav='reports',
            report={'key': key, 'title': title, 'subtitle': subtitle, 'icon': icon},
            filter_defs=defs,
            current=current,
            columns=columns,
            rows=rows,
            stats=stats_cards,
            badge_for=_badge_for,
        )

    def export_view():
        filters = parse_filters()
        excel_file = exporter(filters)
        if not excel_file:
            flash('Unable to generate report. There may be no data to export.', 'danger')
            return redirect(url_for('reports.' + key))
        return send_file(
            excel_file,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name=f'{key}_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.xlsx'
        )

    view = login_required(permission_required('can_view_all_records')(view))
    export_view = login_required(permission_required('can_view_all_records')(export_view))
    reports_bp.add_url_rule(f'/{key}', endpoint=key, view_func=view)
    reports_bp.add_url_rule(f'/{key}/export', endpoint=f'export_{key}', view_func=export_view)


def _history_action_options():
    actions = db.session.query(distinct(ProcurementHistory.action)).all()
    values = {a[0] for a in actions if a[0]}
    values.add('status_changed')
    return [(action, action.replace('_', ' ').title()) for action in sorted(values)]

# --- Tender Register -------------------------------------------------
_register_table_report(
    key='tender_register',
    title='Tender Register',
    subtitle='Complete register of every tender with lifecycle details',
    icon='bi-journal-text',
    columns=[
        ('Tender Number', 'Tender Number', False),
        ('Title', 'Procurement', False),
        ('Category', 'Category', False),
        ('Method', 'Method', False),
        ('Procurement Entity', 'Entity', False),
        ('Status', 'Status', True),
        ('Estimated Value', 'Est. Value (BWP)', False),
        ('Submission Deadline', 'Deadline', False),
        ('Submissions', 'Bids', False),
        ('Bidders Evaluated', 'Evaluated', False),
    ],
    filter_builder=lambda: [
        _make_filter_select('status', 'Status', _PROC_STATUSES, 'All Statuses'),
        _make_filter_select('category', 'Category', _CATEGORIES, 'All Categories'),
        _make_filter_select('method', 'Method', _METHODS, 'All Methods'),
        _make_date_filter('start_date', 'Created From'),
        _make_date_filter('end_date', 'Created To'),
    ],
    parse_filters=lambda: _add_date_filters({
        'status': _arg('status'),
        'category': _arg('category'),
        'method': _arg('method'),
    }),
    generator=ReportsService.generate_tender_register_report,
    exporter=ReportsService.export_tender_register_report,
    stats=[
        ('Total Tenders', lambda rows: len(rows)),
        ('Open', lambda rows: sum(1 for r in rows if r.get('Status') in ('published', 'submission_open', 'clarification_period'))),
        ('With Bids', lambda rows: sum(1 for r in rows if r.get('Submissions'))),
        ('Total Value (BWP)', lambda rows: '{:,.2f}'.format(sum(float(str(r.get('Estimated Value') or '0').replace(',', '')) for r in rows))),
    ],
)

# --- Procurement History -----------------------------------------------------
_register_table_report(
    key='procurement_history',
    title='Procurement History',
    subtitle='Every state change across the procurement lifecycle',
    icon='bi-clock-history',
    columns=[
        ('Tender Number', 'Tender Number', False),
        ('Action', 'Action', True),
        ('Previous Status', 'Previous Status', False),
        ('New Status', 'New Status', False),
        ('Performed By', 'Performed By', False),
        ('Performed At', 'Performed At', False),
        ('Requires Approval', 'Approval', True),
        ('Approved By', 'Approved By', False),
        ('Reason', 'Reason', False),
    ],
    filter_builder=lambda: [
        _make_filter_select('procurement_id', 'Procurement', _proc_options(), 'All Procurements'),
        _make_filter_select('action', 'Action', _history_action_options(), 'All Actions'),
        _make_date_filter('start_date', 'From'),
        _make_date_filter('end_date', 'To'),
    ],
    parse_filters=lambda: _add_date_filters({
        'procurement_id': _arg_int('procurement_id'),
        'action': _arg('action'),
    }),
    generator=ReportsService.generate_procurement_history_report,
    exporter=ReportsService.export_procurement_history_report,
    stats=[
        ('Total Events', lambda rows: len(rows)),
        ('Cancellations', lambda rows: sum(1 for r in rows if r.get('Action') == 'cancelled')),
        ('Reopenings', lambda rows: sum(1 for r in rows if r.get('Action') in ('restored', 'reopened', 'extended'))),
        ('Approvals Required', lambda rows: sum(1 for r in rows if r.get('Requires Approval') == 'Yes')),
    ],
)

# --- Request Pipeline --------------------------------------------------------
_register_table_report(
    key='requests',
    title='Request Pipeline',
    subtitle='Form D / Form E procurement requests and their conversion status',
    icon='bi-inbox',
    columns=[
        ('Request No', 'Request No', False),
        ('Form Type', 'Form Type', False),
        ('Title', 'Title', False),
        ('Requester', 'Requester', False),
        ('Department', 'Department', False),
        ('Budget', 'Budget (BWP)', False),
        ('Status', 'Status', True),
        ('Linked Procurement', 'Linked Tender', False),
        ('Submitted At', 'Submitted At', False),
        ('Converted / Rejected On', 'Decision Date', False),
    ],
    filter_builder=lambda: [
        _make_filter_select('form_type', 'Form Type',
                            [('Form D', 'Form D'), ('Form E', 'Form E'), ('Form D & E', 'Form D & E')], 'All Forms'),
        _make_filter_select('status', 'Status',
                            [('submitted', 'Submitted'), ('under_review', 'Under Review'),
                             ('converted', 'Converted'), ('rejected', 'Rejected')], 'All Statuses'),
        _make_date_filter('start_date', 'Submitted From'),
        _make_date_filter('end_date', 'Submitted To'),
    ],
    parse_filters=lambda: _add_date_filters({
        'form_type': _arg('form_type'),
        'status': _arg('status'),
    }),
    generator=ReportsService.generate_request_pipeline_report,
    exporter=ReportsService.export_request_pipeline_report,
    stats=[
        ('Total Requests', lambda rows: len(rows)),
        ('Converted', lambda rows: sum(1 for r in rows if r.get('Status') == 'converted')),
        ('Under Review', lambda rows: sum(1 for r in rows if r.get('Status') == 'under_review')),
        ('Rejected', lambda rows: sum(1 for r in rows if r.get('Status') == 'rejected')),
    ],
)

# --- Bidder Registry ---------------------------------------------------------
_register_table_report(
    key='bidder_registry',
    title='Bidder Registry',
    subtitle='Registered bidder companies, grades and registration status',
    icon='bi-buildings',
    columns=[
        ('Company Name', 'Company Name', False),
        ('Registration Number', 'Reg. No.', False),
        ('Grade', 'Grade', False),
        ('Category', 'Category', False),
        ('Registration Status', 'Status', True),
        ('Verified', 'Verified', True),
        ('Registered At', 'Registered At', False),
        ('Registration Expiry', 'Expiry', False),
        ('Email', 'Email', False),
        ('Phone', 'Phone', False),
    ],
    filter_builder=lambda: [
        _make_filter_select('status', 'Registration Status',
                            [('active', 'Active'), ('inactive', 'Inactive'),
                             ('suspended', 'Suspended'), ('expired', 'Expired')], 'All'),
        _make_filter_select('verified', 'Verified',
                            [('yes', 'Verified'), ('no', 'Not Verified')], 'Any'),
    ],
    parse_filters=lambda: {
        'status': _arg('status'),
        'verified': _arg('verified'),
    },
    generator=ReportsService.generate_bidder_registry_report,
    exporter=ReportsService.export_bidder_registry_report,
    stats=[
        ('Total Bidders', lambda rows: len(rows)),
        ('Active', lambda rows: sum(1 for r in rows if r.get('Registration Status') == 'active')),
        ('Suspended', lambda rows: sum(1 for r in rows if r.get('Registration Status') == 'suspended')),
        ('Verified', lambda rows: sum(1 for r in rows if r.get('Verified') == 'Yes')),
    ],
)

# --- Submission Activity ------------------------------------------------------
_register_table_report(
    key='submission_activity',
    title='Submission Activity',
    subtitle='Submitted, replaced and withdrawn sealed bids with receipts',
    icon='bi-inboxes',
    columns=[
        ('Tender Number', 'Tender Number', False),
        ('Bidder', 'Bidder', False),
        ('Envelope', 'Envelope', False),
        ('Version', 'Version', False),
        ('Status', 'Status', True),
        ('Submitted At', 'Submitted At', False),
        ('Receipt Code', 'Receipt Code', False),
        ('Original File', 'Original File', False),
        ('File Size (KB)', 'File Size (KB)', False),
    ],
    filter_builder=lambda: [
        _make_filter_select('procurement_id', 'Procurement', _proc_options(), 'All Procurements'),
        _make_filter_select('bidder_id', 'Bidder', _bidder_options(), 'All Bidders'),
        _make_filter_select('status', 'Submission Status',
                            [('submitted', 'Submitted'), ('replaced', 'Replaced'),
                             ('withdrawn', 'Withdrawn'), ('late_rejected', 'Late Rejected')], 'All Statuses'),
        _make_date_filter('start_date', 'From'),
        _make_date_filter('end_date', 'To'),
    ],
    parse_filters=lambda: _add_date_filters({
        'procurement_id': _arg_int('procurement_id'),
        'bidder_id': _arg_int('bidder_id'),
        'status': _arg('status'),
    }),
    generator=ReportsService.generate_submission_activity_report,
    exporter=ReportsService.export_submission_activity_report,
    stats=[
        ('Total Records', lambda rows: len(rows)),
        ('Submitted', lambda rows: sum(1 for r in rows if r.get('Status') == 'submitted')),
        ('Withdrawn', lambda rows: sum(1 for r in rows if r.get('Status') == 'withdrawn')),
        ('Late Rejected', lambda rows: sum(1 for r in rows if r.get('Status') == 'late_rejected')),
    ],
)

# --- Compliance Documents -----------------------------------------------------
_register_table_report(
    key='compliance',
    title='Compliance Documents',
    subtitle='Bidder compliance document submissions and reviews',
    icon='bi-file-earmark-check',
    columns=[
        ('Company Name', 'Company Name', False),
        ('File Name', 'File Name', False),
        ('Status', 'Status', True),
        ('Submitted At', 'Submitted At', False),
        ('Reviewed By', 'Reviewed By', False),
        ('Reviewed At', 'Reviewed At', False),
        ('Review Notes', 'Review Notes', False),
    ],
    filter_builder=lambda: [
        _make_filter_select('status', 'Review Status',
                            [('pending', 'Pending'), ('approved', 'Approved'),
                             ('rejected', 'Rejected')], 'All Statuses'),
    ],
    parse_filters=lambda: {
        'status': _arg('status'),
    },
    generator=ReportsService.generate_compliance_report,
    exporter=ReportsService.export_compliance_report,
    stats=[
        ('Total Documents', lambda rows: len(rows)),
        ('Approved', lambda rows: sum(1 for r in rows if r.get('Status') == 'approved')),
        ('Pending', lambda rows: sum(1 for r in rows if r.get('Status') == 'pending')),
        ('Rejected', lambda rows: sum(1 for r in rows if r.get('Status') == 'rejected')),
    ],
)

# --- Evaluations ---------------------------------------------------------------
_register_table_report(
    key='evaluations',
    title='Evaluation Results',
    subtitle='Scoring, consensus scores and pass/fail outcomes',
    icon='bi-clipboard-data',
    columns=[
        ('Tender Number', 'Tender Number', False),
        ('Procurement', 'Procurement', False),
        ('Bidder', 'Bidder', False),
        ('Evaluator', 'Evaluator', False),
        ('Stage', 'Stage', True),
        ('Score', 'Score', False),
        ('Consensus Score', 'Consensus', False),
        ('Passed', 'Passed', True),
        ('Eliminated', 'Eliminated', True),
        ('Date Reviewed', 'Date Reviewed', False),
    ],
    filter_builder=lambda: [
        _make_filter_select('procurement_id', 'Procurement', _proc_options(), 'All Procurements'),
        _make_filter_select('stage', 'Evaluation Stage',
                            [('compliance', 'Compliance'), ('technical', 'Technical'),
                             ('financial', 'Financial')], 'All Stages'),
        _make_filter_select('passed', 'Result',
                            [('yes', 'Passed'), ('no', 'Failed / Eliminated')], 'Any'),
        _make_date_filter('start_date', 'From'),
        _make_date_filter('end_date', 'To'),
    ],
    parse_filters=lambda: _add_date_filters({
        'procurement_id': _arg_int('procurement_id'),
        'stage': _arg('stage'),
        'passed': 'True' if _arg('passed') == 'yes' else ('False' if _arg('passed') == 'no' else None),
    }),
    generator=ReportsService.generate_evaluation_report,
    exporter=ReportsService.export_evaluation_report,
    stats=[
        ('Total Evaluations', lambda rows: len(rows)),
        ('Passed', lambda rows: sum(1 for r in rows if r.get('Passed') == 'Yes')),
        ('Eliminated', lambda rows: sum(1 for r in rows if r.get('Eliminated') == 'Yes')),
        ('With Consensus', lambda rows: sum(1 for r in rows if str(r.get('Consensus Score', '-')) != '-')),
    ],
)

# --- Awards & Contracts --------------------------------------------------------
_register_table_report(
    key='awards',
    title='Awards & Contracts',
    subtitle='Award decisions, cooling-off periods and contract conclusion',
    icon='bi-trophy',
    columns=[
        ('Tender Number', 'Tender Number', False),
        ('Title', 'Procurement', False),
        ('Winning Bidder', 'Winning Bidder', False),
        ('Award Value', 'Award Value (BWP)', False),
        ('Decision Date', 'Decision Date', False),
        ('Cooling-off Expiry', 'Cooling-off Expiry', False),
        ('Cooling-off Active', 'Cooling-off', True),
        ('Contract Concluded', 'Concluded', True),
        ('Concluded At', 'Concluded At', False),
    ],
    filter_builder=lambda: [
        _make_filter_select('procurement_id', 'Procurement', _proc_options(), 'All Procurements'),
        _make_filter_select('contract_status', 'Contract Status',
                            [('cooling_off', 'Cooling-off Period'), ('concluded', 'Concluded')], 'All'),
        _make_date_filter('start_date', 'Decision From'),
        _make_date_filter('end_date', 'Decision To'),
    ],
    parse_filters=lambda: _add_date_filters({
        'procurement_id': _arg_int('procurement_id'),
        'contract_status': _arg('contract_status'),
    }),
    generator=ReportsService.generate_award_report,
    exporter=ReportsService.export_award_report,
    stats=[
        ('Total Awards', lambda rows: len(rows)),
        ('Cooling-off Active', lambda rows: sum(1 for r in rows if r.get('Cooling-off Active') == 'Yes')),
        ('Contracts Concluded', lambda rows: sum(1 for r in rows if r.get('Contract Concluded') == 'Yes')),
    ],
)

# --- Bidder Performance -------------------------------------------------------
_register_table_report(
    key='bidder_performance',
    title='Bidder Performance',
    subtitle='Post-award performance reviews of winning bidders',
    icon='bi-graph-up-arrow',
    columns=[
        ('Tender Number', 'Tender Number', False),
        ('Bidder', 'Bidder', False),
        ('Delivery Score', 'Delivery', False),
        ('Quality Score', 'Quality', False),
        ('Compliance Score', 'Compliance', False),
        ('Overall Score', 'Overall', False),
        ('Status', 'Status', True),
        ('Reviewed By', 'Reviewed By', False),
        ('Reviewed At', 'Reviewed At', False),
        ('Notes', 'Notes', False),
    ],
    filter_builder=lambda: [
        _make_filter_select('procurement_id', 'Procurement', _proc_options(), 'All Procurements'),
        _make_filter_select('status', 'Review Status',
                            [('under_review', 'Under Review'), ('satisfactory', 'Satisfactory'),
                             ('needs_improvement', 'Needs Improvement'), ('completed', 'Completed')], 'All'),
    ],
    parse_filters=lambda: {
        'procurement_id': _arg_int('procurement_id'),
        'status': _arg('status'),
    },
    generator=ReportsService.generate_bidder_performance_report,
    exporter=ReportsService.export_bidder_performance_report,
    stats=[
        ('Total Reviews', lambda rows: len(rows)),
        ('Satisfactory', lambda rows: sum(1 for r in rows if r.get('Status') == 'satisfactory')),
        ('Needs Improvement', lambda rows: sum(1 for r in rows if r.get('Status') == 'needs_improvement')),
        ('Avg Overall', lambda rows: round(sum(float(r.get('Overall Score') or 0) for r in rows) / len(rows), 2) if rows else 0),
    ],
)

# --- Payment Verification -----------------------------------------------------
_register_table_report(
    key='payments',
    title='Payment Verification',
    subtitle='Tender-document payments and their verification status',
    icon='bi-credit-card',
    columns=[
        ('Tender Number', 'Tender Number', False),
        ('Bidder', 'Bidder', False),
        ('Payment Reference', 'Reference', False),
        ('Amount', 'Amount (BWP)', False),
        ('Status', 'Status', True),
        ('Submitted At', 'Submitted At', False),
        ('Reviewed By', 'Reviewed By', False),
        ('Reviewed At', 'Reviewed At', False),
        ('Notes', 'Notes', False),
    ],
    filter_builder=lambda: [
        _make_filter_select('procurement_id', 'Procurement', _proc_options(), 'All Procurements'),
        _make_filter_select('status', 'Payment Status',
                            [('pending', 'Pending'), ('approved', 'Approved'),
                             ('rejected', 'Rejected'), ('resubmission_required', 'Resubmission Required')], 'All'),
        _make_date_filter('start_date', 'Submitted From'),
        _make_date_filter('end_date', 'Submitted To'),
    ],
    parse_filters=lambda: _add_date_filters({
        'procurement_id': _arg_int('procurement_id'),
        'status': _arg('status'),
    }),
    generator=ReportsService.generate_payment_report,
    exporter=ReportsService.export_payment_report,
    stats=[
        ('Total Payments', lambda rows: len(rows)),
        ('Pending', lambda rows: sum(1 for r in rows if r.get('Status') == 'pending')),
        ('Approved', lambda rows: sum(1 for r in rows if r.get('Status') == 'approved')),
        ('Total Amount (BWP)', lambda rows: '{:,.2f}'.format(sum(float(str(r.get('Amount') or '0').replace(',', '')) for r in rows))),
    ],
)

# --- Budget & Expenditure -----------------------------------------------------
_register_table_report(
    key='budget',
    title='Budget & Expenditure',
    subtitle='Commitments, invoices and payments against procurements',
    icon='bi-cash-stack',
    columns=[
        ('Tender Number', 'Tender Number', False),
        ('Procurement', 'Procurement', False),
        ('Entry Type', 'Entry Type', True),
        ('Description', 'Description', False),
        ('Amount', 'Amount (BWP)', False),
        ('Reference', 'Reference', False),
        ('Entry Date', 'Entry Date', False),
        ('Created By', 'Created By', False),
    ],
    filter_builder=lambda: [
        _make_filter_select('procurement_id', 'Procurement', _proc_options(), 'All Procurements'),
        _make_filter_select('entry_type', 'Entry Type',
                            [('commitment', 'Commitment'), ('invoice', 'Invoice'),
                             ('payment', 'Payment'), ('adjustment', 'Adjustment')], 'All Types'),
        _make_date_filter('start_date', 'From'),
        _make_date_filter('end_date', 'To'),
    ],
    parse_filters=lambda: _add_date_filters({
        'procurement_id': _arg_int('procurement_id'),
        'entry_type': _arg('entry_type'),
    }),
    generator=ReportsService.generate_budget_report,
    exporter=ReportsService.export_budget_report,
    stats=[
        ('Total Entries', lambda rows: len(rows)),
        ('Commitments', lambda rows: sum(1 for r in rows if r.get('Entry Type') == 'commitment')),
        ('Payments', lambda rows: sum(1 for r in rows if r.get('Entry Type') == 'payment')),
        ('Total Amount (BWP)', lambda rows: '{:,.2f}'.format(sum(float(str(r.get('Amount') or '0').replace(',', '')) for r in rows))),
    ],
)

# --- Communications & Clarifications ------------------------------------------
_register_table_report(
    key='communications',
    title='Communications & Clarifications',
    subtitle='Notices, addenda and clarifications issued to bidders',
    icon='bi-chat-left-text',
    columns=[
        ('Tender Number', 'Tender Number', False),
        ('Type', 'Type', True),
        ('From', 'From', False),
        ('Visibility', 'Visibility', True),
        ('Public', 'Public', True),
        ('Attachment', 'Attachment', True),
        ('Content Summary', 'Content', False),
        ('Posted At', 'Posted At', False),
    ],
    filter_builder=lambda: [
        _make_filter_select('procurement_id', 'Procurement', _proc_options(), 'All Procurements'),
        _make_filter_select('type', 'Type',
                            [('question', 'Question'), ('clarification', 'Clarification'),
                             ('addendum', 'Addendum'), ('notice', 'Notice'), ('advertisement', 'Advertisement')], 'All Types'),
        _make_filter_select('visibility', 'Visibility',
                            [('public', 'Public'), ('targeted', 'Targeted')], 'Any'),
        _make_date_filter('start_date', 'From'),
        _make_date_filter('end_date', 'To'),
    ],
    parse_filters=lambda: _add_date_filters({
        'procurement_id': _arg_int('procurement_id'),
        'type': _arg('type'),
        'visibility': _arg('visibility'),
    }),
    generator=ReportsService.generate_communication_report,
    exporter=ReportsService.export_communication_report,
    stats=[
        ('Total Items', lambda rows: len(rows)),
        ('Addenda', lambda rows: sum(1 for r in rows if r.get('Type') == 'Addendum')),
        ('Direct Notices', lambda rows: sum(1 for r in rows if r.get('Type') == 'Notice')),
        ('Targeted', lambda rows: sum(1 for r in rows if r.get('Visibility') == 'targeted')),
    ],
)

# --- Messaging Activity --------------------------------------------------------
_register_table_report(
    key='messages',
    title='Messaging Activity',
    subtitle='Internal message volume, delivery and read status',
    icon='bi-envelope-open',
    columns=[
        ('Subject', 'Subject', False),
        ('Sender', 'Sender', False),
        ('Message Type', 'Type', True),
        ('Recipients', 'Recipients', False),
        ('Unread', 'Unread', False),
        ('Attachments', 'Attachments', False),
        ('Sent At', 'Sent At', False),
    ],
    filter_builder=lambda: [
        _make_filter_select('message_type', 'Message Type',
                            [('direct', 'Direct'), ('broadcast', 'Broadcast'), ('targeted', 'Targeted')], 'All Types'),
        _make_filter_select('sender_id', 'Sender',
                            [(u.id, f'{u.full_name()} ({u.username})') for u in User.query.order_by(User.first_name).all()], 'All Senders'),
        _make_date_filter('start_date', 'From'),
        _make_date_filter('end_date', 'To'),
    ],
    parse_filters=lambda: _add_date_filters({
        'message_type': _arg('message_type'),
        'sender_id': _arg_int('sender_id'),
    }),
    generator=ReportsService.generate_message_report,
    exporter=ReportsService.export_message_report,
    stats=[
        ('Total Messages', lambda rows: len(rows)),
        ('Broadcasts', lambda rows: sum(1 for r in rows if r.get('Message Type') == 'broadcast')),
        ('Direct', lambda rows: sum(1 for r in rows if r.get('Message Type') == 'direct')),
    ],
)

# --- Users & Accounts ------------------------------------------------------------
_register_table_report(
    key='users',
    title='Users & Accounts',
    subtitle='All system accounts, roles, activity and access status',
    icon='bi-person-badge',
    columns=[
        ('Username', 'Username', False),
        ('Full Name', 'Full Name', False),
        ('Role', 'Role', False),
        ('Role Code', 'Role Code', False),
        ('Department', 'Department', False),
        ('Email', 'Email', False),
        ('Status', 'Status', True),
        ('MFA Enabled', 'MFA', True),
        ('Last Login', 'Last Login', False),
        ('Created At', 'Created At', False),
    ],
    filter_builder=lambda: [
        _make_filter_select('role', 'Role',
                            [(r.code, r.name) for r in Role.query.order_by(Role.name).all()], 'All Roles'),
        _make_filter_select('status', 'Account Status',
                            [('active', 'Active'), ('inactive', 'Inactive')], 'Any'),
        _make_date_filter('start_date', 'Created From'),
        _make_date_filter('end_date', 'Created To'),
    ],
    parse_filters=lambda: _add_date_filters({
        'role': _arg('role'),
        'status': _arg('status'),
    }),
    generator=ReportsService.generate_user_account_report,
    exporter=ReportsService.export_user_account_report,
    stats=[
        ('Total Accounts', lambda rows: len(rows)),
        ('Active', lambda rows: sum(1 for r in rows if r.get('Status') == 'active')),
        ('MFA Enabled', lambda rows: sum(1 for r in rows if r.get('MFA Enabled') == 'Yes')),
    ],
)

