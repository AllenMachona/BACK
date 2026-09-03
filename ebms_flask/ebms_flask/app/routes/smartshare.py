from collections import defaultdict
from flask import Blueprint, render_template, redirect, url_for, request, flash, abort
from flask_login import login_required, current_user
from app.extensions import db
from app.models.procurement import Procurement
from app.models.procurement_share import ProcurementShare
from app.models.user import User
from app.utils.audit import log_action
from app.utils.notify import notify_user

smartshare_bp = Blueprint('smartshare', __name__, url_prefix='/smartshare')


def _is_internal(user):
    return bool(user and user.is_active and not user.has_role('bidder') and not user.bidder_id)


def _can_manage(procurement=None):
    if not _is_internal(current_user) or not current_user.has_role('procurement_unit'):
        return False
    if procurement is None:
        return True
    return current_user.can_access_procurement(procurement)


def _recipient_users():
    # Keep this filter dialect-neutral for SQL Server BIT columns.
    users = User.query.order_by(User.first_name.asc(), User.last_name.asc()).all()
    return [user for user in users if user.id != current_user.id and _is_internal(user)]


@smartshare_bp.route('/')
@login_required
def portal():
    if not _is_internal(current_user):
        abort(403)
    grants = ProcurementShare.query.filter_by(
        recipient_id=current_user.id,
        status='active',
    ).join(Procurement).order_by(Procurement.updated_at.desc()).all()
    folders = defaultdict(list)
    for grant in grants:
        folders[grant.folder_name or 'Shared procurements'].append(grant)
    return render_template('smartshare_portal.html', folders=dict(folders))


@smartshare_bp.route('/manage')
@login_required
def manage():
    if not _can_manage():
        abort(403)
    procurements = Procurement.query.order_by(Procurement.updated_at.desc()).all()
    if not current_user.has_permission('can_admin_system'):
        procurements = [p for p in procurements if current_user.can_access_procurement(p)]
    grants = ProcurementShare.query.order_by(ProcurementShare.shared_at.desc()).all()
    if not current_user.has_permission('can_admin_system'):
        grants = [grant for grant in grants if grant.shared_by_id == current_user.id or current_user.can_access_procurement(grant.procurement)]
    return render_template(
        'smartshare_manage.html',
        procurements=procurements,
        recipients=_recipient_users(),
        grants=grants,
        selected_procurement_id=request.args.get('procurement_id', type=int),
    )


@smartshare_bp.route('/share', methods=['POST'])
@login_required
def share():
    if not _can_manage():
        abort(403)
    procurement = Procurement.query.get_or_404(request.form.get('procurement_id', type=int))
    recipient = User.query.get_or_404(request.form.get('recipient_id', type=int))
    if not _can_manage(procurement):
        abort(403)
    if not _is_internal(recipient) or recipient.id == current_user.id:
        flash('SmartShare recipients must be active internal portal users, not bidders.', 'danger')
        return redirect(url_for('smartshare.manage'))

    folder_name = (request.form.get('folder_name') or 'Shared procurements').strip()[:120]
    if not folder_name:
        folder_name = 'Shared procurements'
    grant = ProcurementShare.query.filter_by(
        procurement_id=procurement.id,
        recipient_id=recipient.id,
    ).first()
    if grant:
        grant.folder_name = folder_name
        grant.status = 'active'
        grant.revoked_at = None
        grant.revoked_by_id = None
        grant.shared_by_id = current_user.id
    else:
        grant = ProcurementShare(
            procurement_id=procurement.id,
            recipient_id=recipient.id,
            shared_by_id=current_user.id,
            folder_name=folder_name,
        )
        db.session.add(grant)
    db.session.commit()
    notify_user(
        recipient,
        'smartshare_access_granted',
        f'Procurement shared with you: {procurement.tender_number}',
        f'{current_user.full_name()} shared {procurement.title} with you in SmartShare.',
        procurement_id=procurement.id,
        email=False,
    )
    log_action('SMARTSHARE_ACCESS_GRANTED', entity_type='Procurement', entity_id=procurement.id,
               new_value={'recipient_id': recipient.id, 'folder': folder_name})
    flash(f'{procurement.tender_number} shared with {recipient.full_name()}.', 'success')
    return redirect(url_for('smartshare.manage'))


@smartshare_bp.route('/<int:share_id>/revoke', methods=['POST'])
@login_required
def revoke(share_id):
    grant = ProcurementShare.query.get_or_404(share_id)
    if not _can_manage(grant.procurement):
        abort(403)
    if grant.status != 'active':
        flash('This SmartShare access has already been revoked.', 'info')
        return redirect(url_for('smartshare.manage'))
    grant.revoke(current_user)
    db.session.commit()
    notify_user(
        grant.recipient,
        'smartshare_access_revoked',
        f'SmartShare access revoked: {grant.procurement.tender_number}',
        f'Your access to {grant.procurement.title} has been revoked by {current_user.full_name()}.',
        procurement_id=grant.procurement_id,
        email=False,
    )
    log_action('SMARTSHARE_ACCESS_REVOKED', entity_type='Procurement', entity_id=grant.procurement_id,
               new_value={'recipient_id': grant.recipient_id})
    flash('SmartShare access revoked immediately.', 'success')
    return redirect(url_for('smartshare.manage'))
