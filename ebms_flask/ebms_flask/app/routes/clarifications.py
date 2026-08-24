"""Routes for managing clarifications with visibility and access control.

Supports public and targeted clarifications with backend-enforced access control.
"""
from flask import Blueprint, render_template, redirect, url_for, request, flash, send_from_directory, abort, current_app
from flask_login import login_required, current_user
import os
import secrets
from app.extensions import db
from app.models.communication import Communication
from app.models.procurement import Procurement
from app.models.bidder import Bidder
from app.models.clarification import ClarificationVisibility
from app.models.user import User
from app.utils.clarification_access import ClarificationAccessService
from app.utils.decorators import permission_required
from app.utils.notify import notify_user
from werkzeug.utils import secure_filename

clarifications_bp = Blueprint('clarifications', __name__, url_prefix='/procurements')


@clarifications_bp.route('/<int:procurement_id>/clarifications/create', methods=['POST'])
@login_required
@permission_required('can_create_procurement')
def create_clarification(procurement_id):
    """Post a public or bidder-targeted clarification."""
    procurement = Procurement.query.get_or_404(procurement_id)
    content = request.form.get('content', '').strip()
    visibility_type = request.form.get('visibility_type', 'public')
    bidder_ids = {bidder_id for bidder_id in request.form.getlist('bidder_ids', type=int) if bidder_id}

    if not content:
        flash('Clarification content is required.', 'danger')
        return redirect(url_for('clarifications.list_clarifications', procurement_id=procurement.id))
    if visibility_type not in ('public', 'targeted'):
        flash('Choose a valid clarification visibility.', 'danger')
        return redirect(url_for('clarifications.list_clarifications', procurement_id=procurement.id))
    if visibility_type == 'targeted' and not bidder_ids:
        flash('Select at least one bidder for a targeted clarification.', 'danger')
        return redirect(url_for('clarifications.list_clarifications', procurement_id=procurement.id))

    clarification = Communication(
        procurement_id=procurement.id,
        type='clarification',
        content=content,
        visibility_type=visibility_type,
        is_public=visibility_type == 'public',
        from_user_id=current_user.id,
    )
    attachment = request.files.get('attachment')
    if attachment and attachment.filename:
        upload_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'clarifications')
        os.makedirs(upload_dir, exist_ok=True)
        filename = secure_filename(
            f'{procurement.tender_number}_clarification_{secrets.token_hex(4)}_{attachment.filename}'
        )
        clarification.file_path = os.path.join(upload_dir, filename)
        clarification.original_filename = attachment.filename
        attachment.save(clarification.file_path)

    db.session.add(clarification)
    db.session.flush()
    selected_bidder_ids = set()
    if visibility_type == 'targeted':
        for bidder_id in bidder_ids:
            bidder = Bidder.query.filter_by(id=bidder_id, active=True, suspended=False).first()
            if bidder:
                selected_bidder_ids.add(bidder.id)
                ClarificationAccessService.grant_clarification_access(
                    communication_id=clarification.id,
                    bidder_id=bidder.id,
                    reason='Selected when clarification was posted'
                )
        if not selected_bidder_ids:
            db.session.rollback()
            flash('The selected bidders are no longer available. Please choose active bidders.', 'danger')
            return redirect(url_for('clarifications.list_clarifications', procurement_id=procurement.id))
    db.session.commit()

    if visibility_type == 'targeted':
        bidder_users = User.query.filter(User.bidder_id.in_(selected_bidder_ids)).all()
    else:
        bidder_users = User.query.join(Bidder, User.bidder_id == Bidder.id).filter(
            Bidder.active == True,
            Bidder.suspended == False,
            Bidder.verified == True,
        ).all()

    for bidder_user in bidder_users:
        notify_user(
            bidder_user,
            'clarification_posted',
            f'New clarification posted: {procurement.tender_number}',
            f'A new clarification has been posted for {procurement.title}. '
            'Open the procurement workspace to view it.',
            procurement_id=procurement.id,
        )

    flash('Clarification posted successfully.', 'success')
    return redirect(url_for('clarifications.list_clarifications', procurement_id=procurement.id))


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
    query = Communication.query.filter_by(procurement_id=procurement_id, type='clarification')
    
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
                    ).filter(ClarificationVisibility.revoked_at.is_(None))
                )
            )
        )
    
    clarifications = query.order_by(Communication.created_at.desc()).all()
    
    # Counts for stats display
    all_comms = Communication.query.filter_by(procurement_id=procurement_id)
    public_count = all_comms.filter_by(visibility_type='public').count()
    targeted_count = all_comms.filter_by(visibility_type='targeted').count()
    all_bidders = Bidder.query.filter_by(active=True, suspended=False).order_by(Bidder.company_name).all()
    
    return render_template(
        'clarifications/list.html',
        procurement=procurement,
        clarifications=clarifications,
        public_count=public_count,
        targeted_count=targeted_count,
        all_bidders=all_bidders
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
        visibility_type = request.form.get('visibility_type')

        if visibility_type in ('public', 'targeted'):
            clarification.visibility_type = visibility_type
            clarification.is_public = visibility_type == 'public'
            db.session.commit()
            flash(f'Clarification is now {visibility_type}.', 'success')
            return redirect(url_for('clarifications.manage_visibility',
                                    procurement_id=procurement_id,
                                    communication_id=communication_id))
        
        if action == 'make_public':
            ClarificationAccessService.convert_to_public(communication_id, reason='Staff converted to public')
            flash('Clarification is now public.', 'success')
        
        elif action == 'make_targeted':
            ClarificationAccessService.convert_to_targeted(communication_id, reason='Staff converted to targeted')
            flash('Clarification is now targeted.', 'success')
        
        elif action == 'grant_access':
            bidder_ids = {bidder_id for bidder_id in request.form.getlist('bidder_ids', type=int) if bidder_id}
            if not bidder_ids:
                bidder_id = request.form.get('bidder_id', type=int)
                bidder_ids = {bidder_id} if bidder_id else set()
            for bidder_id in bidder_ids:
                if not Bidder.query.filter_by(id=bidder_id, active=True, suspended=False).first():
                    continue
                ClarificationAccessService.grant_clarification_access(
                    communication_id=communication_id,
                    bidder_id=bidder_id,
                    reason=request.form.get('reason') or 'Access granted by staff'
                )
            flash('Access granted to the selected bidders.', 'success')
        
        elif action == 'revoke_access':
            bidder_id = request.form.get('bidder_id', type=int)
            reason = request.form.get('reason', '').strip()
            if not bidder_id:
                flash('The bidder to revoke could not be identified.', 'danger')
            elif not reason:
                flash('A reason is required to revoke bidder access.', 'danger')
            else:
                revoked = ClarificationAccessService.revoke_clarification_access(
                    communication_id=communication_id,
                    bidder_id=bidder_id,
                    reason=reason
                )
                if revoked:
                    flash('Bidder access revoked successfully.', 'success')
                else:
                    flash('That bidder no longer has active access.', 'warning')
        
        return redirect(url_for('clarifications.manage_visibility', 
                              procurement_id=procurement_id, 
                              communication_id=communication_id))
    
    recipients = ClarificationAccessService.get_clarification_recipients(communication_id)
    all_bidders = Bidder.query.filter_by(active=True, suspended=False).order_by(Bidder.company_name).all()
    clarification_access = ClarificationAccessService.get_clarification_recipients(communication_id)
    active_recipient_ids = {
        access.bidder_id for access in ClarificationVisibility.query.filter_by(
            communication_id=communication_id
        ).filter(ClarificationVisibility.revoked_at.is_(None)).all()
    }
    available_bidders = [bidder for bidder in all_bidders if bidder.id not in active_recipient_ids]
    revoked_access = ClarificationVisibility.query.filter_by(
        communication_id=communication_id
    ).filter(ClarificationVisibility.revoked_at.isnot(None)).all()
    
    return render_template(
        'clarifications/manage_visibility.html',
        procurement=procurement,
        clarification=clarification,
        recipients=recipients,
        all_bidders=all_bidders,
        available_bidders=available_bidders,
        clarification_access=clarification_access,
        revoked_access=revoked_access
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
    
    file_path = clarification.file_path
    if not os.path.isfile(file_path):
        fallback_path = os.path.join(
            current_app.config['UPLOAD_FOLDER'],
            'clarifications',
            os.path.basename(file_path),
        )
        if os.path.isfile(fallback_path):
            file_path = fallback_path
        else:
            current_app.logger.warning(
                'Clarification attachment missing: communication=%s path=%s',
                communication_id,
                clarification.file_path,
            )
            abort(404)
    
    return send_from_directory(
        os.path.dirname(file_path),
        os.path.basename(file_path),
        as_attachment=True,
        download_name=clarification.original_filename,
    )
