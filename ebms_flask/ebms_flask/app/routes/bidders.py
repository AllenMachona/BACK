import os
import secrets
from datetime import datetime
from flask import Blueprint, render_template, redirect, url_for, request, flash, current_app, abort
from flask_login import login_required, current_user
from sqlalchemy import or_
from werkzeug.utils import secure_filename
from app.extensions import db
from app.models.procurement import Procurement
from app.models.submission import Submission
from app.models.communication import Communication
from app.models.clarification import ClarificationVisibility
from app.utils.crypto import encrypt_bytes, sha256_hex
from app.utils.audit import log_action
from app.utils.decorators import role_required

from app.models.user import User
from app.models.role import Role
from app.models.payment import BidderPayment, BidderDocumentAccess
from app.models.complaint import Complaint
from app.utils.notify import notify_user

bidders_bp = Blueprint('bidders', __name__, url_prefix='/bidders')


def _require_bidder():
    if not current_user.has_role('bidder') or not current_user.bidder_id:
        abort(403)


def _procurement_progress(procurement):
    if procurement.status in ('award_published', 'cooling_off', 'complaint_hold', 'ready_for_contract', 'archived'):
        return 'Awarded'
    if procurement.status in ('closed', 'technical_opening', 'compliance_evaluation',
                              'under_evaluation',
                              'technical_evaluation', 'technical_outcome_approved',
                              'financial_opening', 'financial_evaluation', 'award_pending_approval'):
        return 'Under Evaluation'
    if procurement.status in ('published', 'submission_open', 'clarification_period'):
        return 'Open for Bidding'
    return procurement.status_label()


@bidders_bp.route('/portal')
@login_required
@role_required('bidder')
def portal():
    _require_bidder()
    available = Procurement.query.filter(
        Procurement.status.in_(['published', 'submission_open'])
    ).order_by(Procurement.submission_deadline).all()

    my_submissions = Submission.query.filter_by(bidder_id=current_user.bidder_id, status='submitted').order_by(
        Submission.submitted_at.desc()
    ).all()
    my_payments = BidderPayment.query.filter_by(bidder_id=current_user.bidder_id).all()
    monitored_ids = {submission.procurement_id for submission in my_submissions}
    monitored_ids.update(payment.procurement_id for payment in my_payments)
    monitored = Procurement.query.filter(Procurement.id.in_(monitored_ids)).order_by(
        Procurement.updated_at.desc()
    ).all() if monitored_ids else []

    # Track payments per available tender
    payments = {p.id: current_user.bidder.get_payment_for_procurement(p.id) for p in available}

    return render_template('bidder_portal.html', available=available, monitored=monitored,
                           my_submissions=my_submissions, payments=payments)


def _bidder_portal_data():
    available = Procurement.query.filter(
        Procurement.status.in_(['published', 'submission_open'])
    ).order_by(Procurement.submission_deadline).all()
    my_submissions = Submission.query.filter_by(
        bidder_id=current_user.bidder_id, status='submitted'
    ).order_by(Submission.submitted_at.desc()).all()
    my_payments = BidderPayment.query.filter_by(bidder_id=current_user.bidder_id).all()
    monitored_ids = {submission.procurement_id for submission in my_submissions}
    monitored_ids.update(payment.procurement_id for payment in my_payments)
    monitored = Procurement.query.filter(Procurement.id.in_(monitored_ids)).order_by(
        Procurement.updated_at.desc()
    ).all() if monitored_ids else []
    payments = {p.id: current_user.bidder.get_payment_for_procurement(p.id) for p in available}
    return available, monitored, my_submissions, payments


@bidders_bp.route('/progress')
@login_required
@role_required('bidder')
def progress():
    _require_bidder()
    _, monitored, my_submissions, _ = _bidder_portal_data()
    return render_template('bidder_progress.html', monitored=monitored, my_submissions=my_submissions)


@bidders_bp.route('/open-tenders')
@login_required
@role_required('bidder')
def open_tenders():
    _require_bidder()
    available, _, _, payments = _bidder_portal_data()
    return render_template('bidder_open_tenders.html', available=available, payments=payments)


@bidders_bp.route('/complaints')
@login_required
@role_required('bidder')
def complaints():
    _require_bidder()
    procurements = Procurement.query.join(
        Submission, Submission.procurement_id == Procurement.id
    ).filter(
        Submission.bidder_id == current_user.bidder_id,
        Submission.status == 'submitted',
    ).distinct().order_by(Procurement.updated_at.desc()).all()
    selected_id = request.args.get('procurement_id', type=int)
    selected_procurement = next(
        (procurement for procurement in procurements if procurement.id == selected_id),
        procurements[0] if procurements else None,
    )
    selected_complaints = Complaint.query.filter_by(
        procurement_id=selected_procurement.id,
        bidder_id=current_user.bidder_id,
    ).order_by(Complaint.created_at.desc()).all() if selected_procurement else []
    return render_template(
        'bidder_complaints.html',
        procurements=procurements,
        selected_procurement=selected_procurement,
        selected_complaints=selected_complaints,
    )


@bidders_bp.route('/workspace/<int:procurement_id>', methods=['GET', 'POST'])
@login_required
@role_required('bidder')
def workspace(procurement_id):
    _require_bidder()
    procurement = Procurement.query.get_or_404(procurement_id)
    has_participated = bool(
        Submission.query.filter_by(procurement_id=procurement.id, bidder_id=current_user.bidder_id).first()
        or BidderPayment.query.filter_by(procurement_id=procurement.id, bidder_id=current_user.bidder_id).first()
    )
    if procurement.status not in ('published', 'submission_open', 'clarification_period') and not has_participated:
        abort(404)
    payment_required = procurement.has_itt()
    has_approved_payment = (
        not payment_required
        or current_user.bidder.has_approved_payment_for_procurement(procurement.id)
    )
    award = procurement.award
    can_submit_bid = bool(
        has_approved_payment
        and procurement.status == 'submission_open'
        and (not procurement.submission_deadline or datetime.utcnow() <= procurement.submission_deadline)
    )

    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'ask_question':
            question = request.form.get('question', '').strip()
            if question:
                comm = Communication(
                    procurement_id=procurement.id, type='question', content=question,
                    from_bidder_id=current_user.bidder_id, is_public=False,
                )
                db.session.add(comm)
                db.session.commit()
                log_action('QUESTION_SUBMITTED', entity_type='Communication', entity_id=comm.id)
                flash('Your question has been submitted and will be published after review.', 'success')
            return redirect(url_for('bidders.workspace', procurement_id=procurement_id))

        if action == 'submit_complaint':
            if not Submission.query.filter_by(
                procurement_id=procurement.id,
                bidder_id=current_user.bidder_id,
                status='submitted',
            ).first():
                flash('You can post a complaint after submitting a bid for this procurement.', 'warning')
                return redirect(url_for('bidders.workspace', procurement_id=procurement_id))
            grounds = request.form.get('grounds', '').strip()
            relief_sought = request.form.get('relief_sought', '').strip() or None
            if not grounds:
                flash('Please describe the grounds of your complaint.', 'danger')
                return redirect(url_for('bidders.workspace', procurement_id=procurement_id))

            complaint = Complaint(
                procurement_id=procurement.id,
                bidder_id=current_user.bidder_id,
                grounds=grounds,
                relief_sought=relief_sought,
                status='received',
            )
            db.session.add(complaint)
            db.session.commit()
            log_action(
                'COMPLAINT_SUBMITTED',
                entity_type='Complaint',
                entity_id=complaint.id,
                new_value={'procurement_id': procurement.id, 'bidder_id': current_user.bidder_id},
            )

            procurement_users = User.query.join(Role).filter(
                Role.code.in_(['procurement_unit', 'system_admin', 'procurement_oversight'])
            ).all()
            for officer in procurement_users:
                try:
                    notify_user(
                        officer,
                        'complaint_received',
                        f'Complaint Received: {procurement.tender_number}',
                        f'{current_user.bidder.company_name} submitted a complaint for {procurement.title}.',
                        procurement_id=procurement.id,
                        email=False,
                    )
                except Exception:
                    current_app.logger.exception(
                        'Complaint notification failed after complaint %s was saved', complaint.id
                    )
            flash('Your complaint has been submitted and is now visible to Procurement.', 'success')
            return redirect(url_for('bidders.workspace', procurement_id=procurement_id))

        if action == 'submit_payment':
            payment_reference = request.form.get('payment_reference', '').strip()
            amount_raw = request.form.get('amount', '').strip()
            proof_file = request.files.get('proof_file')
            supporting_document = request.files.get('supporting_document')

            if not payment_reference:
                flash('Payment reference is required.', 'danger')
                return redirect(url_for('bidders.workspace', procurement_id=procurement_id))

            try:
                amount = float(amount_raw) if amount_raw else float(procurement.tender_fee or 0.0)
            except ValueError:
                flash('Please enter a valid numeric payment amount.', 'danger')
                return redirect(url_for('bidders.workspace', procurement_id=procurement_id))

            if not proof_file or not proof_file.filename:
                flash('Please upload a proof of payment document (PDF, PNG, JPG, DOCX).', 'danger')
                return redirect(url_for('bidders.workspace', procurement_id=procurement_id))

            payments_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'payments')
            os.makedirs(payments_dir, exist_ok=True)
            token = secrets.token_hex(4)
            filename = secure_filename(f"{procurement.tender_number}_{current_user.bidder_id}_{token}_{proof_file.filename}")
            filepath = os.path.join(payments_dir, filename)
            proof_file.save(filepath)

            support_path = None
            support_filename = None
            if supporting_document and supporting_document.filename:
                support_token = secrets.token_hex(4)
                support_filename = secure_filename(f"{procurement.tender_number}_{current_user.bidder_id}_{support_token}_{supporting_document.filename}")
                support_path = os.path.join(payments_dir, support_filename)
                supporting_document.save(support_path)

            # Check if there is an existing payment record to update (resubmission)
            payment = BidderPayment.query.filter_by(
                procurement_id=procurement.id,
                bidder_id=current_user.bidder_id
            ).first()

            if payment:
                payment.payment_reference = payment_reference
                payment.amount = amount
                payment.proof_file_path = filepath
                payment.proof_filename = proof_file.filename
                if support_path:
                    payment.supporting_document_path = support_path
                    payment.supporting_document_filename = supporting_document.filename
                payment.status = 'pending'
                payment.notes = None
                payment.submitted_at = datetime.utcnow()
                payment.submitted_by_id = current_user.id
                payment.reviewed_by_id = None
                payment.reviewed_at = None
            else:
                payment = BidderPayment(
                    procurement_id=procurement.id,
                    bidder_id=current_user.bidder_id,
                    submitted_by_id=current_user.id,
                    payment_reference=payment_reference,
                    amount=amount,
                    proof_file_path=filepath,
                    proof_filename=proof_file.filename,
                    supporting_document_path=support_path,
                    supporting_document_filename=support_filename,
                    status='pending'
                )
                db.session.add(payment)

            db.session.commit()

            log_action('PAYMENT_PROOF_SUBMITTED', entity_type='BidderPayment', entity_id=payment.id,
                       new_value={'procurement_id': procurement.id, 'bidder_id': current_user.bidder_id,
                                  'reference': payment_reference, 'amount': amount})

            # Notify Procurement Unit
            procurement_users = User.query.join(Role).filter(
                Role.code.in_(['procurement_unit', 'system_admin', 'procurement_oversight'])
            ).all()

            for officer in procurement_users:
                try:
                    notify_user(
                        officer, 'payment_submitted',
                        f'Payment Proof Submitted: {procurement.tender_number}',
                        f'Bidder {current_user.bidder.company_name} has submitted proof of payment (Ref: {payment_reference}, Amount: BWP {amount:,.2f}) for {procurement.title}. Please review and verify.',
                        procurement_id=procurement.id,
                        email=False,
                    )
                except Exception:
                    current_app.logger.exception(
                        'Payment notification failed after proof was saved for procurement %s',
                        procurement.id,
                    )

            flash('Payment proof submitted successfully! Your submission is now pending Procurement verification. Tender documents will unlock once approved.', 'success')
            return redirect(url_for('bidders.workspace', procurement_id=procurement_id))

        if action == 'submit_bid':
            from app.models.site_setting import SiteSetting
            if payment_required and not has_approved_payment:
                flash('Bid submission is available only after your payment has been approved.', 'warning')
                return redirect(url_for('bidders.workspace', procurement_id=procurement_id))
            if SiteSetting.get('enable_bid_submission', 'true').lower() != 'true':
                flash('Bid submission is temporarily disabled by the system administrator.', 'warning')
                return redirect(url_for('bidders.portal'))
            if procurement.status != 'submission_open':
                flash('Submissions are not currently open for this procurement.', 'danger')
                return redirect(url_for('bidders.workspace', procurement_id=procurement_id))

            if procurement.submission_deadline and datetime.utcnow() > procurement.submission_deadline:
                log_action('LATE_SUBMISSION_REJECTED', entity_type='Procurement', entity_id=procurement.id,
                           reason=f'Attempted after deadline {procurement.submission_deadline}')
                flash('The submission deadline has passed. This attempt has been logged.', 'danger')
                return redirect(url_for('bidders.workspace', procurement_id=procurement_id))

            if not request.form.get('declare'):
                flash('You must confirm the declaration before submitting.', 'danger')
                return redirect(url_for('bidders.workspace', procurement_id=procurement_id))

            combined_file = request.files.get('compliance_returnable_document')
            if not combined_file or not combined_file.filename:
                flash('You must upload the compliance and returnable document bundle before submitting the bid.', 'danger')
                return redirect(url_for('bidders.workspace', procurement_id=procurement_id))

            combined_bytes = combined_file.read()
            if not combined_bytes:
                flash('The compliance and returnable document bundle must not be empty.', 'danger')
                return redirect(url_for('bidders.workspace', procurement_id=procurement_id))

            envelope_map = (
                {'technical': 'technical_file', 'financial': 'financial_file'}
                if procurement.envelope_type == 'dual' else {'single': 'single_file'}
            )

            submitted_any = False
            for envelope_type, field_name in envelope_map.items():
                file = request.files.get(field_name)
                if not file or not file.filename:
                    continue

                plaintext = file.read()
                file_hash = sha256_hex(plaintext)
                sealed = encrypt_bytes(plaintext)

                procurement_folder = secure_filename(
                    f'{procurement.tender_number}_{procurement.title}'
                ) or f'procurement_{procurement.id}'
                submission_dir = os.path.join(
                    current_app.config['UPLOAD_FOLDER'], procurement_folder
                )
                os.makedirs(submission_dir, exist_ok=True)
                filename = secure_filename(f"{procurement.tender_number}_{current_user.bidder_id}_{envelope_type}_{secrets.token_hex(4)}.sealed")
                filepath = os.path.join(submission_dir, filename)
                with open(filepath, 'wb') as f:
                    f.write(sealed)

                # Mark any prior submission of this envelope type as replaced.
                Submission.query.filter_by(
                    procurement_id=procurement.id, bidder_id=current_user.bidder_id,
                    envelope_type=envelope_type, status='submitted'
                ).update({'status': 'replaced'})

                prior_count = Submission.query.filter_by(
                    procurement_id=procurement.id, bidder_id=current_user.bidder_id, envelope_type=envelope_type
                ).count()

                combined_path = os.path.join(submission_dir, secure_filename(f'{procurement.tender_number}_{current_user.bidder_id}_{envelope_type}_compliance_returnable_{secrets.token_hex(4)}_{combined_file.filename}'))
                with open(combined_path, 'wb') as combined_handle:
                    combined_handle.write(combined_bytes)

                submission = Submission(
                    procurement_id=procurement.id, bidder_id=current_user.bidder_id, envelope_type=envelope_type,
                    file_path=filepath, original_filename=file.filename, sha256_hash=file_hash,
                    file_size_bytes=len(plaintext), version=prior_count + 1,
                    compliance_document_path=combined_path,
                    compliance_document_filename=combined_file.filename,
                    compliance_document_hash=sha256_hex(combined_bytes),
                    returnable_document_path=combined_path,
                    returnable_document_filename=combined_file.filename,
                    returnable_document_hash=sha256_hex(combined_bytes),
                    submitted_by_id=current_user.id, declaration_accepted=True,
                    receipt_code=f"SUB-{datetime.utcnow():%Y%m%d}-{secrets.token_hex(4).upper()}",
                )
                db.session.add(submission)
                db.session.commit()

                log_action('BID_SUBMITTED', entity_type='Submission', entity_id=submission.id,
                           new_value={'envelope_type': envelope_type, 'hash': file_hash, 'receipt': submission.receipt_code})
                submitted_any = True

            if submitted_any:
                flash('Your sealed bid, compliance document, and returnable document were submitted successfully. Check "My Submissions" for your receipt.', 'success')
            else:
                flash('No file was selected to upload.', 'warning')
            return redirect(url_for('bidders.portal'))

    documents = procurement.communications.filter_by(type='addendum').all()
    clarifications = procurement.communications.filter(
        Communication.type == 'clarification',
        or_(
            Communication.visibility_type == 'public',
            Communication.id.in_(
                db.session.query(ClarificationVisibility.communication_id).filter_by(
                    bidder_id=current_user.bidder_id
                ).filter(ClarificationVisibility.revoked_at.is_(None))
            )
        )
    ).order_by(Communication.created_at.desc()).all()
    advertisement = procurement.communications.filter_by(type='advertisement').order_by(
        Communication.created_at.desc()
    ).first()
    my_submissions = Submission.query.filter_by(
        procurement_id=procurement.id, bidder_id=current_user.bidder_id, status='submitted'
    ).order_by(Submission.submitted_at.desc()).all()
    has_submitted_bid = bool(my_submissions)
    my_complaints = Complaint.query.filter_by(
        procurement_id=procurement.id,
        bidder_id=current_user.bidder_id,
    ).order_by(Complaint.created_at.desc()).all()

    # Query payment and document access for current bidder
    my_payment = current_user.bidder.get_payment_for_procurement(procurement.id)
    has_itt_access = current_user.bidder.has_document_access(procurement.id, 'itt')

    if not has_approved_payment:
        documents = []
        clarifications = []
        # Keep the public advertisement visible before payment. ITT and formal
        # addenda/notices remain restricted until the bidder's payment is approved.

    return render_template(
        'bidder_workspace.html',
        procurement=procurement,
        documents=documents,
        clarifications=clarifications,
        advertisement=advertisement,
        my_submissions=my_submissions,
        my_payment=my_payment,
        has_itt_access=has_itt_access,
        payment_required=payment_required,
        has_approved_payment=has_approved_payment,
        can_submit_bid=can_submit_bid,
        has_submitted_bid=has_submitted_bid,
        procurement_progress=_procurement_progress(procurement),
        award=award,
        my_complaints=my_complaints,
    )
