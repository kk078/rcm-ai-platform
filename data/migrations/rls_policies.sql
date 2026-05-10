-- Row-Level Security Policies for MedClaim AI
-- Apply AFTER initial schema migration
-- All tenant-scoped tables use practice_id for isolation

-- ============================================
-- Step 1: Enable RLS on all tenant-scoped tables
-- ============================================

ALTER TABLE patients ENABLE ROW LEVEL SECURITY;
ALTER TABLE coverages ENABLE ROW LEVEL SECURITY;
ALTER TABLE encounters ENABLE ROW LEVEL SECURITY;
ALTER TABLE claims ENABLE ROW LEVEL SECURITY;
ALTER TABLE claim_lines ENABLE ROW LEVEL SECURITY;
ALTER TABLE claim_diagnoses ENABLE ROW LEVEL SECURITY;
ALTER TABLE claim_scrub_results ENABLE ROW LEVEL SECURITY;
ALTER TABLE coding_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE payment_batches ENABLE ROW LEVEL SECURITY;
ALTER TABLE payment_lines ENABLE ROW LEVEL SECURITY;
ALTER TABLE adjustments ENABLE ROW LEVEL SECURITY;
ALTER TABLE denials ENABLE ROW LEVEL SECURITY;
ALTER TABLE appeals ENABLE ROW LEVEL SECURITY;
ALTER TABLE charge_batches ENABLE ROW LEVEL SECURITY;
ALTER TABLE charge_entries ENABLE ROW LEVEL SECURITY;
ALTER TABLE portal_messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE portal_notifications ENABLE ROW LEVEL SECURITY;
ALTER TABLE staff_assignments ENABLE ROW LEVEL SECURITY;
ALTER TABLE work_queue_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE staff_productivity ENABLE ROW LEVEL SECURITY;
ALTER TABLE client_invoices ENABLE ROW LEVEL SECURITY;
ALTER TABLE practice_locations ENABLE ROW LEVEL SECURITY;
ALTER TABLE service_agreements ENABLE ROW LEVEL SECURITY;
ALTER TABLE payer_enrollments ENABLE ROW LEVEL SECURITY;

-- ============================================
-- Step 2: Create policies for each table
-- Each table gets two policies:
--   1. internal_access: Internal staff see rows for their assigned practices
--   2. provider_access: Provider portal users see only their own practice
-- ============================================

-- --- patients ---
CREATE POLICY patients_internal_access ON patients
    FOR ALL
    USING (
        practice_id IN (
            SELECT sa.practice_id FROM staff_assignments sa
            WHERE sa.user_id = current_setting('app.current_user_id')::UUID
        )
        OR current_setting('app.user_role') IN ('company_admin', 'qa_reviewer')
    );

CREATE POLICY patients_provider_access ON patients
    FOR ALL
    USING (practice_id = current_setting('app.current_practice_id')::UUID);

-- --- coverages ---
CREATE POLICY coverages_internal_access ON coverages
    FOR ALL
    USING (
        practice_id IN (
            SELECT sa.practice_id FROM staff_assignments sa
            WHERE sa.user_id = current_setting('app.current_user_id')::UUID
        )
        OR current_setting('app.user_role') IN ('company_admin', 'qa_reviewer')
    );

CREATE POLICY coverages_provider_access ON coverages
    FOR ALL
    USING (practice_id = current_setting('app.current_practice_id')::UUID);

-- --- encounters ---
CREATE POLICY encounters_internal_access ON encounters
    FOR ALL
    USING (
        practice_id IN (
            SELECT sa.practice_id FROM staff_assignments sa
            WHERE sa.user_id = current_setting('app.current_user_id')::UUID
        )
        OR current_setting('app.user_role') IN ('company_admin', 'qa_reviewer')
    );

CREATE POLICY encounters_provider_access ON encounters
    FOR ALL
    USING (practice_id = current_setting('app.current_practice_id')::UUID);

-- --- claims ---
CREATE POLICY claims_internal_access ON claims
    FOR ALL
    USING (
        practice_id IN (
            SELECT sa.practice_id FROM staff_assignments sa
            WHERE sa.user_id = current_setting('app.current_user_id')::UUID
        )
        OR current_setting('app.user_role') IN ('company_admin', 'qa_reviewer')
    );

CREATE POLICY claims_provider_access ON claims
    FOR ALL
    USING (practice_id = current_setting('app.current_practice_id')::UUID);

-- --- claim_lines ---
CREATE POLICY claim_lines_internal_access ON claim_lines
    FOR ALL
    USING (
        practice_id IN (
            SELECT sa.practice_id FROM staff_assignments sa
            WHERE sa.user_id = current_setting('app.current_user_id')::UUID
        )
        OR current_setting('app.user_role') IN ('company_admin', 'qa_reviewer')
    );

CREATE POLICY claim_lines_provider_access ON claim_lines
    FOR ALL
    USING (practice_id = current_setting('app.current_practice_id')::UUID);

-- --- claim_diagnoses ---
CREATE POLICY claim_diagnoses_internal_access ON claim_diagnoses
    FOR ALL
    USING (
        practice_id IN (
            SELECT sa.practice_id FROM staff_assignments sa
            WHERE sa.user_id = current_setting('app.current_user_id')::UUID
        )
        OR current_setting('app.user_role') IN ('company_admin', 'qa_reviewer')
    );

CREATE POLICY claim_diagnoses_provider_access ON claim_diagnoses
    FOR ALL
    USING (practice_id = current_setting('app.current_practice_id')::UUID);

-- --- claim_scrub_results ---
CREATE POLICY claim_scrub_results_internal_access ON claim_scrub_results
    FOR ALL
    USING (
        practice_id IN (
            SELECT sa.practice_id FROM staff_assignments sa
            WHERE sa.user_id = current_setting('app.current_user_id')::UUID
        )
        OR current_setting('app.user_role') IN ('company_admin', 'qa_reviewer')
    );

CREATE POLICY claim_scrub_results_provider_access ON claim_scrub_results
    FOR ALL
    USING (practice_id = current_setting('app.current_practice_id')::UUID);

-- --- coding_sessions ---
CREATE POLICY coding_sessions_internal_access ON coding_sessions
    FOR ALL
    USING (
        practice_id IN (
            SELECT sa.practice_id FROM staff_assignments sa
            WHERE sa.user_id = current_setting('app.current_user_id')::UUID
        )
        OR current_setting('app.user_role') IN ('company_admin', 'qa_reviewer')
    );

CREATE POLICY coding_sessions_provider_access ON coding_sessions
    FOR ALL
    USING (practice_id = current_setting('app.current_practice_id')::UUID);

-- --- payment_batches ---
CREATE POLICY payment_batches_internal_access ON payment_batches
    FOR ALL
    USING (
        practice_id IN (
            SELECT sa.practice_id FROM staff_assignments sa
            WHERE sa.user_id = current_setting('app.current_user_id')::UUID
        )
        OR current_setting('app.user_role') IN ('company_admin', 'qa_reviewer')
    );

CREATE POLICY payment_batches_provider_access ON payment_batches
    FOR ALL
    USING (practice_id = current_setting('app.current_practice_id')::UUID);

-- --- payment_lines ---
CREATE POLICY payment_lines_internal_access ON payment_lines
    FOR ALL
    USING (
        practice_id IN (
            SELECT sa.practice_id FROM staff_assignments sa
            WHERE sa.user_id = current_setting('app.current_user_id')::UUID
        )
        OR current_setting('app.user_role') IN ('company_admin', 'qa_reviewer')
    );

CREATE POLICY payment_lines_provider_access ON payment_lines
    FOR ALL
    USING (practice_id = current_setting('app.current_practice_id')::UUID);

-- --- adjustments ---
CREATE POLICY adjustments_internal_access ON adjustments
    FOR ALL
    USING (
        practice_id IN (
            SELECT sa.practice_id FROM staff_assignments sa
            WHERE sa.user_id = current_setting('app.current_user_id')::UUID
        )
        OR current_setting('app.user_role') IN ('company_admin', 'qa_reviewer')
    );

CREATE POLICY adjustments_provider_access ON adjustments
    FOR ALL
    USING (practice_id = current_setting('app.current_practice_id')::UUID);

-- --- denials ---
CREATE POLICY denials_internal_access ON denials
    FOR ALL
    USING (
        practice_id IN (
            SELECT sa.practice_id FROM staff_assignments sa
            WHERE sa.user_id = current_setting('app.current_user_id')::UUID
        )
        OR current_setting('app.user_role') IN ('company_admin', 'qa_reviewer')
    );

CREATE POLICY denials_provider_access ON denials
    FOR ALL
    USING (practice_id = current_setting('app.current_practice_id')::UUID);

-- --- appeals ---
CREATE POLICY appeals_internal_access ON appeals
    FOR ALL
    USING (
        practice_id IN (
            SELECT sa.practice_id FROM staff_assignments sa
            WHERE sa.user_id = current_setting('app.current_user_id')::UUID
        )
        OR current_setting('app.user_role') IN ('company_admin', 'qa_reviewer')
    );

CREATE POLICY appeals_provider_access ON appeals
    FOR ALL
    USING (practice_id = current_setting('app.current_practice_id')::UUID);

-- --- charge_batches ---
CREATE POLICY charge_batches_internal_access ON charge_batches
    FOR ALL
    USING (
        practice_id IN (
            SELECT sa.practice_id FROM staff_assignments sa
            WHERE sa.user_id = current_setting('app.current_user_id')::UUID
        )
        OR current_setting('app.user_role') IN ('company_admin', 'qa_reviewer')
    );

CREATE POLICY charge_batches_provider_access ON charge_batches
    FOR ALL
    USING (practice_id = current_setting('app.current_practice_id')::UUID);

-- --- charge_entries ---
CREATE POLICY charge_entries_internal_access ON charge_entries
    FOR ALL
    USING (
        practice_id IN (
            SELECT sa.practice_id FROM staff_assignments sa
            WHERE sa.user_id = current_setting('app.current_user_id')::UUID
        )
        OR current_setting('app.user_role') IN ('company_admin', 'qa_reviewer')
    );

CREATE POLICY charge_entries_provider_access ON charge_entries
    FOR ALL
    USING (practice_id = current_setting('app.current_practice_id')::UUID);

-- --- portal_messages ---
CREATE POLICY portal_messages_internal_access ON portal_messages
    FOR ALL
    USING (
        practice_id IN (
            SELECT sa.practice_id FROM staff_assignments sa
            WHERE sa.user_id = current_setting('app.current_user_id')::UUID
        )
        OR current_setting('app.user_role') IN ('company_admin', 'qa_reviewer')
    );

CREATE POLICY portal_messages_provider_access ON portal_messages
    FOR ALL
    USING (practice_id = current_setting('app.current_practice_id')::UUID);

-- --- portal_notifications ---
CREATE POLICY portal_notifications_internal_access ON portal_notifications
    FOR ALL
    USING (
        practice_id IN (
            SELECT sa.practice_id FROM staff_assignments sa
            WHERE sa.user_id = current_setting('app.current_user_id')::UUID
        )
        OR current_setting('app.user_role') IN ('company_admin', 'qa_reviewer')
    );

CREATE POLICY portal_notifications_provider_access ON portal_notifications
    FOR ALL
    USING (practice_id = current_setting('app.current_practice_id')::UUID);

-- --- staff_assignments ---
-- Internal staff: can see their own assignments + all assignments for their practices
-- Provider users: cannot see staff assignments (internal-only table)
CREATE POLICY staff_assignments_internal_access ON staff_assignments
    FOR ALL
    USING (
        practice_id IN (
            SELECT sa.practice_id FROM staff_assignments sa
            WHERE sa.user_id = current_setting('app.current_user_id')::UUID
        )
        OR current_setting('app.user_role') IN ('company_admin', 'qa_reviewer')
    );

-- No provider_access policy for staff_assignments — providers should never see this table

-- --- work_queue_items ---
CREATE POLICY work_queue_items_internal_access ON work_queue_items
    FOR ALL
    USING (
        practice_id IN (
            SELECT sa.practice_id FROM staff_assignments sa
            WHERE sa.user_id = current_setting('app.current_user_id')::UUID
        )
        OR current_setting('app.user_role') IN ('company_admin', 'qa_reviewer')
    );

CREATE POLICY work_queue_items_provider_access ON work_queue_items
    FOR SELECT
    USING (practice_id = current_setting('app.current_practice_id')::UUID);

-- --- staff_productivity ---
-- practice_id can be NULL for aggregate metrics
CREATE POLICY staff_productivity_internal_access ON staff_productivity
    FOR ALL
    USING (
        (practice_id IN (
            SELECT sa.practice_id FROM staff_assignments sa
            WHERE sa.user_id = current_setting('app.current_user_id')::UUID
        ) OR practice_id IS NULL)
        OR current_setting('app.user_role') IN ('company_admin', 'qa_reviewer')
    );

-- No provider_access policy for staff_productivity — providers should not see internal metrics

-- --- client_invoices ---
CREATE POLICY client_invoices_internal_access ON client_invoices
    FOR ALL
    USING (
        practice_id IN (
            SELECT sa.practice_id FROM staff_assignments sa
            WHERE sa.user_id = current_setting('app.current_user_id')::UUID
        )
        OR current_setting('app.user_role') IN ('company_admin', 'qa_reviewer')
    );

CREATE POLICY client_invoices_provider_access ON client_invoices
    FOR SELECT
    USING (practice_id = current_setting('app.current_practice_id')::UUID);

-- --- practice_locations ---
CREATE POLICY practice_locations_internal_access ON practice_locations
    FOR ALL
    USING (
        practice_id IN (
            SELECT sa.practice_id FROM staff_assignments sa
            WHERE sa.user_id = current_setting('app.current_user_id')::UUID
        )
        OR current_setting('app.user_role') IN ('company_admin', 'qa_reviewer')
    );

CREATE POLICY practice_locations_provider_access ON practice_locations
    FOR ALL
    USING (practice_id = current_setting('app.current_practice_id')::UUID);

-- --- service_agreements ---
CREATE POLICY service_agreements_internal_access ON service_agreements
    FOR ALL
    USING (
        practice_id IN (
            SELECT sa.practice_id FROM staff_assignments sa
            WHERE sa.user_id = current_setting('app.current_user_id')::UUID
        )
        OR current_setting('app.user_role') IN ('company_admin', 'qa_reviewer')
    );

CREATE POLICY service_agreements_provider_access ON service_agreements
    FOR SELECT
    USING (practice_id = current_setting('app.current_practice_id')::UUID);

-- --- payer_enrollments ---
CREATE POLICY payer_enrollments_internal_access ON payer_enrollments
    FOR ALL
    USING (
        practice_id IN (
            SELECT sa.practice_id FROM staff_assignments sa
            WHERE sa.user_id = current_setting('app.current_user_id')::UUID
        )
        OR current_setting('app.user_role') IN ('company_admin', 'qa_reviewer')
    );

CREATE POLICY payer_enrollments_provider_access ON payer_enrollments
    FOR SELECT
    USING (practice_id = current_setting('app.current_practice_id')::UUID);