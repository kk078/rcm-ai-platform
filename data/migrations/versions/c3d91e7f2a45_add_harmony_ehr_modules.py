"""Add harmony & EHR modules: eligibility, prior_auth, patient_statements,
document_attachments, notification_rules, notification_log, ai_coding_feedback,
ehr_connections, ehr_sync_log

Revision ID: c3d91e7f2a45
Revises: a2f84c901e12
Create Date: 2026-05-19 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'c3d91e7f2a45'
down_revision = 'a2f84c901e12'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── eligibility_checks ────────────────────────────────────────────────────
    op.create_table(
        'eligibility_checks',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('practice_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('practices.id'), nullable=False),
        sa.Column('patient_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('patients.id'), nullable=False),
        sa.Column('coverage_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('coverages.id'), nullable=True),
        sa.Column('charge_batch_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('charge_batches.id'), nullable=True),
        sa.Column('payer_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('payers.id'), nullable=True),
        sa.Column('check_date', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.Column('service_date', sa.Date(), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='pending'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('deductible_total', sa.Numeric(10, 2), nullable=True),
        sa.Column('deductible_met', sa.Numeric(10, 2), nullable=True),
        sa.Column('oop_total', sa.Numeric(10, 2), nullable=True),
        sa.Column('oop_met', sa.Numeric(10, 2), nullable=True),
        sa.Column('copay', sa.Numeric(10, 2), nullable=True),
        sa.Column('coinsurance_pct', sa.Integer(), nullable=True),
        sa.Column('network_status', sa.String(20), nullable=True),
        sa.Column('plan_name', sa.String(200), nullable=True),
        sa.Column('group_number', sa.String(100), nullable=True),
        sa.Column('raw_response', postgresql.JSONB(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('checked_by_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), onupdate=sa.text('now()'), nullable=False),
    )
    op.create_index('ix_eligibility_checks_practice_patient',
                    'eligibility_checks', ['practice_id', 'patient_id'])
    op.create_index('ix_eligibility_checks_check_date',
                    'eligibility_checks', ['check_date'])

    # ── prior_authorizations ──────────────────────────────────────────────────
    op.create_table(
        'prior_authorizations',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('practice_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('practices.id'), nullable=False),
        sa.Column('patient_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('patients.id'), nullable=False),
        sa.Column('coverage_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('coverages.id'), nullable=True),
        sa.Column('encounter_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('encounters.id'), nullable=True),
        sa.Column('claim_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('claims.id'), nullable=True),
        sa.Column('payer_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('payers.id'), nullable=True),
        sa.Column('auth_number', sa.String(100), nullable=True),
        sa.Column('procedure_codes', postgresql.ARRAY(sa.String(20)), nullable=True),
        sa.Column('diagnosis_codes', postgresql.ARRAY(sa.String(20)), nullable=True),
        sa.Column('status', sa.String(30), nullable=False, server_default='pending'),
        sa.Column('requested_date', sa.Date(), nullable=True),
        sa.Column('approved_date', sa.Date(), nullable=True),
        sa.Column('valid_from', sa.Date(), nullable=True),
        sa.Column('valid_to', sa.Date(), nullable=True),
        sa.Column('approved_units', sa.Integer(), nullable=True),
        sa.Column('approved_visits', sa.Integer(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('requested_by_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id'), nullable=True),
        sa.Column('denial_reason', sa.Text(), nullable=True),
        sa.Column('appeal_deadline', sa.Date(), nullable=True),
        sa.Column('metadata', postgresql.JSONB(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), onupdate=sa.text('now()'), nullable=False),
    )
    op.create_index('ix_prior_auth_practice_patient',
                    'prior_authorizations', ['practice_id', 'patient_id'])
    op.create_index('ix_prior_auth_status', 'prior_authorizations', ['status'])
    op.create_index('ix_prior_auth_valid_to', 'prior_authorizations', ['valid_to'])

    # ── patient_statements ────────────────────────────────────────────────────
    op.create_table(
        'patient_statements',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('practice_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('practices.id'), nullable=False),
        sa.Column('patient_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('patients.id'), nullable=False),
        sa.Column('statement_number', sa.String(50), nullable=False, unique=True),
        sa.Column('statement_date', sa.Date(), nullable=False),
        sa.Column('due_date', sa.Date(), nullable=True),
        sa.Column('total_charges', sa.Numeric(12, 2), nullable=False, server_default='0'),
        sa.Column('total_insurance_paid', sa.Numeric(12, 2), nullable=False, server_default='0'),
        sa.Column('total_adjustments', sa.Numeric(12, 2), nullable=False, server_default='0'),
        sa.Column('total_patient_paid', sa.Numeric(12, 2), nullable=False, server_default='0'),
        sa.Column('balance_due', sa.Numeric(12, 2), nullable=False, server_default='0'),
        sa.Column('status', sa.String(20), nullable=False, server_default='open'),
        sa.Column('delivery_method', sa.String(20), nullable=True),
        sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('paid_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('payment_reference', sa.String(100), nullable=True),
        sa.Column('line_items', postgresql.JSONB(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), onupdate=sa.text('now()'), nullable=False),
    )
    op.create_index('ix_patient_statements_practice_patient',
                    'patient_statements', ['practice_id', 'patient_id'])
    op.create_index('ix_patient_statements_status', 'patient_statements', ['status'])

    # ── document_attachments ──────────────────────────────────────────────────
    op.create_table(
        'document_attachments',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('practice_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('practices.id'), nullable=False),
        sa.Column('entity_type', sa.String(50), nullable=False),
        sa.Column('entity_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('file_name', sa.String(500), nullable=False),
        sa.Column('file_size', sa.Integer(), nullable=True),
        sa.Column('mime_type', sa.String(100), nullable=True),
        sa.Column('storage_key', sa.String(1000), nullable=False),
        sa.Column('storage_url', sa.String(2000), nullable=True),
        sa.Column('document_type', sa.String(50), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('uploaded_by_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id'), nullable=True),
        sa.Column('is_phi', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), onupdate=sa.text('now()'), nullable=False),
    )
    op.create_index('ix_document_attachments_entity',
                    'document_attachments', ['entity_type', 'entity_id'])
    op.create_index('ix_document_attachments_practice',
                    'document_attachments', ['practice_id'])

    # ── notification_rules ────────────────────────────────────────────────────
    op.create_table(
        'notification_rules',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('practice_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('practices.id'), nullable=True),
        sa.Column('event_type', sa.String(100), nullable=False),
        sa.Column('role_filter', postgresql.ARRAY(sa.String(50)), nullable=True),
        sa.Column('channels', postgresql.ARRAY(sa.String(20)), nullable=False),
        sa.Column('threshold_hours', sa.Integer(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('template_subject', sa.String(500), nullable=True),
        sa.Column('template_body', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), onupdate=sa.text('now()'), nullable=False),
    )

    # ── notification_log ──────────────────────────────────────────────────────
    op.create_table(
        'notification_log',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('practice_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('practices.id'), nullable=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id'), nullable=True),
        sa.Column('event_type', sa.String(100), nullable=False),
        sa.Column('channel', sa.String(20), nullable=False),
        sa.Column('recipient', sa.String(500), nullable=True),
        sa.Column('subject', sa.String(500), nullable=True),
        sa.Column('body', sa.Text(), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='sent'),
        sa.Column('entity_type', sa.String(50), nullable=True),
        sa.Column('entity_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('external_id', sa.String(200), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), onupdate=sa.text('now()'), nullable=False),
    )
    op.create_index('ix_notification_log_user_created',
                    'notification_log', ['user_id', 'created_at'])

    # ── ai_coding_feedback ────────────────────────────────────────────────────
    op.create_table(
        'ai_coding_feedback',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('practice_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('practices.id'), nullable=False),
        sa.Column('coding_session_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('coding_sessions.id'), nullable=False),
        sa.Column('encounter_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('encounters.id'), nullable=True),
        sa.Column('coder_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id'), nullable=False),
        sa.Column('ai_suggested_dx', postgresql.ARRAY(sa.String(20)), nullable=True),
        sa.Column('ai_suggested_cpt', postgresql.ARRAY(sa.String(20)), nullable=True),
        sa.Column('final_dx', postgresql.ARRAY(sa.String(20)), nullable=True),
        sa.Column('final_cpt', postgresql.ARRAY(sa.String(20)), nullable=True),
        sa.Column('dx_accepted', sa.Boolean(), nullable=True),
        sa.Column('cpt_accepted', sa.Boolean(), nullable=True),
        sa.Column('override_reason', sa.Text(), nullable=True),
        sa.Column('specialty', sa.String(100), nullable=True),
        sa.Column('ai_provider', sa.String(50), nullable=True),
        sa.Column('ai_model', sa.String(100), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), onupdate=sa.text('now()'), nullable=False),
    )
    op.create_index('ix_ai_coding_feedback_practice_specialty',
                    'ai_coding_feedback', ['practice_id', 'specialty'])
    op.create_index('ix_ai_coding_feedback_coder',
                    'ai_coding_feedback', ['coder_id'])

    # ── ehr_connections ───────────────────────────────────────────────────────
    op.create_table(
        'ehr_connections',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('practice_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('practices.id'), nullable=False, unique=True),
        sa.Column('ehr_type', sa.String(50), nullable=False),
        sa.Column('ehr_name', sa.String(200), nullable=True),
        sa.Column('base_url', sa.String(2000), nullable=True),
        sa.Column('client_id', sa.String(500), nullable=True),
        sa.Column('client_secret_enc', sa.Text(), nullable=True),
        sa.Column('access_token_enc', sa.Text(), nullable=True),
        sa.Column('refresh_token_enc', sa.Text(), nullable=True),
        sa.Column('token_expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('sftp_host', sa.String(500), nullable=True),
        sa.Column('sftp_port', sa.Integer(), nullable=True, server_default='22'),
        sa.Column('sftp_username', sa.String(200), nullable=True),
        sa.Column('sftp_password_enc', sa.Text(), nullable=True),
        sa.Column('sftp_path', sa.String(1000), nullable=True),
        sa.Column('webhook_secret', sa.String(500), nullable=True),
        sa.Column('fhir_patient_scope', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('fhir_coverage_scope', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('fhir_encounter_scope', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('last_sync_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_sync_status', sa.String(20), nullable=True),
        sa.Column('last_sync_count', sa.Integer(), nullable=True),
        sa.Column('config', postgresql.JSONB(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), onupdate=sa.text('now()'), nullable=False),
    )

    # ── ehr_sync_log ──────────────────────────────────────────────────────────
    op.create_table(
        'ehr_sync_log',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('ehr_connection_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('ehr_connections.id'), nullable=False),
        sa.Column('practice_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('practices.id'), nullable=False),
        sa.Column('sync_type', sa.String(50), nullable=False),
        sa.Column('trigger', sa.String(50), nullable=False),
        sa.Column('records_fetched', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('records_created', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('records_updated', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('records_skipped', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('records_errored', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('status', sa.String(20), nullable=False, server_default='running'),
        sa.Column('error_details', postgresql.JSONB(), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), onupdate=sa.text('now()'), nullable=False),
    )
    op.create_index('ix_ehr_sync_log_connection',
                    'ehr_sync_log', ['ehr_connection_id', 'started_at'])


def downgrade() -> None:
    op.drop_table('ehr_sync_log')
    op.drop_table('ehr_connections')
    op.drop_table('ai_coding_feedback')
    op.drop_table('notification_log')
    op.drop_table('notification_rules')
    op.drop_table('document_attachments')
    op.drop_table('patient_statements')
    op.drop_table('prior_authorizations')
    op.drop_table('eligibility_checks')
