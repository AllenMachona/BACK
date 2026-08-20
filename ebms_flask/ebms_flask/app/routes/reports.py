from datetime import datetime, timedelta
from flask import Blueprint, render_template, send_file, request, flash, redirect, url_for
from flask_login import login_required, current_user
from sqlalchemy import func
from app.extensions import db
from app.models.procurement import Procurement
from app.models.submission import Submission
from app.models.complaint import Complaint
from app.models.audit import AuditLog
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
    statuses = [p.status for p in Procurement.query.distinct(Procurement.status).all()]
    categories = [p.category for p in Procurement.query.distinct(Procurement.category).all() if p.category]
    
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
