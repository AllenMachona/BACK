"""Routes for managing clarifications with visibility and access control.

Supports public and targeted clarifications with backend-enforced access control.
"""
from flask import Blueprint, render_template, redirect, url_for, request, flash, send_file, abort
from flask_login import login_required, current_user
import os
from app.extensions import db
from app.models.communication import Communication
from app.models.procurement import Procurement
from app.models.bidder import Bidder
from app.utils.clarification_access import ClarificationAccessService
from app.utils.decorators import permission_required

clarifications_bp = Blueprint('clarifications', __name__, url_prefix='/procurements')


@clarifications_bp.route('/<int:procurement_id>/clarifications')
@login_required
def list_clarifications(procurement_id):
    """List all clarifications for a procurement."""
    procurement = Procurement.query.get_or_404(procurement_id)
    
    # Check access to procurement
    if current_user.has_role('bidder'):
        if procurement.status not in ['published', 'submission_open', 'clarification_period', 'closed']:
            abort(403)
    elif not (current_user.has_role('system_admin') or current_user.has_permission('can_create_procurement')):
        abort(403)
    
    # Get clarifications based on visibility
    query = Communication.query.filter_by(procurement_id=procurement_id)
    
    if current_user.has_role('bidder'):
        from sqlalchemy import or_
        from app.models.clarification import ClarificationVisibility
        
        bidder_id = current_user.bidder_id
        query = query.filter(
            or_(
                Communication.visibility_type == 'public',
                Communication.id.in_(
                    db.session.query(ClarificationVisibility.communication_id).filter_by(
                        bidder_id=bidder_id
                    )
                )
            )
        )
    
    clarifications = query.order_by(Communication.created_at.desc()).all()
    
    # Counts for stats display
    all_comms = Communication.query.filter_by(procurement_id=procurement_id)
    public_count = all_comms.filter_by(visibility_type='public').count()
    targeted_count = all_comms.filter_by(visibility_type='targeted').count()
    
    return render_template(
        'clarifications/list.html',
        procurement=procurement,
        clarifications=clarifications,
        public_count=public_count,
        targeted_count=targeted_count
    )


@clarifications_bp.route('/<int:procurement_id>/clarifications/<int:communication_id>')
@login_required
def view_clarification(procurement_id, communication_id):
    """View a single clarification with access control."""
    procurement = Procurement.query.get_or_404(procurement_id)
    clarification = Communication.query.get_or_404(communication_id)
    
    if clarification.procurement_id != procurement_id:
        abort(404)
    
    if current_user.has_role('bidder'):
        bidder_id = current_user.bidder_id
        if not ClarificationAccessService.can_bidder_view_clarification(communication_id, bidder_id):
            flash('You do not have access to this clarification.', 'danger')
            return redirect(url_for('clarifications.list_clarifications', procurement_id=procurement_id))
        
        ClarificationAccessService.log_access(
            communication_id=communication_id,
            bidder_id=bidder_id,
            accessed_by_user_id=current_user.id,
            access_type='view'
        )
    elif not (current_user.has_role('system_admin') or current_user.has_permission('can_create_procurement')):
        abort(403)
    
    access_log = None
    if current_user.has_role('system_admin') or current_user.has_permission('can_create_procurement'):
        access_log = ClarificationAccessService.get_access_log(communication_id, limit=50)
    
    return render_template(
        'clarifications/view.html',
        procurement=procurement,
        clarification=clarification,
        access_log=access_log
    )


@clarifications_bp.route('/<int:procurement_id>/clarifications/<int:communication_id>/manage-visibility', methods=['GET', 'POST'])
@login_required
@permission_required('can_create_procurement')
def manage_visibility(procurement_id, communication_id):
    """Manage clarification visibility."""
    procurement = Procurement.query.get_or_404(procurement_id)
    clarification = Communication.query.get_or_404(communication_id)
    
    if clarification.procurement_id != procurement_id:
        abort(404)
    
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'make_public':
            ClarificationAccessService.convert_to_public(communication_id, reason='Staff converted to public')
            flash('Clarification is now public.', 'success')
        
        elif action == 'make_targeted':
            ClarificationAccessService.convert_to_targeted(communication_id, reason='Staff converted to targeted')
            flash('Clarification is now targeted.', 'success')
        
        elif action == 'grant_access':
            bidder_id = request.form.get('bidder_id', type=int)
            if bidder_id:
                ClarificationAccessService.grant_clarification_access(
                    communication_id=communication_id,
                    bidder_id=bidder_id,
                    reason='Access granted by staff'
                )
                flash('Access granted.', 'success')
        
        elif action == 'revoke_access':
            bidder_id = request.form.get('bidder_id', type=int)
            if bidder_id:
                ClarificationAccessService.revoke_clarification_access(
                    communication_id=communication_id,
                    bidder_id=bidder_id,
                    reason='Access revoked by staff'
                )
                flash('Access revoked.', 'success')
        
        return redirect(url_for('clarifications.manage_visibility', 
                              procurement_id=procurement_id, 
                              communication_id=communication_id))
    
    recipients = ClarificationAccessService.get_clarification_recipients(communication_id)
    all_bidders = Bidder.query.filter_by(active=True, suspended=False).all()
    
    return render_template(
        'clarifications/manage_visibility.html',
        procurement=procurement,
        clarification=clarification,
        recipients=recipients,
        all_bidders=all_bidders
    )


@clarifications_bp.route('/<int:procurement_id>/clarifications/<int:communication_id>/download', methods=['GET'])
@login_required
def download_clarification_file(procurement_id, communication_id):
    """Download clarification document with access control."""
    procurement = Procurement.query.get_or_404(procurement_id)
    clarification = Communication.query.get_or_404(communication_id)
    
    if clarification.procurement_id != procurement_id:
        abort(404)
    
    if not clarification.file_path:
        flash('This clarification has no attached file.', 'warning')
        return redirect(url_for('clarifications.view_clarification',
                              procurement_id=procurement_id,
                              communication_id=communication_id))
    
    if current_user.has_role('bidder'):
        bidder_id = current_user.bidder_id
        if not ClarificationAccessService.can_bidder_view_clarification(communication_id, bidder_id):
            flash('You do not have access to this file.', 'danger')
            return redirect(url_for('clarifications.list_clarifications', procurement_id=procurement_id))
        
        ClarificationAccessService.log_access(
            communication_id=communication_id,
            bidder_id=bidder_id,
            accessed_by_user_id=current_user.id,
            access_type='download'
        )
    
    if not os.path.exists(clarification.file_path):
        flash('File not found.', 'danger')
        return redirect(url_for('clarifications.view_clarification',
                              procurement_id=procurement_id,
                              communication_id=communication_id))
    
    return send_file(
        clarification.file_path,
        as_attachment=True,
        download_name=clarification.original_filename
    )
