# Data Model Additions — Multi-Tenant Third-Party Billing

> These tables are IN ADDITION to the existing DATA_MODEL.md tables.
> The critical change: every existing table (patients, encounters, claims, etc.)
> gets a `practice_id UUID NOT NULL REFERENCES practices(id)` column
> with Row-Level Security enabled.

---

## Multi-Tenancy Core

### practices (Your Clients)
```sql
CREATE TABLE practices (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    practice_name       VARCHAR(255) NOT NULL,
    legal_name          VARCHAR(255),
    tin                 VARCHAR(20) NOT NULL,                  -- Encrypted. Tax ID / EIN
    group_npi           VARCHAR(10),
    specialty_primary   VARCHAR(100),
    specialty_codes     VARCHAR(20)[],                         -- Taxonomy codes
    address_line_1      TEXT,
    address_line_2      TEXT,
    city                VARCHAR(100),
    state               VARCHAR(2),
    zip_code            VARCHAR(10),
    phone               VARCHAR(20),
    fax                 VARCHAR(20),
    email               VARCHAR(255),
    website             VARCHAR(500),
    contact_name        VARCHAR(200),                          -- Primary billing contact at practice
    contact_phone       VARCHAR(20),
    contact_email       VARCHAR(255),

    -- Onboarding
    status              VARCHAR(20) DEFAULT 'onboarding',      -- onboarding, active, suspended, terminated
    onboarded_at        TIMESTAMPTZ,
    go_live_date        DATE,
    terminated_at       TIMESTAMPTZ,
    termination_reason  TEXT,

    -- Configuration
    timezone            VARCHAR(50) DEFAULT 'America/New_York',
    intake_method       VARCHAR(20) DEFAULT 'portal',          -- portal, upload, ehr, batch
    default_clearinghouse VARCHAR(100),

    -- Metadata
    notes               TEXT,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW(),
    created_by          UUID REFERENCES users(id)
);

CREATE INDEX idx_practices_status ON practices(status);
CREATE INDEX idx_practices_tin ON practices(tin);
```

### practice_locations
```sql
CREATE TABLE practice_locations (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    practice_id         UUID NOT NULL REFERENCES practices(id),
    location_name       VARCHAR(255) NOT NULL,                 -- "Main Office", "Satellite Clinic"
    address_line_1      TEXT NOT NULL,
    address_line_2      TEXT,
    city                VARCHAR(100),
    state               VARCHAR(2),
    zip_code            VARCHAR(10),
    phone               VARCHAR(20),
    fax                 VARCHAR(20),
    place_of_service    VARCHAR(5) NOT NULL DEFAULT '11',      -- CMS POS code
    facility_npi        VARCHAR(10),                           -- If facility has its own NPI
    is_primary          BOOLEAN DEFAULT FALSE,
    is_active           BOOLEAN DEFAULT TRUE,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_locations_practice ON practice_locations(practice_id);
```

### service_agreements (How You Bill Your Clients)
```sql
CREATE TABLE service_agreements (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    practice_id         UUID NOT NULL REFERENCES practices(id),

    -- Fee Model
    fee_model           VARCHAR(20) NOT NULL,                  -- percentage, per_claim, flat_fee, hybrid
    percentage_rate     DECIMAL(5,2),                          -- e.g., 5.50 for 5.5%
    per_claim_rate      DECIMAL(10,2),                         -- e.g., 4.50 per claim
    flat_fee_monthly    DECIMAL(12,2),                         -- e.g., 3000.00 per month
    -- Hybrid: flat base + percentage above threshold
    hybrid_base_fee     DECIMAL(12,2),
    hybrid_threshold    DECIMAL(12,2),                         -- Collections above this get percentage
    hybrid_overage_rate DECIMAL(5,2),

    -- Minimum fee
    minimum_monthly_fee DECIMAL(12,2),                         -- Floor fee regardless of collections

    -- Services Included
    includes_coding     BOOLEAN DEFAULT TRUE,
    includes_billing    BOOLEAN DEFAULT TRUE,
    includes_posting    BOOLEAN DEFAULT TRUE,
    includes_denials    BOOLEAN DEFAULT TRUE,
    includes_credentialing BOOLEAN DEFAULT FALSE,
    includes_eligibility BOOLEAN DEFAULT TRUE,
    includes_patient_collections BOOLEAN DEFAULT FALSE,
    includes_reporting  BOOLEAN DEFAULT TRUE,

    -- SLA Targets
    sla_clean_claim_rate DECIMAL(5,2) DEFAULT 95.00,          -- Target %
    sla_days_to_submit  INTEGER DEFAULT 2,                     -- Business days after receiving charge
    sla_appeal_turnaround INTEGER DEFAULT 5,                   -- Business days to file appeal
    sla_posting_turnaround INTEGER DEFAULT 2,                  -- Business days to post ERA
    sla_denial_response INTEGER DEFAULT 5,                     -- Business days to work denial

    -- Contract Terms
    effective_date      DATE NOT NULL,
    termination_date    DATE,
    auto_renew          BOOLEAN DEFAULT TRUE,
    notice_period_days  INTEGER DEFAULT 90,                    -- Days notice required to terminate

    is_active           BOOLEAN DEFAULT TRUE,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_agreements_practice ON service_agreements(practice_id);
```

### payer_enrollments (Per-Practice Payer Configuration)
```sql
CREATE TABLE payer_enrollments (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    practice_id         UUID NOT NULL REFERENCES practices(id),
    payer_id            UUID NOT NULL REFERENCES payers(id),

    -- Enrollment IDs
    group_number        VARCHAR(50),
    provider_numbers    JSONB,                                 -- {provider_npi: payer_provider_id}
    edi_payer_id        VARCHAR(20),                           -- Payer's EDI identifier

    -- ERA / EFT Enrollment
    era_enrolled        BOOLEAN DEFAULT FALSE,
    era_enrollment_date DATE,
    eft_enrolled        BOOLEAN DEFAULT FALSE,
    eft_enrollment_date DATE,

    -- Clearinghouse Config
    clearinghouse       VARCHAR(100),
    sender_id           VARCHAR(50),                           -- EDI sender ID for this practice+payer
    receiver_id         VARCHAR(50),

    -- Payer-Specific Config
    timely_filing_days  INTEGER,                               -- Override payer default
    appeal_filing_days  INTEGER,
    appeal_address      TEXT,
    appeal_fax          VARCHAR(20),
    payer_portal_url    VARCHAR(500),
    payer_portal_login  VARCHAR(255),                          -- Encrypted
    payer_phone         VARCHAR(20),
    payer_rep_name      VARCHAR(200),

    -- Fee Schedule
    fee_schedule_id     UUID REFERENCES fee_schedules(id),

    is_active           BOOLEAN DEFAULT TRUE,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(practice_id, payer_id)
);

CREATE INDEX idx_enrollments_practice ON payer_enrollments(practice_id);
CREATE INDEX idx_enrollments_payer ON payer_enrollments(payer_id);
```

---

## Charge Intake

### charge_batches (Incoming Work From Providers)
```sql
CREATE TABLE charge_batches (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    practice_id         UUID NOT NULL REFERENCES practices(id),
    submitted_by        UUID REFERENCES users(id),             -- Provider portal user who submitted
    intake_method       VARCHAR(20) NOT NULL,                  -- portal, upload, batch_import, ehr, fax
    source_file_id      UUID,                                  -- S3 reference if uploaded file
    total_charges       INTEGER DEFAULT 0,
    processed_charges   INTEGER DEFAULT 0,
    error_charges       INTEGER DEFAULT 0,
    status              VARCHAR(20) DEFAULT 'received',        -- received, processing, complete, error
    received_at         TIMESTAMPTZ DEFAULT NOW(),
    processed_at        TIMESTAMPTZ,
    notes               TEXT,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_charge_batches_practice ON charge_batches(practice_id);
CREATE INDEX idx_charge_batches_status ON charge_batches(status);
```

### charge_entries (Individual Charges From Provider)
```sql
CREATE TABLE charge_entries (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    practice_id         UUID NOT NULL REFERENCES practices(id),
    batch_id            UUID REFERENCES charge_batches(id),
    encounter_id        UUID REFERENCES encounters(id),        -- Linked after processing

    -- Patient Info (as submitted by provider)
    patient_id          UUID REFERENCES patients(id),
    patient_name_submitted VARCHAR(200),                       -- In case patient not yet in system
    patient_dob_submitted DATE,
    patient_mrn_submitted VARCHAR(50),

    -- Provider Info
    rendering_provider_id UUID REFERENCES providers(id),
    referring_provider_name VARCHAR(200),
    referring_provider_npi VARCHAR(10),

    -- Service Info
    service_date        DATE NOT NULL,
    place_of_service    VARCHAR(5),
    location_id         UUID REFERENCES practice_locations(id),

    -- Codes (as submitted — may need coding review)
    diagnosis_codes     VARCHAR(10)[],                         -- ICD-10 codes
    procedure_codes     JSONB,                                 -- [{cpt, modifiers[], units, charge}]
    needs_coding        BOOLEAN DEFAULT FALSE,                 -- True if notes need AI coding

    -- Clinical Documentation
    clinical_notes      TEXT,                                  -- If entered directly
    document_ids        UUID[],                                -- S3 references to uploaded docs
    superbill_image_id  UUID,                                  -- S3 reference to superbill scan

    -- Insurance Info
    primary_payer_id    UUID REFERENCES payers(id),
    member_id           VARCHAR(50),
    authorization_number VARCHAR(50),

    -- Status
    status              VARCHAR(20) DEFAULT 'received',
    -- received, validation_error, needs_info, needs_coding, ready_to_bill, billed, rejected
    validation_errors   JSONB,                                 -- List of missing/invalid fields
    assigned_to         UUID REFERENCES users(id),             -- Internal staff working this

    -- Communication
    provider_notified   BOOLEAN DEFAULT FALSE,                 -- If we asked provider for more info
    provider_response   TEXT,

    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_charges_practice ON charge_entries(practice_id);
CREATE INDEX idx_charges_status ON charge_entries(status);
CREATE INDEX idx_charges_assigned ON charge_entries(assigned_to);
CREATE INDEX idx_charges_date ON charge_entries(service_date);
```

---

## Provider Portal Communication

### portal_messages (Secure Inbox Between You and Provider)
```sql
CREATE TABLE portal_messages (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    practice_id         UUID NOT NULL REFERENCES practices(id),
    thread_id           UUID,                                  -- Group related messages
    sender_id           UUID NOT NULL REFERENCES users(id),
    sender_type         VARCHAR(20) NOT NULL,                  -- internal_staff, provider
    subject             VARCHAR(500),
    body                TEXT NOT NULL,
    attachments         UUID[],                                -- S3 references

    -- Context linking
    related_claim_id    UUID REFERENCES claims(id),
    related_charge_id   UUID REFERENCES charge_entries(id),
    related_denial_id   UUID REFERENCES denials(id),

    -- Status
    is_read             BOOLEAN DEFAULT FALSE,
    read_at             TIMESTAMPTZ,
    is_urgent           BOOLEAN DEFAULT FALSE,
    requires_response   BOOLEAN DEFAULT FALSE,
    response_deadline   TIMESTAMPTZ,

    created_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_messages_practice ON portal_messages(practice_id);
CREATE INDEX idx_messages_thread ON portal_messages(thread_id);
CREATE INDEX idx_messages_unread ON portal_messages(is_read) WHERE is_read = FALSE;
```

### portal_notifications
```sql
CREATE TABLE portal_notifications (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    practice_id         UUID NOT NULL REFERENCES practices(id),
    user_id             UUID NOT NULL REFERENCES users(id),
    notification_type   VARCHAR(30) NOT NULL,
    -- Types: denial_alert, payment_posted, claim_submitted, info_needed,
    --        report_ready, appeal_update, message_received
    title               VARCHAR(500) NOT NULL,
    body                TEXT,
    link_url            VARCHAR(500),                          -- Deep link into portal
    is_read             BOOLEAN DEFAULT FALSE,
    read_at             TIMESTAMPTZ,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_notifications_user ON portal_notifications(user_id);
CREATE INDEX idx_notifications_unread ON portal_notifications(is_read, user_id) WHERE is_read = FALSE;
```

---

## Internal Staff Management

### staff_assignments (Who Works on Which Practice)
```sql
CREATE TABLE staff_assignments (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             UUID NOT NULL REFERENCES users(id),    -- Internal billing staff
    practice_id         UUID NOT NULL REFERENCES practices(id),
    role_in_practice    VARCHAR(30) NOT NULL,                  -- coder, biller, poster, denial_analyst, manager
    is_primary          BOOLEAN DEFAULT FALSE,                 -- Primary contact for this client
    assigned_at         TIMESTAMPTZ DEFAULT NOW(),
    assigned_by         UUID REFERENCES users(id),

    UNIQUE(user_id, practice_id, role_in_practice)
);

CREATE INDEX idx_assignments_user ON staff_assignments(user_id);
CREATE INDEX idx_assignments_practice ON staff_assignments(practice_id);
```

### work_queue_items (Unified Cross-Client Queue)
```sql
CREATE TABLE work_queue_items (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    practice_id         UUID NOT NULL REFERENCES practices(id),
    queue_type          VARCHAR(20) NOT NULL,
    -- Types: intake, coding, billing, posting, denial, follow_up
    item_type           VARCHAR(30) NOT NULL,                  -- charge_entry, coding_session, claim, payment_batch, denial
    item_id             UUID NOT NULL,                         -- FK to the actual item
    priority            INTEGER DEFAULT 50,                    -- 0-100, higher = more urgent
    assigned_to         UUID REFERENCES users(id),
    status              VARCHAR(20) DEFAULT 'pending',         -- pending, in_progress, completed, escalated
    due_date            TIMESTAMPTZ,                           -- SLA deadline
    sla_breached        BOOLEAN DEFAULT FALSE,

    started_at          TIMESTAMPTZ,
    completed_at        TIMESTAMPTZ,
    time_spent_seconds  INTEGER,

    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_queue_type_status ON work_queue_items(queue_type, status);
CREATE INDEX idx_queue_assigned ON work_queue_items(assigned_to, status);
CREATE INDEX idx_queue_priority ON work_queue_items(priority DESC, due_date ASC);
CREATE INDEX idx_queue_practice ON work_queue_items(practice_id);
CREATE INDEX idx_queue_sla ON work_queue_items(sla_breached) WHERE sla_breached = TRUE;
```

### staff_productivity (Track Your Team's Performance)
```sql
CREATE TABLE staff_productivity (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             UUID NOT NULL REFERENCES users(id),
    practice_id         UUID REFERENCES practices(id),         -- NULL for aggregate
    date                DATE NOT NULL,
    queue_type          VARCHAR(20) NOT NULL,

    items_completed     INTEGER DEFAULT 0,
    total_time_seconds  INTEGER DEFAULT 0,
    avg_time_per_item   INTEGER DEFAULT 0,
    errors_found        INTEGER DEFAULT 0,                     -- QA review errors

    -- Specific metrics
    claims_submitted    INTEGER,
    claims_dollar_amount DECIMAL(14,2),
    payments_posted     INTEGER,
    payments_dollar_amount DECIMAL(14,2),
    denials_worked      INTEGER,
    denials_dollar_recovered DECIMAL(14,2),
    codes_reviewed      INTEGER,
    coding_accuracy_pct DECIMAL(5,2),

    created_at          TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(user_id, practice_id, date, queue_type)
);

CREATE INDEX idx_productivity_user ON staff_productivity(user_id, date);
CREATE INDEX idx_productivity_practice ON staff_productivity(practice_id, date);
```

---

## Client Billing (How You Invoice Your Clients)

### client_invoices
```sql
CREATE TABLE client_invoices (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    practice_id         UUID NOT NULL REFERENCES practices(id),
    invoice_number      VARCHAR(50) UNIQUE NOT NULL,
    billing_period_start DATE NOT NULL,
    billing_period_end  DATE NOT NULL,

    -- Collection Basis
    total_collections   DECIMAL(14,2) NOT NULL,                -- Total collected during period
    total_claims_submitted INTEGER,

    -- Fee Calculation
    fee_model_used      VARCHAR(20) NOT NULL,
    calculated_fee      DECIMAL(12,2) NOT NULL,
    minimum_fee_applied BOOLEAN DEFAULT FALSE,
    adjustments         DECIMAL(12,2) DEFAULT 0,               -- Credits, discounts
    total_due           DECIMAL(12,2) NOT NULL,

    -- Line Items (stored as JSONB for flexibility)
    line_items          JSONB NOT NULL,
    -- Example: [
    --   {"description": "Billing services (5.5% of $95,000)", "amount": 5225.00},
    --   {"description": "Credentialing - Dr. New Provider", "amount": 350.00},
    --   {"description": "Credit: SLA miss on appeal turnaround", "amount": -200.00}
    -- ]

    -- Payment Tracking
    status              VARCHAR(20) DEFAULT 'draft',           -- draft, sent, viewed, paid, overdue
    sent_at             TIMESTAMPTZ,
    due_date            DATE,
    paid_at             TIMESTAMPTZ,
    paid_amount         DECIMAL(12,2),
    payment_method      VARCHAR(30),                           -- check, ach, credit_card
    payment_reference   VARCHAR(100),

    notes               TEXT,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_invoices_practice ON client_invoices(practice_id);
CREATE INDEX idx_invoices_status ON client_invoices(status);
CREATE INDEX idx_invoices_period ON client_invoices(billing_period_start, billing_period_end);
```

---

## Updated Users Table (Multi-Tenant Aware)

```sql
-- Replace the existing users table with:
CREATE TABLE users (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email               VARCHAR(255) UNIQUE NOT NULL,
    password_hash       VARCHAR(255) NOT NULL,
    first_name          VARCHAR(100) NOT NULL,
    last_name           VARCHAR(100) NOT NULL,

    -- User Classification
    user_type           VARCHAR(20) NOT NULL,                  -- internal, provider
    -- internal = your billing company staff
    -- provider = someone from a client practice

    -- For provider users: which practice they belong to
    practice_id         UUID REFERENCES practices(id),         -- NULL for internal users

    -- For internal users: their company-wide role
    internal_role       VARCHAR(30),
    -- company_admin, billing_manager, coder, payment_poster,
    -- denial_analyst, qa_reviewer, readonly

    -- For provider users: their role within their practice
    provider_role       VARCHAR(30),
    -- practice_admin, provider, office_manager, front_desk

    -- Provider-specific
    provider_id         UUID REFERENCES providers(id),         -- If this user IS a doctor

    department          VARCHAR(100),
    is_active           BOOLEAN DEFAULT TRUE,
    last_login          TIMESTAMPTZ,
    mfa_enabled         BOOLEAN DEFAULT FALSE,
    mfa_secret          BYTEA,
    password_changed_at TIMESTAMPTZ DEFAULT NOW(),
    failed_login_count  INTEGER DEFAULT 0,
    locked_until        TIMESTAMPTZ,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_users_type ON users(user_type);
CREATE INDEX idx_users_practice ON users(practice_id);
CREATE INDEX idx_users_email ON users(email);
```

---

## RLS Policy Template (Apply to ALL Tenant Tables)

```sql
-- Template for every table that has practice_id:
-- Run this for: patients, encounters, claims, claim_lines, claim_diagnoses,
-- claim_scrub_results, payment_batches, payment_lines, adjustments, denials,
-- appeals, coding_sessions, coverages, charge_entries, charge_batches,
-- portal_messages, portal_notifications, work_queue_items

-- Example for claims:
ALTER TABLE claims ENABLE ROW LEVEL SECURITY;

-- Internal users: access assigned practices
CREATE POLICY claims_internal_access ON claims
    FOR ALL
    TO internal_role
    USING (
        practice_id IN (
            SELECT practice_id FROM staff_assignments
            WHERE user_id = current_setting('app.current_user_id')::UUID
        )
        OR current_setting('app.user_role') IN ('company_admin', 'qa_reviewer')
    );

-- Provider portal users: access only their practice
CREATE POLICY claims_provider_access ON claims
    FOR ALL
    TO provider_role
    USING (practice_id = current_setting('app.current_practice_id')::UUID);
```
