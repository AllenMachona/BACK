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
        Procurement.status.in_(['published', 'submission_open'])
    ).order_by(Procurement.submission_deadline).all()

    my_submissions = Submission.query.filter_by(bidder_id=current_user.bidder_id).order_by(
        Submission.submitted_at.desc()
    ).all()

    return render_template('bidder_portal.html', available=available, my_submissions=my_submissions)


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

        if action == 'submit_bid':
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

                filename = secure_filename(f"{procurement.tender_number}_{current_user.bidder_id}_{envelope_type}_{secrets.token_hex(4)}.sealed")
                filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
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
    my_submissions = Submission.query.filter_by(
        procurement_id=procurement.id, bidder_id=current_user.bidder_id
    ).all()

    return render_template(
        'bidder_workspace.html', procurement=procurement, documents=documents,
        clarifications=clarifications, my_submissions=my_submissions,
    )
