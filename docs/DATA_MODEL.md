# Data Model — MedClaim AI

## Entity Relationship Overview

```
Patient ──┬── Encounter ──┬── CodingSession ──── CodingSuggestion
          │               │
          │               └── Claim ──┬── ClaimLine
          │                           │
          └── Coverage ───────────────┤
                                      ├── ClaimScrubResult
                                      │
                                      ├── PaymentLine ──── Adjustment
                                      │       │
                                      │       └── PaymentBatch
                                      │
                                      └── Denial ──── Appeal
                                              │
                                              └── DenialPattern

Payer ──┬── FeeSchedule ──── FeeScheduleRate
        ├── PayerRule
        └── PayerPolicy

Provider ──── ProviderCredential

User ──── AuditLog
```

## Core Tables

### patients
```sql
CREATE TABLE patients (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    mrn                 VARCHAR(50) UNIQUE NOT NULL,          -- Medical Record Number
    first_name          TEXT NOT NULL,                         -- Encrypted at rest
    last_name           TEXT NOT NULL,                         -- Encrypted at rest
    date_of_birth       DATE NOT NULL,                         -- Encrypted at rest
    gender              VARCHAR(10),
    ssn_encrypted       BYTEA,                                -- AES-256 encrypted
    address_line_1      TEXT,
    address_line_2      TEXT,
    city                VARCHAR(100),
    state               VARCHAR(2),
    zip_code            VARCHAR(10),
    phone               VARCHAR(20),
    email               VARCHAR(255),
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW(),
    is_active           BOOLEAN DEFAULT TRUE
);

CREATE INDEX idx_patients_mrn ON patients(mrn);
CREATE INDEX idx_patients_name ON patients(last_name, first_name);
CREATE INDEX idx_patients_dob ON patients(date_of_birth);
```

### coverages (Insurance)
```sql
CREATE TABLE coverages (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id          UUID NOT NULL REFERENCES patients(id),
    payer_id            UUID NOT NULL REFERENCES payers(id),
    member_id           VARCHAR(50) NOT NULL,
    group_number        VARCHAR(50),
    plan_name           VARCHAR(255),
    plan_type           VARCHAR(20),                          -- HMO, PPO, POS, EPO, Medicare, Medicaid
    coverage_type       VARCHAR(20) NOT NULL,                 -- primary, secondary, tertiary
    subscriber_relation VARCHAR(20),                          -- self, spouse, child, other
    effective_date      DATE NOT NULL,
    termination_date    DATE,
    copay_amount        DECIMAL(10,2),
    deductible_amount   DECIMAL(10,2),
    deductible_met      DECIMAL(10,2),
    coinsurance_pct     DECIMAL(5,2),
    verified_at         TIMESTAMPTZ,
    verified_by         UUID REFERENCES users(id),
    is_active           BOOLEAN DEFAULT TRUE,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_coverages_patient ON coverages(patient_id);
CREATE INDEX idx_coverages_payer ON coverages(payer_id);
CREATE INDEX idx_coverages_member ON coverages(member_id);
```

### encounters
```sql
CREATE TABLE encounters (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id          UUID NOT NULL REFERENCES patients(id),
    provider_id         UUID NOT NULL REFERENCES providers(id),
    facility_id         UUID REFERENCES facilities(id),
    encounter_type      VARCHAR(20) NOT NULL,                 -- office, inpatient, outpatient, ER, telehealth
    encounter_date      DATE NOT NULL,
    admit_date          DATE,
    discharge_date      DATE,
    place_of_service    VARCHAR(5) NOT NULL,                  -- CMS POS codes (11, 21, 22, etc.)
    referring_provider_id UUID REFERENCES providers(id),
    prior_auth_number   VARCHAR(50),
    notes               TEXT,                                  -- Clinical notes reference
    document_ids        UUID[],                                -- References to stored documents in S3
    status              VARCHAR(20) DEFAULT 'open',            -- open, coded, billed, closed
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_encounters_patient ON encounters(patient_id);
CREATE INDEX idx_encounters_date ON encounters(encounter_date);
CREATE INDEX idx_encounters_status ON encounters(status);
```

### claims
```sql
CREATE TABLE claims (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    claim_number        VARCHAR(50) UNIQUE NOT NULL,
    encounter_id        UUID NOT NULL REFERENCES encounters(id),
    patient_id          UUID NOT NULL REFERENCES patients(id),
    payer_id            UUID NOT NULL REFERENCES payers(id),
    coverage_id         UUID NOT NULL REFERENCES coverages(id),
    rendering_provider  UUID NOT NULL REFERENCES providers(id),
    billing_provider    UUID NOT NULL REFERENCES providers(id),
    claim_type          VARCHAR(5) NOT NULL,                  -- 837P (professional), 837I (institutional)
    frequency_code      VARCHAR(2) DEFAULT '1',               -- 1=original, 7=replacement, 8=void
    total_charge        DECIMAL(12,2) NOT NULL,
    total_paid          DECIMAL(12,2) DEFAULT 0,
    total_adjusted      DECIMAL(12,2) DEFAULT 0,
    patient_responsibility DECIMAL(12,2) DEFAULT 0,
    status              VARCHAR(30) NOT NULL DEFAULT 'draft',
    -- Statuses: draft, scrubbing, scrub_failed, ready, submitted, accepted,
    --           rejected, paid, partial_paid, denied, appealed, closed
    submission_date     TIMESTAMPTZ,
    adjudication_date   TIMESTAMPTZ,
    timely_filing_deadline DATE,
    clearinghouse_id    VARCHAR(100),
    clearinghouse_ref   VARCHAR(100),
    edi_837_file_id     UUID,
    scrub_score         INTEGER,                               -- 0-100 clean claim score
    denial_risk_score   DECIMAL(5,4),                         -- ML-predicted denial probability
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW(),
    created_by          UUID REFERENCES users(id),
    
    CONSTRAINT valid_status CHECK (status IN (
        'draft','scrubbing','scrub_failed','ready','submitted',
        'accepted','rejected','paid','partial_paid','denied','appealed','closed'
    ))
);

CREATE INDEX idx_claims_number ON claims(claim_number);
CREATE INDEX idx_claims_patient ON claims(patient_id);
CREATE INDEX idx_claims_payer ON claims(payer_id);
CREATE INDEX idx_claims_status ON claims(status);
CREATE INDEX idx_claims_submission ON claims(submission_date);
CREATE INDEX idx_claims_encounter ON claims(encounter_id);
```

### claim_lines
```sql
CREATE TABLE claim_lines (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    claim_id            UUID NOT NULL REFERENCES claims(id) ON DELETE CASCADE,
    line_number         INTEGER NOT NULL,
    cpt_code            VARCHAR(10) NOT NULL,
    cpt_description     TEXT,
    icd_pointer_1       VARCHAR(10),                          -- ICD-10 diagnosis code
    icd_pointer_2       VARCHAR(10),
    icd_pointer_3       VARCHAR(10),
    icd_pointer_4       VARCHAR(10),
    modifier_1          VARCHAR(5),
    modifier_2          VARCHAR(5),
    modifier_3          VARCHAR(5),
    modifier_4          VARCHAR(5),
    units               DECIMAL(10,2) NOT NULL DEFAULT 1,
    charge_amount       DECIMAL(12,2) NOT NULL,
    paid_amount         DECIMAL(12,2) DEFAULT 0,
    allowed_amount      DECIMAL(12,2),
    service_date_from   DATE NOT NULL,
    service_date_to     DATE,
    place_of_service    VARCHAR(5),
    ndc_code            VARCHAR(20),                          -- National Drug Code (if applicable)
    revenue_code        VARCHAR(10),                          -- For institutional claims
    status              VARCHAR(20) DEFAULT 'active',
    
    UNIQUE(claim_id, line_number)
);

CREATE INDEX idx_claim_lines_claim ON claim_lines(claim_id);
CREATE INDEX idx_claim_lines_cpt ON claim_lines(cpt_code);
```

### claim_diagnoses
```sql
CREATE TABLE claim_diagnoses (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    claim_id            UUID NOT NULL REFERENCES claims(id) ON DELETE CASCADE,
    sequence_number     INTEGER NOT NULL,                     -- 1-12, order matters
    icd10_code          VARCHAR(10) NOT NULL,
    description         TEXT,
    is_principal        BOOLEAN DEFAULT FALSE,                -- Principal/primary diagnosis
    
    UNIQUE(claim_id, sequence_number)
);

CREATE INDEX idx_claim_dx_claim ON claim_diagnoses(claim_id);
CREATE INDEX idx_claim_dx_code ON claim_diagnoses(icd10_code);
```

### claim_scrub_results
```sql
CREATE TABLE claim_scrub_results (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    claim_id            UUID NOT NULL REFERENCES claims(id),
    claim_line_id       UUID REFERENCES claim_lines(id),
    rule_type           VARCHAR(30) NOT NULL,                 -- ncci_edit, mue, modifier, eligibility, auth, timely_filing, payer_specific
    rule_id             VARCHAR(100),                         -- Reference to specific rule
    severity            VARCHAR(10) NOT NULL,                 -- error, warning, info
    message             TEXT NOT NULL,
    suggestion          TEXT,                                  -- AI-suggested fix
    auto_fixable        BOOLEAN DEFAULT FALSE,
    auto_fixed          BOOLEAN DEFAULT FALSE,
    resolved            BOOLEAN DEFAULT FALSE,
    resolved_by         UUID REFERENCES users(id),
    resolved_at         TIMESTAMPTZ,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_scrub_claim ON claim_scrub_results(claim_id);
CREATE INDEX idx_scrub_severity ON claim_scrub_results(severity);
```

### payment_batches
```sql
CREATE TABLE payment_batches (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    payer_id            UUID NOT NULL REFERENCES payers(id),
    check_number        VARCHAR(50),
    eft_trace           VARCHAR(50),
    payment_method      VARCHAR(20),                          -- check, eft, virtual_card
    total_paid          DECIMAL(14,2) NOT NULL,
    total_claims        INTEGER NOT NULL,
    era_file_id         UUID,                                 -- S3 reference to 835 file
    production_date     DATE,
    deposit_date        DATE,
    posted_date         TIMESTAMPTZ,
    status              VARCHAR(20) DEFAULT 'received',       -- received, processing, posted, reconciled, exception
    posted_by           UUID REFERENCES users(id),
    auto_posted         BOOLEAN DEFAULT FALSE,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_payment_batch_payer ON payment_batches(payer_id);
CREATE INDEX idx_payment_batch_check ON payment_batches(check_number);
CREATE INDEX idx_payment_batch_status ON payment_batches(status);
```

### payment_lines
```sql
CREATE TABLE payment_lines (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    batch_id            UUID NOT NULL REFERENCES payment_batches(id),
    claim_id            UUID REFERENCES claims(id),
    claim_line_id       UUID REFERENCES claim_lines(id),
    patient_id          UUID REFERENCES patients(id),
    claim_number_reported VARCHAR(50),                        -- Claim # as reported by payer
    service_date        DATE,
    cpt_code            VARCHAR(10),
    billed_amount       DECIMAL(12,2),
    allowed_amount      DECIMAL(12,2),
    paid_amount         DECIMAL(12,2) NOT NULL,
    patient_responsibility DECIMAL(12,2) DEFAULT 0,
    match_status        VARCHAR(20) DEFAULT 'unmatched',      -- matched, unmatched, partial, exception
    match_confidence    DECIMAL(5,4),
    is_underpaid        BOOLEAN DEFAULT FALSE,
    underpayment_amount DECIMAL(12,2),
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_payment_line_batch ON payment_lines(batch_id);
CREATE INDEX idx_payment_line_claim ON payment_lines(claim_id);
CREATE INDEX idx_payment_line_match ON payment_lines(match_status);
```

### adjustments
```sql
CREATE TABLE adjustments (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    payment_line_id     UUID NOT NULL REFERENCES payment_lines(id),
    group_code          VARCHAR(5) NOT NULL,                  -- CO, PR, OA, PI, CR
    reason_code         VARCHAR(10) NOT NULL,                 -- CARC codes (1, 2, 3, 4, 45, 50, 96, 97, etc.)
    amount              DECIMAL(12,2) NOT NULL,
    remark_codes        VARCHAR(20)[],                        -- RARC codes (N1, N56, M15, MA130, etc.)
    is_denial           BOOLEAN DEFAULT FALSE,                -- Flagged if this adjustment = denial
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_adj_payment_line ON adjustments(payment_line_id);
CREATE INDEX idx_adj_reason ON adjustments(reason_code);
CREATE INDEX idx_adj_denial ON adjustments(is_denial) WHERE is_denial = TRUE;
```

### denials
```sql
CREATE TABLE denials (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    claim_id            UUID NOT NULL REFERENCES claims(id),
    claim_line_id       UUID REFERENCES claim_lines(id),
    adjustment_id       UUID REFERENCES adjustments(id),
    payer_id            UUID NOT NULL REFERENCES payers(id),
    denial_date         DATE NOT NULL,
    reason_code         VARCHAR(10) NOT NULL,                 -- CARC
    remark_codes        VARCHAR(20)[],                        -- RARC
    denial_amount       DECIMAL(12,2) NOT NULL,
    
    -- AI Classification
    category            VARCHAR(30),                          -- registration, coding, billing, clinical, auth, other
    subcategory         VARCHAR(50),
    root_cause          TEXT,                                  -- AI-generated root cause analysis
    
    -- Priority Scoring
    priority_score      DECIMAL(5,4),                         -- 0-1, higher = more urgent
    recovery_probability DECIMAL(5,4),                        -- ML-predicted appeal success rate
    
    -- Workflow
    status              VARCHAR(20) DEFAULT 'new',            -- new, in_review, appealing, resolved, written_off
    assigned_to         UUID REFERENCES users(id),
    appeal_deadline     DATE,
    timely_filing_deadline DATE,
    
    -- Resolution
    resolution          VARCHAR(20),                          -- paid, partial, upheld, written_off
    recovered_amount    DECIMAL(12,2),
    resolved_at         TIMESTAMPTZ,
    resolved_by         UUID REFERENCES users(id),
    
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_denials_claim ON denials(claim_id);
CREATE INDEX idx_denials_payer ON denials(payer_id);
CREATE INDEX idx_denials_status ON denials(status);
CREATE INDEX idx_denials_category ON denials(category);
CREATE INDEX idx_denials_priority ON denials(priority_score DESC);
CREATE INDEX idx_denials_deadline ON denials(appeal_deadline);
```

### appeals
```sql
CREATE TABLE appeals (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    denial_id           UUID NOT NULL REFERENCES denials(id),
    appeal_level        INTEGER NOT NULL DEFAULT 1,           -- 1=first, 2=second, 3=external/IRE
    appeal_type         VARCHAR(30),                          -- reconsideration, redetermination, QIC, ALJ, council
    
    -- Content
    letter_content      TEXT NOT NULL,                        -- Generated appeal letter
    letter_file_id      UUID,                                 -- S3 reference to final PDF
    supporting_docs     UUID[],                               -- S3 references to clinical docs
    
    -- AI Metadata
    ai_generated        BOOLEAN DEFAULT TRUE,
    ai_confidence       DECIMAL(5,4),
    prompt_template_id  VARCHAR(100),
    guidelines_cited    TEXT[],                                -- LCD/NCD/guideline references used
    
    -- Tracking
    status              VARCHAR(20) DEFAULT 'draft',          -- draft, approved, submitted, in_review, decided
    submitted_date      DATE,
    decision_date       DATE,
    decision            VARCHAR(20),                          -- approved, partial, denied
    decision_amount     DECIMAL(12,2),
    follow_up_date      DATE,
    
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW(),
    created_by          UUID REFERENCES users(id),
    approved_by         UUID REFERENCES users(id)
);

CREATE INDEX idx_appeals_denial ON appeals(denial_id);
CREATE INDEX idx_appeals_status ON appeals(status);
CREATE INDEX idx_appeals_follow_up ON appeals(follow_up_date);
```

### coding_sessions
```sql
CREATE TABLE coding_sessions (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    encounter_id        UUID NOT NULL REFERENCES encounters(id),
    coder_id            UUID REFERENCES users(id),
    document_ids        UUID[],                                -- S3 references to clinical docs
    
    -- AI Processing
    nlp_extraction      JSONB,                                -- Extracted clinical entities
    ai_model_version    VARCHAR(50),
    processing_time_ms  INTEGER,
    token_count         INTEGER,
    
    -- Results
    suggested_codes     JSONB NOT NULL,                       -- Array of {code, system, confidence, rationale}
    final_codes         JSONB,                                -- Coder-approved codes
    
    -- Audit
    review_started_at   TIMESTAMPTZ,
    review_completed_at TIMESTAMPTZ,
    review_time_seconds INTEGER,
    coder_changes       JSONB,                                -- Diff of what coder changed
    
    status              VARCHAR(20) DEFAULT 'processing',     -- processing, ready_for_review, approved, rejected
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_coding_encounter ON coding_sessions(encounter_id);
CREATE INDEX idx_coding_status ON coding_sessions(status);
CREATE INDEX idx_coding_coder ON coding_sessions(coder_id);
```

### payers
```sql
CREATE TABLE payers (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    payer_name          VARCHAR(255) NOT NULL,
    payer_id_number     VARCHAR(20) UNIQUE,                   -- Payer ID for EDI
    payer_type          VARCHAR(20),                          -- commercial, medicare, medicaid, tricare, workers_comp
    address             JSONB,
    phone               VARCHAR(20),
    website             VARCHAR(500),
    portal_url          VARCHAR(500),
    clearinghouse       VARCHAR(100),
    timely_filing_days  INTEGER DEFAULT 365,
    appeal_filing_days  INTEGER DEFAULT 60,
    electronic_payer    BOOLEAN DEFAULT TRUE,
    era_enrolled        BOOLEAN DEFAULT FALSE,
    eft_enrolled        BOOLEAN DEFAULT FALSE,
    notes               TEXT,
    is_active           BOOLEAN DEFAULT TRUE,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_payers_pid ON payers(payer_id_number);
CREATE INDEX idx_payers_type ON payers(payer_type);
```

### fee_schedules
```sql
CREATE TABLE fee_schedules (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    payer_id            UUID NOT NULL REFERENCES payers(id),
    name                VARCHAR(255) NOT NULL,
    effective_date      DATE NOT NULL,
    termination_date    DATE,
    is_active           BOOLEAN DEFAULT TRUE,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE fee_schedule_rates (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    fee_schedule_id     UUID NOT NULL REFERENCES fee_schedules(id),
    cpt_code            VARCHAR(10) NOT NULL,
    modifier            VARCHAR(5),
    place_of_service    VARCHAR(5),
    allowed_amount      DECIMAL(12,2) NOT NULL,
    effective_date      DATE NOT NULL,
    
    UNIQUE(fee_schedule_id, cpt_code, modifier, place_of_service, effective_date)
);

CREATE INDEX idx_fsr_schedule ON fee_schedule_rates(fee_schedule_id);
CREATE INDEX idx_fsr_cpt ON fee_schedule_rates(cpt_code);
```

### payer_rules
```sql
CREATE TABLE payer_rules (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    payer_id            UUID NOT NULL REFERENCES payers(id),
    rule_type           VARCHAR(30) NOT NULL,                 -- modifier, bundling, auth_required, frequency_limit, age_limit, gender_limit
    cpt_code            VARCHAR(10),
    icd10_code          VARCHAR(10),
    rule_definition     JSONB NOT NULL,                       -- Flexible rule structure
    description         TEXT,
    source              VARCHAR(255),                         -- Where this rule was sourced
    effective_date      DATE,
    termination_date    DATE,
    is_active           BOOLEAN DEFAULT TRUE,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_payer_rules_payer ON payer_rules(payer_id);
CREATE INDEX idx_payer_rules_cpt ON payer_rules(cpt_code);
CREATE INDEX idx_payer_rules_type ON payer_rules(rule_type);
```

### providers
```sql
CREATE TABLE providers (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    npi                 VARCHAR(10) UNIQUE NOT NULL,
    first_name          VARCHAR(100) NOT NULL,
    last_name           VARCHAR(100) NOT NULL,
    credential          VARCHAR(20),                          -- MD, DO, NP, PA, etc.
    taxonomy_code       VARCHAR(20),
    specialty           VARCHAR(100),
    tin                 VARCHAR(20),                          -- Encrypted
    is_individual       BOOLEAN DEFAULT TRUE,                 -- vs organizational
    is_active           BOOLEAN DEFAULT TRUE,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);
```

### audit_logs (HIPAA Required)
```sql
CREATE TABLE audit_logs (
    id                  BIGSERIAL PRIMARY KEY,
    user_id             UUID NOT NULL,
    action              VARCHAR(50) NOT NULL,                 -- read, create, update, delete, export, login, logout
    resource_type       VARCHAR(50) NOT NULL,                 -- patient, claim, payment, denial, etc.
    resource_id         UUID,
    resource_detail     TEXT,                                  -- What specific data was accessed
    ip_address          INET,
    user_agent          TEXT,
    request_path        VARCHAR(500),
    request_method      VARCHAR(10),
    response_status     INTEGER,
    phi_accessed        BOOLEAN DEFAULT FALSE,                -- Was PHI part of this access?
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

-- Partitioned by month for performance
-- Retained for minimum 7 years per HIPAA
CREATE INDEX idx_audit_user ON audit_logs(user_id);
CREATE INDEX idx_audit_resource ON audit_logs(resource_type, resource_id);
CREATE INDEX idx_audit_created ON audit_logs(created_at);
CREATE INDEX idx_audit_phi ON audit_logs(phi_accessed) WHERE phi_accessed = TRUE;
```

### users & RBAC
```sql
CREATE TABLE users (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email               VARCHAR(255) UNIQUE NOT NULL,
    password_hash       VARCHAR(255) NOT NULL,
    first_name          VARCHAR(100) NOT NULL,
    last_name           VARCHAR(100) NOT NULL,
    role                VARCHAR(30) NOT NULL,                 -- admin, billing_manager, coder, payment_poster, denial_analyst, analyst, readonly
    department          VARCHAR(100),
    is_active           BOOLEAN DEFAULT TRUE,
    last_login          TIMESTAMPTZ,
    mfa_enabled         BOOLEAN DEFAULT FALSE,
    mfa_secret          BYTEA,                                -- Encrypted
    password_changed_at TIMESTAMPTZ DEFAULT NOW(),
    failed_login_count  INTEGER DEFAULT 0,
    locked_until        TIMESTAMPTZ,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE permissions (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    role                VARCHAR(30) NOT NULL,
    resource            VARCHAR(50) NOT NULL,
    action              VARCHAR(20) NOT NULL,                 -- read, create, update, delete, export
    conditions          JSONB,                                -- Additional conditions (e.g., own_department_only)
    
    UNIQUE(role, resource, action)
);
```
