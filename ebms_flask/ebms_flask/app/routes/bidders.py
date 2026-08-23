import os
import secrets
from datetime import datetime
from flask import Blueprint, render_template, redirect, url_for, request, flash, current_app, abort
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from app.extensions import db
from app.models.procurement import Procurement
from app.models.submission import Submission
from app.models.communication import Communication
from app.utils.crypto import encrypt_bytes, sha256_hex
from app.utils.audit import log_action
from app.utils.decorators import role_required

from app.models.user import User
from app.models.role import Role
from app.models.payment import BidderPayment, BidderDocumentAccess
from app.utils.notify import notify_user

bidders_bp = Blueprint('bidders', __name__, url_prefix='/bidders')


def _require_bidder():
    if not current_user.has_role('bidder') or not current_user.bidder_id:
        abort(403)


@bidders_bp.route('/portal')
@login_required
@role_required('bidder')
def portal():
    _require_bidder()
    available = Procurement.query.filter(
        Procurement.status.in_(['published', 'submission_open', 'clarification_period'])
    ).order_by(Procurement.submission_deadline).all()

    my_submissions = Submission.query.filter_by(bidder_id=current_user.bidder_id).order_by(
        Submission.submitted_at.desc()
    ).all()

    # Track payments per available tender
    payments = {p.id: current_user.bidder.get_payment_for_procurement(p.id) for p in available}

    return render_template('bidder_portal.html', available=available, my_submissions=my_submissions, payments=payments)


@bidders_bp.route('/workspace/<int:procurement_id>', methods=['GET', 'POST'])
@login_required
@role_required('bidder')
def workspace(procurement_id):
    _require_bidder()
    procurement = Procurement.query.get_or_404(procurement_id)
    if procurement.status not in ('published', 'submission_open', 'clarification_period'):
        abort(404)

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

        if action == 'submit_payment':
            payment_reference = request.form.get('payment_reference', '').strip()
            amount_raw = request.form.get('amount', '').strip()
            proof_file = request.files.get('proof_file')

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
                notify_user(
                    officer, 'payment_submitted',
                    f'Payment Proof Submitted: {procurement.tender_number}',
                    f'Bidder {current_user.bidder.company_name} has submitted proof of payment (Ref: {payment_reference}, Amount: BWP {amount:,.2f}) for {procurement.title}. Please review and verify.',
                    procurement_id=procurement.id
                )

            flash('Payment proof submitted successfully! Your submission is now pending Procurement verification. Tender documents will unlock once approved.', 'success')
            return redirect(url_for('bidders.workspace', procurement_id=procurement_id))

        if action == 'submit_bid':
            from app.models.site_setting import SiteSetting
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

                submission = Submission(
                    procurement_id=procurement.id, bidder_id=current_user.bidder_id, envelope_type=envelope_type,
                    file_path=filepath, original_filename=file.filename, sha256_hash=file_hash,
                    file_size_bytes=len(plaintext), version=prior_count + 1,
                    submitted_by_id=current_user.id, declaration_accepted=True,
                    receipt_code=f"SUB-{datetime.utcnow():%Y%m%d}-{secrets.token_hex(4).upper()}",
                )
                db.session.add(submission)
                db.session.commit()

                log_action('BID_SUBMITTED', entity_type='Submission', entity_id=submission.id,
                           new_value={'envelope_type': envelope_type, 'hash': file_hash, 'receipt': submission.receipt_code})
                submitted_any = True

            if submitted_any:
                flash('Your sealed bid has been submitted and encrypted. Check "My Submissions" for your receipt.', 'success')
            else:
                flash('No file was selected to upload.', 'warning')
            return redirect(url_for('bidders.portal'))

    documents = procurement.communications.filter_by(type='addendum').all()
    clarifications = procurement.communications.filter_by(type='clarification', is_public=True).order_by(
        Communication.created_at.desc()
    ).all()
    advertisement = procurement.communications.filter_by(type='advertisement').order_by(
        Communication.created_at.desc()
    ).first()
    my_submissions = Submission.query.filter_by(
        procurement_id=procurement.id, bidder_id=current_user.bidder_id
    ).all()

    # Query payment and document access for current bidder
    my_payment = current_user.bidder.get_payment_for_procurement(procurement.id)
    has_approved_payment = current_user.bidder.has_approved_payment_for_procurement(procurement.id)
    has_rfce_access = current_user.bidder.has_document_access(procurement.id, 'rfce')
    has_itt_access = current_user.bidder.has_document_access(procurement.id, 'itt')

    if not has_approved_payment:
        documents = []
        clarifications = []
        advertisement = None

    return render_template(
        'bidder_workspace.html',
        procurement=procurement,
        documents=documents,
        clarifications=clarifications,
        advertisement=advertisement,
        my_submissions=my_submissions,
        my_payment=my_payment,
        has_rfce_access=has_rfce_access,
        has_itt_access=has_itt_access,
        has_approved_payment=has_approved_payment,
    )
