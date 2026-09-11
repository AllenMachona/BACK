-- EBMS SQL Server database schema
-- Generated from ebms_flask/app/models using SQLAlchemy metadata.
-- This creates structure only; it does not insert application data.

IF DB_ID(N'ProcurementDB') IS NULL
    CREATE DATABASE [ProcurementDB];
GO
USE [ProcurementDB];
GO


CREATE TABLE bidders (
	id INTEGER NOT NULL IDENTITY, 
	company_name VARCHAR(200) NOT NULL, 
	ppra_registration_number VARCHAR(50) NULL, 
	ppra_grade VARCHAR(10) NULL, 
	category VARCHAR(50) NULL, 
	contact_email VARCHAR(120) NOT NULL, 
	contact_phone VARCHAR(20) NULL, 
	registered_at DATETIME NULL, 
	registration_expiry DATETIME NULL, 
	active BIT NULL, 
	suspended BIT NULL, 
	verified BIT NULL, 
	PRIMARY KEY (id)
)

;
GO


CREATE TABLE roles (
	id INTEGER NOT NULL IDENTITY, 
	code VARCHAR(50) NOT NULL, 
	name VARCHAR(100) NOT NULL, 
	description TEXT NULL, 
	created_at DATETIME NULL, 
	can_create_procurement BIT NULL, 
	can_approve_procurement BIT NULL, 
	can_publish BIT NULL, 
	can_evaluate BIT NULL, 
	can_open_bids BIT NULL, 
	can_award BIT NULL, 
	can_view_all_records BIT NULL, 
	can_admin_system BIT NULL, 
	can_bid BIT NULL, 
	PRIMARY KEY (id)
)

;
GO


CREATE TABLE site_settings (
	id INTEGER NOT NULL IDENTITY, 
	[key] VARCHAR(80) NOT NULL, 
	value VARCHAR(500) NOT NULL, 
	label VARCHAR(120) NOT NULL, 
	description TEXT NULL, 
	created_at DATETIME NULL, 
	updated_at DATETIME NULL, 
	PRIMARY KEY (id)
)

;
GO


CREATE TABLE users (
	id INTEGER NOT NULL IDENTITY, 
	uuid VARCHAR(36) NULL, 
	username VARCHAR(80) NOT NULL, 
	email VARCHAR(120) NOT NULL, 
	password_hash VARCHAR(256) NULL, 
	first_name VARCHAR(100) NOT NULL, 
	last_name VARCHAR(100) NOT NULL, 
	phone VARCHAR(20) NULL, 
	department VARCHAR(100) NULL, 
	designation VARCHAR(100) NULL, 
	employee_id VARCHAR(50) NULL, 
	role_id INTEGER NOT NULL, 
	delegation_limit NUMERIC(15, 2) NULL, 
	delegation_start DATETIME NULL, 
	delegation_end DATETIME NULL, 
	delegation_conditions TEXT NULL, 
	bidder_id INTEGER NULL, 
	is_active BIT NULL, 
	mfa_enabled BIT NULL, 
	mfa_secret VARCHAR(256) NULL, 
	last_login DATETIME NULL, 
	last_login_ip VARCHAR(45) NULL, 
	failed_login_attempts INTEGER NULL, 
	locked_until DATETIME NULL, 
	password_changed_at DATETIME NULL, 
	password_expiry_days INTEGER NULL, 
	reset_token VARCHAR(255) NULL, 
	reset_token_expires_at DATETIME NULL, 
	email_confirmation_token VARCHAR(255) NULL, 
	email_confirmation_expires_at DATETIME NULL, 
	email_confirmed_at DATETIME NULL, 
	preferences TEXT NULL, 
	federation_id VARCHAR(256) NULL, 
	federation_provider VARCHAR(50) NULL, 
	conflict_of_interest_declared BIT NULL, 
	conflict_of_interest_details TEXT NULL, 
	confidentiality_signed BIT NULL, 
	confidentiality_signed_at DATETIME NULL, 
	created_at DATETIME NULL, 
	created_by INTEGER NULL, 
	updated_at DATETIME NULL, 
	PRIMARY KEY (id), 
	UNIQUE (uuid), 
	FOREIGN KEY(role_id) REFERENCES roles (id), 
	FOREIGN KEY(bidder_id) REFERENCES bidders (id), 
	FOREIGN KEY(created_by) REFERENCES users (id)
)

;
GO


CREATE TABLE audit_logs (
	id INTEGER NOT NULL IDENTITY, 
	user_id INTEGER NULL, 
	action VARCHAR(100) NOT NULL, 
	entity_type VARCHAR(50) NULL, 
	entity_id INTEGER NULL, 
	previous_value TEXT NULL, 
	new_value TEXT NULL, 
	ip_address VARCHAR(45) NULL, 
	reason TEXT NULL, 
	created_at DATETIME NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id)
)

;
GO


CREATE TABLE bidder_compliance_documents (
	id INTEGER NOT NULL IDENTITY, 
	bidder_id INTEGER NOT NULL, 
	document_type VARCHAR(50) NOT NULL, 
	file_path VARCHAR(500) NOT NULL, 
	original_filename VARCHAR(300) NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	review_notes TEXT NULL, 
	submitted_at DATETIME NOT NULL, 
	reviewed_at DATETIME NULL, 
	reviewed_by_id INTEGER NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_bidder_compliance_document_type UNIQUE (bidder_id, document_type), 
	FOREIGN KEY(bidder_id) REFERENCES bidders (id), 
	FOREIGN KEY(reviewed_by_id) REFERENCES users (id)
)

;
GO


CREATE TABLE document_versions (
	id INTEGER NOT NULL IDENTITY, 
	document_type VARCHAR(50) NOT NULL, 
	entity_type VARCHAR(50) NOT NULL, 
	entity_id INTEGER NOT NULL, 
	version_number INTEGER NOT NULL, 
	is_current BIT NULL, 
	file_path VARCHAR(500) NOT NULL, 
	file_name VARCHAR(300) NOT NULL, 
	file_size_bytes INTEGER NULL, 
	file_hash VARCHAR(64) NULL, 
	created_by_id INTEGER NOT NULL, 
	created_at DATETIME NULL, 
	restored_from_version INTEGER NULL, 
	restored_by_id INTEGER NULL, 
	restored_at DATETIME NULL, 
	restoration_reason TEXT NULL, 
	description TEXT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(created_by_id) REFERENCES users (id), 
	FOREIGN KEY(restored_by_id) REFERENCES users (id)
)

;
GO


CREATE TABLE procurement_plan_items (
	id INTEGER NOT NULL IDENTITY, 
	procurement_entity VARCHAR(200) NOT NULL, 
	financial_year VARCHAR(20) NOT NULL, 
	title VARCHAR(300) NOT NULL, 
	description TEXT NULL, 
	ppra_code VARCHAR(50) NULL, 
	ppra_sub_code VARCHAR(20) NULL, 
	ppra_description TEXT NULL, 
	category VARCHAR(50) NOT NULL, 
	method VARCHAR(50) NOT NULL, 
	estimated_value NUMERIC(15, 2) NOT NULL, 
	planned_quarter VARCHAR(2) NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	created_by_id INTEGER NOT NULL, 
	created_at DATETIME NULL, 
	updated_at DATETIME NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(created_by_id) REFERENCES users (id)
)

;
GO


CREATE TABLE procurements (
	id INTEGER NOT NULL IDENTITY, 
	tender_number VARCHAR(50) NOT NULL, 
	title VARCHAR(300) NOT NULL, 
	description TEXT NULL, 
	category VARCHAR(30) NOT NULL, 
	procurement_entity VARCHAR(200) NULL, 
	ppra_code VARCHAR(50) NULL, 
	ppra_sub_code VARCHAR(20) NULL, 
	method VARCHAR(30) NOT NULL, 
	evaluation_method VARCHAR(50) NULL, 
	envelope_type VARCHAR(10) NULL, 
	estimated_value NUMERIC(15, 2) NOT NULL, 
	user_department VARCHAR(150) NULL, 
	submission_deadline DATETIME NULL, 
	clarification_deadline DATETIME NULL, 
	opening_scheduled_at DATETIME NULL, 
	evaluator_feedback_released_at DATETIME NULL, 
	evaluator_feedback_released_by_id INTEGER NULL, 
	status VARCHAR(30) NULL, 
	cancelled BIT NULL, 
	cancelled_reason TEXT NULL, 
	cancelled_at DATETIME NULL, 
	replacement_of_id INTEGER NULL, 
	created_by_id INTEGER NOT NULL, 
	created_at DATETIME NULL, 
	updated_at DATETIME NULL, 
	tender_fee NUMERIC(15, 2) NULL, 
	form_d_file_path VARCHAR(500) NULL, 
	form_d_filename VARCHAR(300) NULL, 
	form_e_file_path VARCHAR(500) NULL, 
	form_e_filename VARCHAR(300) NULL, 
	itt_file_path VARCHAR(500) NULL, 
	itt_filename VARCHAR(300) NULL, 
	rfq_file_path VARCHAR(500) NULL, 
	rfq_filename VARCHAR(300) NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(evaluator_feedback_released_by_id) REFERENCES users (id), 
	FOREIGN KEY(replacement_of_id) REFERENCES procurements (id), 
	FOREIGN KEY(created_by_id) REFERENCES users (id)
)

;
GO


CREATE TABLE awards (
	id INTEGER NOT NULL IDENTITY, 
	procurement_id INTEGER NOT NULL, 
	winning_bidder_id INTEGER NOT NULL, 
	decision_date DATETIME NULL, 
	cooling_off_expiry DATETIME NOT NULL, 
	contract_concluded BIT NULL, 
	contract_concluded_at DATETIME NULL, 
	award_value NUMERIC(15, 2) NULL, 
	decision_reason TEXT NULL, 
	decision_notes TEXT NULL, 
	published_at DATETIME NULL, 
	published_by_id INTEGER NULL, 
	pre_decision_at DATETIME NULL, 
	pre_decision_by_id INTEGER NULL, 
	pou_score_summary TEXT NULL, 
	pou_score_entries TEXT NULL, 
	pou_score_reasons TEXT NULL, 
	pou_decision_document_path VARCHAR(500) NULL, 
	pou_decision_document_name VARCHAR(255) NULL, 
	evaluation_results_file_path VARCHAR(500) NULL, 
	evaluation_results_filename VARCHAR(255) NULL, 
	ao_decision_at DATETIME NULL, 
	ao_decision_by_id INTEGER NULL, 
	ao_decision_reason TEXT NULL, 
	ao_final_choice_summary TEXT NULL, 
	ao_decision_document_path VARCHAR(500) NULL, 
	ao_decision_document_name VARCHAR(255) NULL, 
	created_by_id INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (procurement_id), 
	FOREIGN KEY(procurement_id) REFERENCES procurements (id), 
	FOREIGN KEY(winning_bidder_id) REFERENCES bidders (id), 
	FOREIGN KEY(published_by_id) REFERENCES users (id), 
	FOREIGN KEY(pre_decision_by_id) REFERENCES users (id), 
	FOREIGN KEY(ao_decision_by_id) REFERENCES users (id), 
	FOREIGN KEY(created_by_id) REFERENCES users (id)
)

;
GO


CREATE TABLE bidder_payments (
	id INTEGER NOT NULL IDENTITY, 
	procurement_id INTEGER NOT NULL, 
	bidder_id INTEGER NOT NULL, 
	submitted_by_id INTEGER NOT NULL, 
	payment_reference VARCHAR(100) NOT NULL, 
	amount NUMERIC(15, 2) NOT NULL, 
	proof_file_path VARCHAR(500) NOT NULL, 
	proof_filename VARCHAR(300) NOT NULL, 
	supporting_document_path VARCHAR(500) NULL, 
	supporting_document_filename VARCHAR(300) NULL, 
	status VARCHAR(30) NOT NULL, 
	notes TEXT NULL, 
	submitted_at DATETIME NOT NULL, 
	reviewed_by_id INTEGER NULL, 
	reviewed_at DATETIME NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(procurement_id) REFERENCES procurements (id), 
	FOREIGN KEY(bidder_id) REFERENCES bidders (id), 
	FOREIGN KEY(submitted_by_id) REFERENCES users (id), 
	FOREIGN KEY(reviewed_by_id) REFERENCES users (id)
)

;
GO


CREATE TABLE bidder_performance (
	id INTEGER NOT NULL IDENTITY, 
	procurement_id INTEGER NOT NULL, 
	bidder_id INTEGER NOT NULL, 
	delivery_score INTEGER NOT NULL, 
	quality_score INTEGER NOT NULL, 
	compliance_score INTEGER NOT NULL, 
	overall_score NUMERIC(5, 2) NOT NULL, 
	status VARCHAR(30) NOT NULL, 
	notes TEXT NULL, 
	reviewed_by_id INTEGER NOT NULL, 
	reviewed_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(procurement_id) REFERENCES procurements (id), 
	FOREIGN KEY(bidder_id) REFERENCES bidders (id), 
	FOREIGN KEY(reviewed_by_id) REFERENCES users (id)
)

;
GO


CREATE TABLE budget_entries (
	id INTEGER NOT NULL IDENTITY, 
	procurement_id INTEGER NOT NULL, 
	entry_type VARCHAR(30) NOT NULL, 
	description VARCHAR(300) NOT NULL, 
	amount NUMERIC(15, 2) NOT NULL, 
	reference VARCHAR(100) NULL, 
	entry_date DATETIME NOT NULL, 
	created_by_id INTEGER NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(procurement_id) REFERENCES procurements (id), 
	FOREIGN KEY(created_by_id) REFERENCES users (id)
)

;
GO


CREATE TABLE committee_members (
	id INTEGER NOT NULL IDENTITY, 
	procurement_id INTEGER NOT NULL, 
	user_id INTEGER NOT NULL, 
	appointment_instrument_ref VARCHAR(100) NOT NULL, 
	appointment_date DATETIME NOT NULL, 
	role VARCHAR(30) NOT NULL, 
	is_voting_member BIT NULL, 
	skills TEXT NULL, 
	conflict_of_interest_declared BIT NULL, 
	conflict_of_interest_details TEXT NULL, 
	confidentiality_signed BIT NULL, 
	confidentiality_signed_at DATETIME NULL, 
	access_granted BIT NULL, 
	access_granted_at DATETIME NULL, 
	access_revoked_at DATETIME NULL, 
	access_valid_from DATETIME NULL, 
	access_valid_until DATETIME NULL, 
	created_at DATETIME NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(procurement_id) REFERENCES procurements (id), 
	FOREIGN KEY(user_id) REFERENCES users (id)
)

;
GO


CREATE TABLE communications (
	id INTEGER NOT NULL IDENTITY, 
	procurement_id INTEGER NOT NULL, 
	type VARCHAR(20) NOT NULL, 
	content TEXT NOT NULL, 
	file_path VARCHAR(500) NULL, 
	original_filename VARCHAR(255) NULL, 
	from_user_id INTEGER NULL, 
	from_bidder_id INTEGER NULL, 
	is_public BIT NULL, 
	visibility_type VARCHAR(20) NULL, 
	created_at DATETIME NULL, 
	updated_at DATETIME NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(procurement_id) REFERENCES procurements (id), 
	FOREIGN KEY(from_user_id) REFERENCES users (id), 
	FOREIGN KEY(from_bidder_id) REFERENCES bidders (id)
)

;
GO


CREATE TABLE complaints (
	id INTEGER NOT NULL IDENTITY, 
	procurement_id INTEGER NOT NULL, 
	bidder_id INTEGER NOT NULL, 
	grounds TEXT NOT NULL, 
	relief_sought TEXT NULL, 
	status VARCHAR(20) NULL, 
	decision TEXT NULL, 
	created_at DATETIME NULL, 
	resolved_at DATETIME NULL, 
	resolved_by_id INTEGER NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(procurement_id) REFERENCES procurements (id), 
	FOREIGN KEY(bidder_id) REFERENCES bidders (id), 
	FOREIGN KEY(resolved_by_id) REFERENCES users (id)
)

;
GO


CREATE TABLE evaluator_assignments (
	id INTEGER NOT NULL IDENTITY, 
	procurement_id INTEGER NOT NULL, 
	evaluator_id INTEGER NOT NULL, 
	document_scope VARCHAR(20) NOT NULL, 
	assigned_by_id INTEGER NOT NULL, 
	assigned_at DATETIME NOT NULL, 
	updated_at DATETIME NULL, 
	status VARCHAR(20) NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_evaluator_assignment_proc_eval UNIQUE (procurement_id, evaluator_id), 
	FOREIGN KEY(procurement_id) REFERENCES procurements (id), 
	FOREIGN KEY(evaluator_id) REFERENCES users (id), 
	FOREIGN KEY(assigned_by_id) REFERENCES users (id)
)

;
GO


CREATE TABLE evaluator_feedback (
	id INTEGER NOT NULL IDENTITY, 
	procurement_id INTEGER NOT NULL, 
	evaluator_id INTEGER NOT NULL, 
	feedback_text TEXT NULL, 
	file_path VARCHAR(500) NOT NULL, 
	original_filename VARCHAR(300) NOT NULL, 
	submitted_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(procurement_id) REFERENCES procurements (id), 
	FOREIGN KEY(evaluator_id) REFERENCES users (id)
)

;
GO


CREATE TABLE form_d_requests (
	id INTEGER NOT NULL IDENTITY, 
	requester_id INTEGER NOT NULL, 
	status VARCHAR(30) NULL, 
	requisition_title VARCHAR(200) NOT NULL, 
	category VARCHAR(30) NOT NULL, 
	procurement_method VARCHAR(30) NOT NULL, 
	estimated_value NUMERIC(15, 2) NOT NULL, 
	procurement_entity VARCHAR(200) NULL, 
	justification TEXT NULL, 
	delivery_period VARCHAR(100) NULL, 
	authorized_by VARCHAR(150) NULL, 
	authorization_date DATETIME NULL, 
	submitted_form_path VARCHAR(500) NULL, 
	submitted_form_filename VARCHAR(300) NULL, 
	procurement_id INTEGER NULL, 
	submitted_by_id INTEGER NULL, 
	under_review_by_id INTEGER NULL, 
	under_review_at DATETIME NULL, 
	converted_by_id INTEGER NULL, 
	converted_at DATETIME NULL, 
	rejected_by_id INTEGER NULL, 
	rejected_at DATETIME NULL, 
	rejection_reason TEXT NULL, 
	created_at DATETIME NULL, 
	updated_at DATETIME NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(requester_id) REFERENCES users (id), 
	FOREIGN KEY(procurement_id) REFERENCES procurements (id), 
	FOREIGN KEY(submitted_by_id) REFERENCES users (id), 
	FOREIGN KEY(under_review_by_id) REFERENCES users (id), 
	FOREIGN KEY(converted_by_id) REFERENCES users (id), 
	FOREIGN KEY(rejected_by_id) REFERENCES users (id)
)

;
GO


CREATE TABLE form_de_requests (
	id INTEGER NOT NULL IDENTITY, 
	requester_id INTEGER NOT NULL, 
	status VARCHAR(30) NULL, 
	department VARCHAR(200) NULL, 
	justification TEXT NULL, 
	form_d_file_path VARCHAR(500) NULL, 
	form_d_filename VARCHAR(300) NULL, 
	form_e_file_path VARCHAR(500) NULL, 
	form_e_filename VARCHAR(300) NULL, 
	procurement_id INTEGER NULL, 
	submitted_by_id INTEGER NULL, 
	under_review_by_id INTEGER NULL, 
	under_review_at DATETIME NULL, 
	converted_by_id INTEGER NULL, 
	converted_at DATETIME NULL, 
	rejected_by_id INTEGER NULL, 
	rejected_at DATETIME NULL, 
	rejection_reason TEXT NULL, 
	created_at DATETIME NULL, 
	updated_at DATETIME NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(requester_id) REFERENCES users (id), 
	FOREIGN KEY(procurement_id) REFERENCES procurements (id), 
	FOREIGN KEY(submitted_by_id) REFERENCES users (id), 
	FOREIGN KEY(under_review_by_id) REFERENCES users (id), 
	FOREIGN KEY(converted_by_id) REFERENCES users (id), 
	FOREIGN KEY(rejected_by_id) REFERENCES users (id)
)

;
GO


CREATE TABLE form_e_requests (
	id INTEGER NOT NULL IDENTITY, 
	requester_id INTEGER NOT NULL, 
	status VARCHAR(30) NULL, 
	specification_title VARCHAR(200) NOT NULL, 
	category VARCHAR(30) NOT NULL, 
	technical_specification TEXT NOT NULL, 
	budget_line VARCHAR(100) NULL, 
	budget_allocated NUMERIC(15, 2) NOT NULL, 
	budget_status VARCHAR(30) NULL, 
	procurement_entity VARCHAR(200) NULL, 
	clearance_authority VARCHAR(150) NULL, 
	clearance_date DATETIME NULL, 
	submitted_form_path VARCHAR(500) NULL, 
	submitted_form_filename VARCHAR(300) NULL, 
	procurement_id INTEGER NULL, 
	submitted_by_id INTEGER NULL, 
	under_review_by_id INTEGER NULL, 
	under_review_at DATETIME NULL, 
	converted_by_id INTEGER NULL, 
	converted_at DATETIME NULL, 
	rejected_by_id INTEGER NULL, 
	rejected_at DATETIME NULL, 
	rejection_reason TEXT NULL, 
	created_at DATETIME NULL, 
	updated_at DATETIME NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(requester_id) REFERENCES users (id), 
	FOREIGN KEY(procurement_id) REFERENCES procurements (id), 
	FOREIGN KEY(submitted_by_id) REFERENCES users (id), 
	FOREIGN KEY(under_review_by_id) REFERENCES users (id), 
	FOREIGN KEY(converted_by_id) REFERENCES users (id), 
	FOREIGN KEY(rejected_by_id) REFERENCES users (id)
)

;
GO


CREATE TABLE lots (
	id INTEGER NOT NULL IDENTITY, 
	procurement_id INTEGER NOT NULL, 
	lot_number VARCHAR(20) NOT NULL, 
	description TEXT NULL, 
	estimated_value NUMERIC(15, 2) NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(procurement_id) REFERENCES procurements (id)
)

;
GO


CREATE TABLE notifications (
	id INTEGER NOT NULL IDENTITY, 
	user_id INTEGER NOT NULL, 
	sender_id INTEGER NULL, 
	type VARCHAR(30) NOT NULL, 
	title VARCHAR(200) NOT NULL, 
	body TEXT NOT NULL, 
	procurement_id INTEGER NULL, 
	reply_to INTEGER NULL, 
	is_read BIT NULL, 
	emailed_at DATETIME NULL, 
	created_at DATETIME NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id), 
	FOREIGN KEY(sender_id) REFERENCES users (id), 
	FOREIGN KEY(procurement_id) REFERENCES procurements (id), 
	FOREIGN KEY(reply_to) REFERENCES notifications (id)
)

;
GO


CREATE TABLE procurement_histories (
	id INTEGER NOT NULL IDENTITY, 
	procurement_id INTEGER NOT NULL, 
	action VARCHAR(50) NOT NULL, 
	previous_status VARCHAR(30) NULL, 
	new_status VARCHAR(30) NULL, 
	reason TEXT NULL, 
	restored_from_history_id INTEGER NULL, 
	performed_by_id INTEGER NOT NULL, 
	performed_at DATETIME NULL, 
	requires_approval BIT NULL, 
	approved_by_id INTEGER NULL, 
	approved_at DATETIME NULL, 
	affected_submission_deadline DATETIME NULL, 
	affected_opening_date DATETIME NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(procurement_id) REFERENCES procurements (id), 
	FOREIGN KEY(restored_from_history_id) REFERENCES procurement_histories (id), 
	FOREIGN KEY(performed_by_id) REFERENCES users (id), 
	FOREIGN KEY(approved_by_id) REFERENCES users (id)
)

;
GO


CREATE TABLE procurement_shares (
	id INTEGER NOT NULL IDENTITY, 
	procurement_id INTEGER NOT NULL, 
	recipient_id INTEGER NOT NULL, 
	shared_by_id INTEGER NOT NULL, 
	folder_name VARCHAR(120) NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	shared_at DATETIME NOT NULL, 
	revoked_at DATETIME NULL, 
	revoked_by_id INTEGER NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_procurement_share_recipient UNIQUE (procurement_id, recipient_id), 
	FOREIGN KEY(procurement_id) REFERENCES procurements (id), 
	FOREIGN KEY(recipient_id) REFERENCES users (id), 
	FOREIGN KEY(shared_by_id) REFERENCES users (id), 
	FOREIGN KEY(revoked_by_id) REFERENCES users (id)
)

;
GO


CREATE TABLE submissions (
	id INTEGER NOT NULL IDENTITY, 
	procurement_id INTEGER NOT NULL, 
	bidder_id INTEGER NOT NULL, 
	envelope_type VARCHAR(10) NOT NULL, 
	file_path VARCHAR(500) NULL, 
	original_filename VARCHAR(300) NULL, 
	sha256_hash VARCHAR(64) NULL, 
	file_size_bytes INTEGER NULL, 
	compliance_document_path VARCHAR(500) NULL, 
	compliance_document_filename VARCHAR(300) NULL, 
	compliance_document_hash VARCHAR(64) NULL, 
	returnable_document_path VARCHAR(500) NULL, 
	returnable_document_filename VARCHAR(300) NULL, 
	returnable_document_hash VARCHAR(64) NULL, 
	version INTEGER NULL, 
	status VARCHAR(20) NULL, 
	submitted_by_id INTEGER NOT NULL, 
	submitted_at DATETIME NULL, 
	receipt_code VARCHAR(40) NULL, 
	declaration_accepted BIT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(procurement_id) REFERENCES procurements (id), 
	FOREIGN KEY(bidder_id) REFERENCES bidders (id), 
	FOREIGN KEY(submitted_by_id) REFERENCES users (id), 
	UNIQUE (receipt_code)
)

;
GO


CREATE TABLE bidder_document_accesses (
	id INTEGER NOT NULL IDENTITY, 
	procurement_id INTEGER NOT NULL, 
	bidder_id INTEGER NOT NULL, 
	document_type VARCHAR(30) NOT NULL, 
	payment_id INTEGER NULL, 
	status VARCHAR(20) NOT NULL, 
	granted_by_id INTEGER NOT NULL, 
	granted_at DATETIME NOT NULL, 
	revoked_by_id INTEGER NULL, 
	revoked_at DATETIME NULL, 
	revocation_reason TEXT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(procurement_id) REFERENCES procurements (id), 
	FOREIGN KEY(bidder_id) REFERENCES bidders (id), 
	FOREIGN KEY(payment_id) REFERENCES bidder_payments (id), 
	FOREIGN KEY(granted_by_id) REFERENCES users (id), 
	FOREIGN KEY(revoked_by_id) REFERENCES users (id)
)

;
GO


CREATE TABLE clarification_accesses (
	id INTEGER NOT NULL IDENTITY, 
	communication_id INTEGER NOT NULL, 
	bidder_id INTEGER NOT NULL, 
	accessed_by_user_id INTEGER NOT NULL, 
	access_type VARCHAR(30) NOT NULL, 
	ip_address VARCHAR(45) NULL, 
	accessed_at DATETIME NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(communication_id) REFERENCES communications (id), 
	FOREIGN KEY(bidder_id) REFERENCES bidders (id), 
	FOREIGN KEY(accessed_by_user_id) REFERENCES users (id)
)

;
GO


CREATE TABLE clarification_visibilities (
	id INTEGER NOT NULL IDENTITY, 
	communication_id INTEGER NOT NULL, 
	bidder_id INTEGER NOT NULL, 
	granted_by_id INTEGER NOT NULL, 
	granted_at DATETIME NULL, 
	revoked_by_id INTEGER NULL, 
	revoked_at DATETIME NULL, 
	revocation_reason TEXT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(communication_id) REFERENCES communications (id), 
	FOREIGN KEY(bidder_id) REFERENCES bidders (id), 
	FOREIGN KEY(granted_by_id) REFERENCES users (id), 
	FOREIGN KEY(revoked_by_id) REFERENCES users (id)
)

;
GO


CREATE TABLE evaluation_criteria (
	id INTEGER NOT NULL IDENTITY, 
	procurement_id INTEGER NOT NULL, 
	lot_id INTEGER NULL, 
	criteria_type VARCHAR(20) NOT NULL, 
	name VARCHAR(200) NOT NULL, 
	description TEXT NULL, 
	weight NUMERIC(5, 2) NULL, 
	max_score NUMERIC(5, 2) NULL, 
	min_qualifying_mark NUMERIC(5, 2) NULL, 
	scoring_method VARCHAR(20) NULL, 
	is_mandatory BIT NULL, 
	locked BIT NULL, 
	locked_at DATETIME NULL, 
	locked_by INTEGER NULL, 
	sequence INTEGER NULL, 
	created_at DATETIME NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(procurement_id) REFERENCES procurements (id), 
	FOREIGN KEY(lot_id) REFERENCES lots (id), 
	FOREIGN KEY(locked_by) REFERENCES users (id)
)

;
GO


CREATE TABLE evaluations (
	id INTEGER NOT NULL IDENTITY, 
	procurement_id INTEGER NOT NULL, 
	lot_id INTEGER NULL, 
	bidder_id INTEGER NOT NULL, 
	evaluator_id INTEGER NOT NULL, 
	evaluation_stage VARCHAR(30) NOT NULL, 
	score NUMERIC(5, 2) NULL, 
	comments TEXT NULL, 
	evidence_references TEXT NULL, 
	is_consensus BIT NULL, 
	consensus_reached BIT NULL, 
	consensus_score NUMERIC(5, 2) NULL, 
	consensus_comments TEXT NULL, 
	passed BIT NULL, 
	eliminated BIT NULL, 
	elimination_reason TEXT NULL, 
	approved_by INTEGER NULL, 
	approved_at DATETIME NULL, 
	created_at DATETIME NULL, 
	updated_at DATETIME NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(procurement_id) REFERENCES procurements (id), 
	FOREIGN KEY(lot_id) REFERENCES lots (id), 
	FOREIGN KEY(bidder_id) REFERENCES bidders (id), 
	FOREIGN KEY(evaluator_id) REFERENCES users (id), 
	FOREIGN KEY(approved_by) REFERENCES users (id)
)

;
GO


CREATE TABLE messages (
	id INTEGER NOT NULL IDENTITY, 
	sender_id INTEGER NOT NULL, 
	subject VARCHAR(200) NOT NULL, 
	body TEXT NOT NULL, 
	message_type VARCHAR(20) NOT NULL, 
	procurement_id INTEGER NULL, 
	communication_id INTEGER NULL, 
	attachment_path VARCHAR(500) NULL, 
	attachment_filename VARCHAR(255) NULL, 
	reply_to_id INTEGER NULL, 
	thread_id INTEGER NULL, 
	created_at DATETIME NULL, 
	updated_at DATETIME NULL, 
	unsent_at DATETIME NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(sender_id) REFERENCES users (id), 
	FOREIGN KEY(procurement_id) REFERENCES procurements (id), 
	FOREIGN KEY(communication_id) REFERENCES communications (id), 
	FOREIGN KEY(reply_to_id) REFERENCES messages (id), 
	FOREIGN KEY(thread_id) REFERENCES messages (id)
)

;
GO


CREATE TABLE submission_histories (
	id INTEGER NOT NULL IDENTITY, 
	submission_id INTEGER NOT NULL, 
	action VARCHAR(50) NOT NULL, 
	previous_status VARCHAR(20) NULL, 
	new_status VARCHAR(20) NULL, 
	reason TEXT NULL, 
	performed_by_id INTEGER NOT NULL, 
	performed_at DATETIME NULL, 
	replaced_submission_id INTEGER NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(submission_id) REFERENCES submissions (id), 
	FOREIGN KEY(performed_by_id) REFERENCES users (id), 
	FOREIGN KEY(replaced_submission_id) REFERENCES submissions (id)
)

;
GO


CREATE TABLE message_attachments (
	id INTEGER NOT NULL IDENTITY, 
	message_id INTEGER NOT NULL, 
	filename VARCHAR(255) NOT NULL, 
	stored_name VARCHAR(255) NOT NULL, 
	file_type VARCHAR(100) NOT NULL, 
	file_size INTEGER NOT NULL, 
	storage_path VARCHAR(500) NOT NULL, 
	created_at DATETIME NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(message_id) REFERENCES messages (id)
)

;
GO


CREATE TABLE message_recipients (
	id INTEGER NOT NULL IDENTITY, 
	message_id INTEGER NOT NULL, 
	user_id INTEGER NULL, 
	bidder_id INTEGER NULL, 
	role_id INTEGER NULL, 
	delivered_at DATETIME NULL, 
	read_at DATETIME NULL, 
	archived_at DATETIME NULL, 
	created_at DATETIME NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(message_id) REFERENCES messages (id), 
	FOREIGN KEY(user_id) REFERENCES users (id), 
	FOREIGN KEY(bidder_id) REFERENCES bidders (id), 
	FOREIGN KEY(role_id) REFERENCES roles (id)
)

;
GO


CREATE TABLE score_sheets (
	id INTEGER NOT NULL IDENTITY, 
	evaluation_id INTEGER NOT NULL, 
	criteria_id INTEGER NOT NULL, 
	score NUMERIC(5, 2) NULL, 
	max_score NUMERIC(5, 2) NULL, 
	weight NUMERIC(5, 2) NULL, 
	weighted_score NUMERIC(5, 2) NULL, 
	comments TEXT NULL, 
	evidence_reference TEXT NULL, 
	created_at DATETIME NULL, 
	updated_at DATETIME NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(evaluation_id) REFERENCES evaluations (id), 
	FOREIGN KEY(criteria_id) REFERENCES evaluation_criteria (id)
)

;
GO

CREATE UNIQUE INDEX uq_bidders_ppra_registration_number ON bidders (ppra_registration_number) WHERE [ppra_registration_number] IS NOT NULL;
GO

CREATE INDEX ix_bidders_ppra_registration_number ON bidders (ppra_registration_number);
GO

CREATE UNIQUE INDEX ix_roles_code ON roles (code);
GO

CREATE UNIQUE INDEX ix_site_settings_key ON site_settings ([key]);
GO

CREATE INDEX ix_users_email_confirmation_token ON users (email_confirmation_token);
GO

CREATE UNIQUE INDEX ix_users_email ON users (email);
GO

CREATE UNIQUE INDEX ix_users_username ON users (username);
GO

CREATE INDEX ix_audit_logs_created_at ON audit_logs (created_at);
GO

CREATE INDEX ix_bidder_compliance_documents_bidder_id ON bidder_compliance_documents (bidder_id);
GO

CREATE INDEX ix_bidder_compliance_documents_document_type ON bidder_compliance_documents (document_type);
GO

CREATE INDEX ix_bidder_compliance_documents_status ON bidder_compliance_documents (status);
GO

CREATE INDEX ix_document_versions_is_current ON document_versions (is_current);
GO

CREATE INDEX ix_document_versions_created_at ON document_versions (created_at);
GO

CREATE INDEX ix_document_versions_entity_type ON document_versions (entity_type);
GO

CREATE INDEX ix_document_versions_document_type ON document_versions (document_type);
GO

CREATE INDEX ix_document_versions_entity_id ON document_versions (entity_id);
GO

CREATE INDEX ix_procurement_plan_items_financial_year ON procurement_plan_items (financial_year);
GO

CREATE INDEX ix_procurement_plan_items_status ON procurement_plan_items (status);
GO

CREATE UNIQUE INDEX ix_procurements_tender_number ON procurements (tender_number);
GO

CREATE INDEX ix_procurements_status ON procurements (status);
GO

CREATE INDEX ix_bidder_payments_status ON bidder_payments (status);
GO

CREATE INDEX ix_bidder_payments_bidder_id ON bidder_payments (bidder_id);
GO

CREATE INDEX ix_bidder_payments_submitted_at ON bidder_payments (submitted_at);
GO

CREATE INDEX ix_bidder_payments_procurement_id ON bidder_payments (procurement_id);
GO

CREATE INDEX ix_bidder_performance_bidder_id ON bidder_performance (bidder_id);
GO

CREATE INDEX ix_bidder_performance_procurement_id ON bidder_performance (procurement_id);
GO

CREATE INDEX ix_budget_entries_procurement_id ON budget_entries (procurement_id);
GO

CREATE INDEX ix_evaluator_assignments_assigned_at ON evaluator_assignments (assigned_at);
GO

CREATE INDEX ix_evaluator_assignments_document_scope ON evaluator_assignments (document_scope);
GO

CREATE INDEX ix_evaluator_assignments_procurement_id ON evaluator_assignments (procurement_id);
GO

CREATE INDEX ix_evaluator_assignments_evaluator_id ON evaluator_assignments (evaluator_id);
GO

CREATE INDEX ix_evaluator_assignments_status ON evaluator_assignments (status);
GO

CREATE INDEX ix_evaluator_feedback_evaluator_id ON evaluator_feedback (evaluator_id);
GO

CREATE INDEX ix_evaluator_feedback_submitted_at ON evaluator_feedback (submitted_at);
GO

CREATE INDEX ix_evaluator_feedback_procurement_id ON evaluator_feedback (procurement_id);
GO

CREATE INDEX ix_form_d_requests_status ON form_d_requests (status);
GO

CREATE INDEX ix_form_d_requests_created_at ON form_d_requests (created_at);
GO

CREATE INDEX ix_form_d_requests_requester_id ON form_d_requests (requester_id);
GO

CREATE INDEX ix_form_d_requests_procurement_id ON form_d_requests (procurement_id);
GO

CREATE INDEX ix_form_de_requests_requester_id ON form_de_requests (requester_id);
GO

CREATE INDEX ix_form_de_requests_procurement_id ON form_de_requests (procurement_id);
GO

CREATE INDEX ix_form_de_requests_created_at ON form_de_requests (created_at);
GO

CREATE INDEX ix_form_de_requests_status ON form_de_requests (status);
GO

CREATE INDEX ix_form_e_requests_requester_id ON form_e_requests (requester_id);
GO

CREATE INDEX ix_form_e_requests_created_at ON form_e_requests (created_at);
GO

CREATE INDEX ix_form_e_requests_status ON form_e_requests (status);
GO

CREATE INDEX ix_form_e_requests_procurement_id ON form_e_requests (procurement_id);
GO

CREATE INDEX ix_notifications_created_at ON notifications (created_at);
GO

CREATE INDEX ix_procurement_histories_procurement_id ON procurement_histories (procurement_id);
GO

CREATE INDEX ix_procurement_histories_performed_at ON procurement_histories (performed_at);
GO

CREATE INDEX ix_procurement_shares_recipient_id ON procurement_shares (recipient_id);
GO

CREATE INDEX ix_procurement_shares_status ON procurement_shares (status);
GO

CREATE INDEX ix_procurement_shares_procurement_id ON procurement_shares (procurement_id);
GO

CREATE INDEX ix_bidder_document_accesses_procurement_id ON bidder_document_accesses (procurement_id);
GO

CREATE INDEX ix_bidder_document_accesses_status ON bidder_document_accesses (status);
GO

CREATE INDEX ix_bidder_document_accesses_bidder_id ON bidder_document_accesses (bidder_id);
GO

CREATE INDEX ix_clarification_accesses_bidder_id ON clarification_accesses (bidder_id);
GO

CREATE INDEX ix_clarification_accesses_communication_id ON clarification_accesses (communication_id);
GO

CREATE INDEX ix_clarification_accesses_accessed_at ON clarification_accesses (accessed_at);
GO

CREATE INDEX ix_clarification_visibilities_communication_id ON clarification_visibilities (communication_id);
GO

CREATE INDEX ix_clarification_visibilities_bidder_id ON clarification_visibilities (bidder_id);
GO

CREATE INDEX ix_messages_unsent_at ON messages (unsent_at);
GO

CREATE INDEX ix_messages_created_at ON messages (created_at);
GO

CREATE INDEX ix_messages_thread_id ON messages (thread_id);
GO

CREATE INDEX ix_submission_histories_performed_at ON submission_histories (performed_at);
GO

CREATE INDEX ix_submission_histories_submission_id ON submission_histories (submission_id);
GO

CREATE INDEX ix_message_attachments_message_id ON message_attachments (message_id);
GO

CREATE INDEX ix_message_recipients_message_id ON message_recipients (message_id);
GO

CREATE INDEX ix_message_recipients_read_at ON message_recipients (read_at);
GO
