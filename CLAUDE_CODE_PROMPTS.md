# CLAUDE_CODE_PROMPTS.md
# Complete Prompt Playbook — Copy-Paste Into Claude Code In Order
# 
# INSTRUCTIONS:
# 1. Unzip rcm-ai-platform.zip into your working directory
# 2. cd rcm-ai-platform
# 3. Open Claude Code: claude
# 4. Paste each prompt below ONE AT A TIME
# 5. Wait for Claude Code to finish before pasting the next one
# 6. If Claude Code asks a question, answer it, then continue
# 7. After each phase, run the verification prompt before moving on
#
# ESTIMATED TIME: 2-3 weeks with Max 20x plan
# TOTAL PROMPTS: 62 prompts across 15 phases
#
# ⚠️  IMPORTANT: Always paste the VERIFY prompt after each phase
#     before moving to the next phase. Fix any issues before continuing.

# ═══════════════════════════════════════════════════════════════════
# PHASE 0: PROJECT INITIALIZATION
# ═══════════════════════════════════════════════════════════════════

## Prompt 0.1 — Project Context (PASTE THIS FIRST, EVERY SESSION)
```
Read the following files to understand the full project architecture before doing anything:

1. README.md
2. CLAUDE_CODE_INSTRUCTIONS.md
3. docs/ARCHITECTURE.md
4. docs/DATA_MODEL.md
5. docs/DATA_MODEL_MULTITENANT.md
6. docs/ENHANCEMENTS.md
7. src/config.py
8. src/api/main.py
9. src/api/middleware/tenant.py
10. src/api/routes/__init__.py

After reading, confirm you understand:
- This is a multi-tenant third-party medical billing platform
- Every table has practice_id with Row-Level Security
- There are two portals: Internal Staff and Provider Portal
- The user types are "internal" (billing company staff) and "provider" (client practice users)
- The build order in CLAUDE_CODE_INSTRUCTIONS.md must be followed exactly
```

## Prompt 0.2 — Environment Setup
```
Set up the development environment:

1. Create a Python virtual environment: python -m venv .venv && source .venv/bin/activate
2. Install all dependencies from pyproject.toml: pip install -e ".[dev]"
3. Copy .env.example to .env
4. Verify the app starts: python -c "from src.api.main import app; print('OK')"
5. Run existing tests: python -m pytest tests/ -v
6. Confirm all 157 tests pass

If any dependency fails to install, fix it. If any test fails, fix it before proceeding.
```


# ═══════════════════════════════════════════════════════════════════
# PHASE 1: DATABASE MODELS & MIGRATIONS
# ═══════════════════════════════════════════════════════════════════

## Prompt 1.1 — SQLAlchemy Models (Core Tables)
```
Create SQLAlchemy ORM models in src/infrastructure/database/models.py based on docs/DATA_MODEL.md.

Create these models with proper relationships, indexes, and constraints:
- Patient (with encrypted fields for SSN, DOB)
- Provider
- Payer
- Coverage (insurance)
- Encounter
- Claim (with all status options as enum)
- ClaimLine
- ClaimDiagnosis
- ClaimScrubResult
- PaymentBatch
- PaymentLine
- Adjustment
- Denial
- Appeal
- CodingSession
- FeeSchedule
- FeeScheduleRate
- PayerRule
- AuditLog (HIPAA required — immutable)

All models must:
- Use UUID primary keys (gen_random_uuid)
- Have created_at and updated_at timestamps
- Import from the Base class in src/infrastructure/database/session.py
- Use proper SQLAlchemy relationship() declarations
- Include all indexes specified in DATA_MODEL.md

DO NOT modify any existing files. Create new file only.
```

## Prompt 1.2 — SQLAlchemy Models (Multi-Tenant Tables)
```
Add multi-tenant models to src/infrastructure/database/models.py based on docs/DATA_MODEL_MULTITENANT.md.

Add these models:
- Practice (your client practices)
- PracticeLocation
- ServiceAgreement
- PayerEnrollment
- ChargeBatch
- ChargeEntry
- PortalMessage
- PortalNotification
- StaffAssignment
- WorkQueueItem
- StaffProductivity
- ClientInvoice
- User (updated with user_type, practice_id, internal_role, provider_role)
- Permission

Critical: Add practice_id as a foreign key column to ALL tenant-scoped models:
Patient, Encounter, Claim, ClaimLine, ClaimDiagnosis, ClaimScrubResult,
PaymentBatch, PaymentLine, Adjustment, Denial, Appeal, CodingSession,
Coverage, ChargeEntry, ChargeBatch, PortalMessage, PortalNotification,
WorkQueueItem

Every practice_id column must be: UUID, NOT NULL, REFERENCES practices(id)
```

## Prompt 1.3 — Alembic Setup & First Migration
```
Set up Alembic for database migrations:

1. Initialize Alembic: alembic init data/migrations
2. Configure alembic.ini to use the DATABASE_URL from .env
3. Configure data/migrations/env.py to:
   - Import all models from src/infrastructure/database/models
   - Use async engine
   - Support auto-generation of migrations
4. Generate the initial migration: alembic revision --autogenerate -m "initial_schema"
5. Review the generated migration file for correctness
6. Make sure all tables, indexes, and constraints from both DATA_MODEL.md files are included

Update alembic.ini to point to data/migrations as the script_location.
```

## Prompt 1.4 — Row-Level Security
```
Create a SQL migration file at data/migrations/rls_policies.sql that applies Row-Level Security to all tenant tables.

For each table with practice_id, add:
1. ALTER TABLE <table> ENABLE ROW LEVEL SECURITY;
2. CREATE POLICY for internal users (access assigned practices or all if admin/qa)
3. CREATE POLICY for provider users (access only their practice)

Follow the exact RLS policy pattern from docs/DATA_MODEL_MULTITENANT.md.

Also create a helper function in src/infrastructure/database/rls.py:
- async def set_tenant_context(session, user_id, user_role, practice_id)
  Sets the PostgreSQL session variables: app.current_user_id, app.user_role, app.current_practice_id

This function must be called at the start of every database transaction.
```

## VERIFY Phase 1:
```
Run these checks and fix any issues:

1. python -c "from src.infrastructure.database.models import *; print('All models import OK')"
2. python -m pytest tests/ -v  (all existing tests must still pass)
3. Count total models created and list them
4. Verify every tenant-scoped model has practice_id column
5. Verify User model has user_type, internal_role, provider_role, practice_id fields

If anything fails, fix it now before we proceed.
```


# ═══════════════════════════════════════════════════════════════════
# PHASE 2: AUTHENTICATION & SECURITY
# ═══════════════════════════════════════════════════════════════════

## Prompt 2.1 — Auth Service
```
Create src/infrastructure/auth/service.py with a complete authentication service:

1. Password hashing (bcrypt, work factor 12)
2. JWT token creation and validation:
   - Access token (15 min expiry) containing: user_id, user_type, email,
     internal_role OR provider_role, practice_id (for provider users),
     assigned_practice_ids (for internal users, queried from staff_assignments)
   - Refresh token (7 day expiry) 
3. MFA support (TOTP via pyotp):
   - generate_mfa_secret() → returns secret + QR code URI
   - verify_mfa_code(user_id, code) → bool
4. Account lockout:
   - Track failed login attempts
   - Lock account after 5 failures for 30 minutes
5. Password validation:
   - Minimum 12 characters
   - Must contain uppercase, lowercase, digit, special char

Use settings from src/config.py for all configuration values.
```

## Prompt 2.2 — Auth Middleware
```
Create src/infrastructure/auth/middleware.py with a FastAPI dependency for authentication:

1. get_current_user dependency:
   - Extracts JWT from Authorization: Bearer header
   - Validates token, checks expiry
   - Returns user dict with all JWT claims
   - Raises 401 if token invalid/expired

2. require_role dependency factory:
   - require_role("company_admin", "billing_manager") 
   - Checks user's role against allowed roles
   - Raises 403 if not authorized

3. require_practice_access dependency:
   - For internal users: checks if practice_id in their assigned_practice_ids
   - For provider users: checks if practice_id matches their practice_id
   - Company admins and QA reviewers bypass this check
   - Raises 403 if not authorized

4. Wire these into the TenantMiddleware in src/api/middleware/tenant.py:
   - Extract user info from JWT in the middleware
   - Set request.state.current_user from the JWT claims
```

## Prompt 2.3 — Auth Routes Implementation
```
Fully implement all endpoints in src/api/routes/auth.py:

1. POST /login — Accept email + password, verify credentials against User model,
   check MFA if enabled, return access_token + refresh_token.
   On failure: increment failed_login_count, lock if threshold reached.
   On success: reset failed_login_count, update last_login.

2. POST /refresh — Accept refresh_token, validate, return new access_token.

3. POST /logout — Invalidate the current refresh token (add to blacklist in Redis).

4. POST /mfa/setup — Generate TOTP secret, return secret + provisioning URI + QR code data.
   Requires authenticated user.

5. POST /mfa/verify — Verify TOTP code during login flow.

Use the auth service from the previous step. All endpoints must have proper request/response Pydantic models.
Write unit tests for login, refresh, and MFA flows.
```

## Prompt 2.4 — PHI Encryption Service
```
Create src/infrastructure/auth/encryption.py with field-level encryption:

1. PHIEncryptor class:
   - encrypt(plaintext: str) → encrypted bytes (AES-256-GCM)
   - decrypt(ciphertext: bytes) → plaintext string
   - Uses PHI_ENCRYPTION_KEY from settings
   - Each encryption generates a unique nonce/IV

2. SQLAlchemy custom type EncryptedString:
   - Automatically encrypts on write, decrypts on read
   - Use for: Patient.ssn, Patient.date_of_birth, Practice.tin

3. Key rotation support:
   - Support decrypting with old key while encrypting with new key
   - rotate_key(old_key, new_key) function for bulk re-encryption

Write tests proving encrypt/decrypt roundtrip works and different inputs produce different ciphertext.
```

## VERIFY Phase 2:
```
Run these checks:

1. python -m pytest tests/ -v (all tests pass)
2. Test auth service: create a user, login, get JWT, decode JWT, verify claims
3. Test MFA: generate secret, generate code, verify code
4. Test encryption: encrypt SSN, decrypt SSN, verify they match
5. Test account lockout: 5 failed logins → account locked
6. Test role checking: admin can access all, coder can only access assigned practices

Fix any issues before proceeding.
```


# ═══════════════════════════════════════════════════════════════════
# PHASE 3: CLIENT MANAGEMENT
# ═══════════════════════════════════════════════════════════════════

## Prompt 3.1 — Client Management Service
```
Create src/core/client_management/service.py implementing the business logic for managing practice clients.

Read src/api/routes/client_management.py for all the endpoints that need to be supported.

Implement:
1. PracticeService:
   - create_practice() — Create practice record, set status to "onboarding"
   - get_practice() / list_practices() — With tenant filtering
   - update_practice() — Update practice details
   - activate_practice() — Validate all onboarding steps done, set go_live_date
   - suspend_practice() — Set status to suspended, stop processing
   - terminate_practice() — Set status to terminated, trigger offboarding

2. ProviderService:
   - add_provider_to_practice() — Link provider to practice, create if NPI doesn't exist
   - list_practice_providers()

3. PayerEnrollmentService:
   - add_payer_enrollment() — Configure payer for a practice
   - update_payer_enrollment()

4. ServiceAgreementService:
   - create_agreement() — Set fee model, SLAs
   - calculate_fee() — Calculate billing fee for a period based on fee model

5. StaffAssignmentService:
   - assign_staff() — Assign internal user to practice
   - remove_assignment()

6. PortalUserService:
   - create_portal_user() — Create provider portal account with welcome email trigger
   - deactivate_portal_user()

7. OnboardingService:
   - get_onboarding_status() — Check which steps are complete
   - Checks: practice created, providers added, locations added, payers enrolled,
     fee schedules loaded, agreement set, portal users created

Every method must enforce tenant isolation. Every write must create an audit log entry.
```

## Prompt 3.2 — Wire Client Management Routes
```
Fully implement every endpoint in src/api/routes/client_management.py by:

1. Adding auth dependencies (require_role("company_admin", "billing_manager"))
2. Adding database session dependency (get_db)
3. Calling the PracticeService/ProviderService/etc from the service layer
4. Replacing all "raise HTTPException(status_code=501)" with actual implementations
5. Adding proper error handling (404 for not found, 409 for conflicts, 422 for validation)
6. Adding audit logging for all write operations

Write integration tests that:
- Create a practice through the API
- Add providers, locations, payer enrollments
- Set up a service agreement
- Create portal users
- Check onboarding status shows all steps complete
- Activate the practice
```

## VERIFY Phase 3:
```
Run all tests: python -m pytest tests/ -v
Test the full client onboarding flow end-to-end:
1. Create a practice
2. Add 2 providers
3. Add 2 locations
4. Add 3 payer enrollments
5. Create a service agreement (percentage model, 5.5%)
6. Create 2 portal users
7. Check onboarding status
8. Activate the practice
9. Verify practice status is "active"

Fix any issues before proceeding.
```


# ═══════════════════════════════════════════════════════════════════
# PHASE 4: REFERENCE DATA
# ═══════════════════════════════════════════════════════════════════

## Prompt 4.1 — Reference Data Loader
```
Create scripts/seed_reference_data.py that loads essential reference data:

1. CARC (Claim Adjustment Reason Codes) — Create a table or JSON file with all ~300 CARC codes
   and their descriptions. Include at minimum the top 50 most common codes from 
   CLAUDE_CODE_INSTRUCTIONS.md.

2. RARC (Remittance Advice Remark Codes) — Top 50 most common remark codes.

3. Place of Service codes — All CMS POS codes (01-99) with descriptions.

4. Payer seed data — Create at least 20 major payers:
   Medicare Part A, Medicare Part B, Medicaid (generic), 
   Aetna, Anthem/BCBS, Cigna, Humana, UnitedHealthcare, 
   Kaiser, Tricare, Blue Cross Blue Shield (multiple states),
   Molina, Centene, WellCare, Oscar Health, Ambetter

5. Sample NCCI edit pairs — Load at least 100 common NCCI Column 1/Column 2 edit pairs
   with modifier indicators.

6. Sample MUE values — Load MUE limits for at least 100 common CPT codes
   (E/M codes, common procedures, lab codes).

Create the seed script so it can be run with: python scripts/seed_reference_data.py
It should be idempotent (safe to run multiple times).
```

## Prompt 4.2 — Vector Store Seeding
```
Create scripts/build_vector_index.py that:

1. Creates all Qdrant collections defined in src/core/nlp/vector_store.py
2. Loads sample coding guidelines into the icd10_guidelines collection:
   - Create at least 30 sample guideline documents covering:
     - ICD-10-CM general coding guidelines (Chapter 1-4 summaries)
     - Common coding scenarios (diabetes, hypertension, fractures, respiratory)
     - Modifier usage guidelines
   - Chunk each document into ~500 token segments with overlap
   - Generate embeddings and store in Qdrant

3. Loads sample payer policies into the payer_policies collection:
   - Create at least 20 sample payer policy documents
   - Cover common medical necessity policies for: E/M visits, imaging, labs, physical therapy

4. Loads sample appeal templates into the appeal_templates collection:
   - Create at least 10 successful appeal letter templates for common denial types:
     - Medical necessity (CO-50)
     - Prior auth missing (CO-197)
     - Timely filing (CO-29)  
     - Bundling (CO-97)
     - Duplicate claim (CO-18)

Make the script idempotent and runnable with: python scripts/build_vector_index.py
Handle the case where Qdrant isn't running (log warning, skip).
```


# ═══════════════════════════════════════════════════════════════════
# PHASE 5: CHARGE INTAKE
# ═══════════════════════════════════════════════════════════════════

## Prompt 5.1 — Charge Intake Service
```
Create src/core/charge_intake/service.py implementing charge intake business logic.

Read src/api/routes/charge_intake.py for all endpoints.

Implement:
1. ChargeEntryService:
   - submit_charge() — Validate fields, match patient, create ChargeEntry record,
     create WorkQueueItem(type=intake), return charge with validation status
   - validate_charge() — Run validation:
     - Patient exists and has active coverage
     - Provider is in the practice
     - Codes are valid format (ICD-10 pattern, CPT 5-digit)
     - Service date not in future
     - No obvious duplicate (same patient+DOS+CPT in last 7 days)
   - request_info_from_provider() — Create PortalMessage + PortalNotification,
     set charge status to "needs_info"
   - route_to_coding() — Set status to "needs_coding", create WorkQueueItem(type=coding)
   - route_to_billing() — Create Encounter + Claim from charge data,
     set status to "ready_to_bill", create WorkQueueItem(type=billing)
   - reject_charge() — Set status to "rejected", notify provider

2. BatchImportService:
   - import_from_csv() — Parse CSV/Excel, validate each row, create ChargeEntry records
   - Return BatchImportResult with success/error counts and row-level errors

All operations must be scoped to practice_id.
```

## Prompt 5.2 — Wire Charge Intake Routes
```
Fully implement every endpoint in src/api/routes/charge_intake.py:

1. Replace all 501 stubs with real implementations calling ChargeEntryService
2. Add auth dependencies:
   - Provider portal users can: submit charges, upload superbills, batch import, view their charges
   - Internal staff can: validate, route, reject, request info, view all assigned practices
3. Add file upload handling for superbill_upload and batch_import endpoints
4. Add proper pagination for list endpoints
5. Implement intake dashboard and queue endpoints

Write tests covering:
- Provider submits a charge → appears in intake queue
- Staff validates a charge → validation errors returned
- Staff requests info → provider gets notification
- Staff routes to billing → claim created
- Batch import with 5 valid + 2 invalid rows → correct counts
```


# ═══════════════════════════════════════════════════════════════════
# PHASE 6: MEDICAL CODING ENGINE
# ═══════════════════════════════════════════════════════════════════

## Prompt 6.1 — Coding Service
```
Create src/core/coding/service.py implementing AI-assisted medical coding.

Read src/api/routes/coding.py and src/core/nlp/ai_service.py.

Implement:
1. CodingService:
   - start_session(encounter_id) — Full pipeline:
     a. Load encounter + clinical documents from S3/DB
     b. Call AIService.suggest_codes() with clinical text
     c. Validate suggested codes against NCCI edits and MUE
     d. Create CodingSession record with suggestions
     e. Create WorkQueueItem(type=coding) if not auto-approved
     f. Return session with ranked suggestions

   - approve_codes(session_id, approved_codes) —
     a. Record final codes and coder changes (diff from AI suggestions)
     b. Calculate coding accuracy metrics
     c. Update CodingSession status to "approved"
     d. Trigger claim assembly (route_to_billing)
     e. Mark WorkQueueItem as completed

   - get_relevant_guidelines(session_id) — 
     Query vector store for guidelines matching the session's codes

2. CodeLookupService:
   - lookup(code) — Return code description, guidelines, common modifiers
   - search(query) — Semantic search via vector store + exact match

Wire all endpoints in src/api/routes/coding.py with proper auth.
Internal staff (coders) only — provider portal users cannot access coding.

Write tests for the coding session lifecycle.
```


# ═══════════════════════════════════════════════════════════════════
# PHASE 7: CLAIMS & BILLING ENGINE
# ═══════════════════════════════════════════════════════════════════

## Prompt 7.1 — Claim Service
```
Create src/core/billing/service.py implementing claim lifecycle management.

Read src/api/routes/claims.py and src/core/rules_engine/scrubber.py.

Implement:
1. ClaimService:
   - create_claim(encounter_id, codes, payer_info) —
     a. Generate unique claim number (format: practice_prefix + sequential)
     b. Create Claim + ClaimLine + ClaimDiagnosis records
     c. Set status to "draft"
     d. Auto-trigger scrubbing

   - scrub_claim(claim_id) —
     a. Load claim with lines and diagnoses
     b. Load payer rules from PayerEnrollment + PayerRule tables
     c. Run ClaimScrubber.scrub() with NCCI data, MUE data, and payer rules
     d. Call AIService.analyze_claim_risk() for AI denial prediction
     e. Save ClaimScrubResult records
     f. Update claim.scrub_score and claim.denial_risk_score
     g. If no errors: set status to "ready"
     h. If errors: set status to "scrub_failed"

   - submit_claim(claim_id) —
     a. Verify status is "ready"
     b. Generate EDI 837P or 837I using Claim837Generator
     c. Look up clearinghouse config from practice's PayerEnrollment
     d. Submit to clearinghouse API (stub for now, log the EDI file)
     e. Store EDI file in S3
     f. Set status to "submitted", record submission_date
     g. Create follow-up WorkQueueItem if no response in 14 days

   - batch_submit(claim_ids) — Submit multiple claims in one EDI batch
   - void_claim(claim_id) — Generate void (frequency code 8)
   - submit_corrected(claim_id, corrections) — Generate corrected (frequency code 7)
   - get_claim_history(claim_id) — Full lifecycle events

Wire all endpoints in src/api/routes/claims.py.
Write tests for create → scrub → submit lifecycle.
```


# ═══════════════════════════════════════════════════════════════════
# PHASE 8: PAYMENT POSTING ENGINE
# ═══════════════════════════════════════════════════════════════════

## Prompt 8.1 — Payment Posting Service
```
Create src/core/payment_posting/service.py implementing ERA processing and payment posting.

Read src/api/routes/payments.py and src/services/edi/parser.py.

Implement:
1. ERAProcessingService:
   - process_era(file_content) —
     a. Parse with ERA835Parser
     b. Route to correct practice by matching payee TIN/NPI to Practice table
     c. Create PaymentBatch record
     d. For each claim in the ERA:
        - Match to existing Claim record (by claim number, then fuzzy by patient+DOS+CPT)
        - Create PaymentLine records with match_status and match_confidence
        - Create Adjustment records for each CAS segment
        - If adjustment.is_denial → create Denial record + WorkQueueItem(type=denial)
        - If paid_amount < expected (from fee schedule) → flag is_underpaid
     e. Auto-post: if match_confidence > 0.95 and no underpayment → post automatically
     f. Create WorkQueueItem(type=posting) for manual review items

2. PaymentMatchingService:
   - match_by_claim_number(claim_number) — Exact match
   - fuzzy_match(patient_name, dos, cpt, payer, amount) — Fuzzy matching with confidence score
   - manual_match(line_id, claim_id) — Staff manually matches

3. ReconciliationService:
   - generate_reconciliation(period) — Monthly reconciliation report
   - detect_underpayments(batch_id) — Compare paid vs fee schedule rates

Wire all endpoints in src/api/routes/payments.py.
Write tests covering ERA parsing → matching → posting → denial routing.
```


# ═══════════════════════════════════════════════════════════════════
# PHASE 9: DENIAL MANAGEMENT ENGINE
# ═══════════════════════════════════════════════════════════════════

## Prompt 9.1 — Denial Management Service
```
Create src/core/denial_management/service.py implementing AI-powered denial management.

Read src/api/routes/denials.py and src/core/nlp/ai_service.py.

Implement:
1. DenialService:
   - classify_denial(denial_id) —
     a. Load denial with claim context
     b. First-pass: map CARC code to category using CARC reference data
     c. Second-pass: call AIService.classify_denial() for deep root cause analysis
     d. Update denial.category, subcategory, root_cause
     e. Score priority: recovery_probability × denial_amount × deadline_urgency
     f. Update denial.priority_score and recovery_probability

   - get_worklist(user_id) —
     a. Get user's assigned practices
     b. Query denials with status in (new, in_review) for those practices
     c. Sort by priority_score DESC
     d. Return with claim and patient context

   - generate_appeal(denial_id, appeal_level) —
     a. Load denial + claim + clinical docs
     b. Call AIService.generate_appeal() with full context
     c. Create Appeal record with draft letter
     d. Return for human review

   - submit_appeal(denial_id, final_letter, supporting_docs) —
     a. Update Appeal status to "submitted"
     b. Record submission date
     c. Schedule follow-up (Celery task at 30 days)
     d. Notify provider via PortalNotification

   - analyze_patterns(practice_id, date_range) —
     a. Aggregate denials by category + payer + reason_code
     b. Calculate frequency, total amount, recovery rate per pattern
     c. Identify trends (increasing/decreasing/stable)

Wire all endpoints in src/api/routes/denials.py.
Write tests for denial lifecycle: intake → classify → appeal → resolution.
```


# ═══════════════════════════════════════════════════════════════════
# PHASE 10: WORK QUEUE SYSTEM
# ═══════════════════════════════════════════════════════════════════

## Prompt 10.1 — Work Queue Service
```
Create src/core/work_queue/service.py implementing the cross-client work queue system.

Read src/api/routes/work_queue.py.

Implement:
1. QueueService:
   - create_item(practice_id, queue_type, item_type, item_id, priority) —
     Create WorkQueueItem, calculate due_date from practice's SLA

   - get_my_queue(user_id, filters) —
     Get all items from user's assigned practices, sorted by priority

   - claim_item(item_id, user_id) — Self-assign, set status=in_progress, record started_at
   - release_item(item_id) — Return to queue, clear assignment
   - complete_item(item_id, time_spent) — Mark done, record time, update StaffProductivity
   - escalate_item(item_id, reason, escalate_to) — Change status, notify manager
   - assign_item(item_id, user_id) — Manager assigns to specific staff
   - bulk_assign(item_ids, user_id) — Batch assignment

2. PriorityEngine:
   - calculate_priority(item) — Based on: amount × deadline_urgency × recovery_prob × sla_risk
   - recalculate_all() — Celery periodic task to update priorities

3. SLAMonitor:
   - check_breaches() — Find items past SLA deadline, mark sla_breached=True, alert managers
   - get_compliance_report(practice_id, date_range) — Actual vs target per SLA metric

4. ProductivityTracker:
   - log_completion(user_id, practice_id, queue_type, time_spent) — Update StaffProductivity
   - get_team_workload() — Current assignments per staff member
   - get_productivity_report(user_id, date_range) — Items completed, time, accuracy

Wire all endpoints in src/api/routes/work_queue.py.
Write tests for queue operations and SLA monitoring.
```


# ═══════════════════════════════════════════════════════════════════
# PHASE 11: PROVIDER PORTAL
# ═══════════════════════════════════════════════════════════════════

## Prompt 11.1 — Provider Portal Service
```
Create src/core/provider_portal/service.py implementing provider-facing features.

Read src/api/routes/provider_portal.py.

CRITICAL SECURITY RULE: Every method must enforce practice_id from the authenticated
provider user's JWT. Provider users can NEVER see data from other practices.
Provider users can NEVER see internal staff notes, work queue details, or scrub results.

Implement:
1. PortalDashboardService:
   - get_dashboard(practice_id, period) — Calculate all KPIs:
     total_charges_mtd, total_collections_mtd, ar_aging buckets,
     claims_submitted/paid/denied counts, denial_rate, pending work counts

2. PortalClaimService:
   - list_claims(practice_id, filters) — Simplified claim view for providers
     (hide internal fields like scrub_score, assigned_to, internal notes)
   - get_claim_timeline(claim_id) — Key lifecycle events only

3. PortalDenialService:
   - list_denials(practice_id) — Show denials with status of billing team's work
   - upload_supporting_doc(denial_id, file) — Provider uploads clinical docs for appeal

4. PortalMessageService:
   - list_messages(practice_id) — Conversations with billing team
   - send_message(practice_id, subject, body, related_claim_id)
   - mark_read(message_id)

5. PortalNotificationService:
   - list_notifications(practice_id, user_id) — Unread notifications
   - mark_all_read()

6. PortalReportService:
   - monthly_collection_report(practice_id, period)
   - ar_aging_report(practice_id)
   - denial_summary(practice_id, period)
   - payer_performance(practice_id)

Wire all endpoints in src/api/routes/provider_portal.py.
Add auth dependency: require user_type == "provider".
Write tests proving provider cannot access other practices' data.
```


# ═══════════════════════════════════════════════════════════════════
# PHASE 12: CLIENT BILLING & INVOICING
# ═══════════════════════════════════════════════════════════════════

## Prompt 12.1 — Client Billing Service
```
Create src/core/client_billing/service.py implementing invoice generation.

Read src/api/routes/client_billing.py.

Implement:
1. InvoiceService:
   - generate_invoice(practice_id, period_start, period_end) —
     a. Load practice's ServiceAgreement
     b. Calculate total collections for the period (sum of payments posted)
     c. Apply fee model:
        - Percentage: collections × percentage_rate / 100
        - Per-claim: count submitted claims × per_claim_rate
        - Flat fee: flat_fee_monthly
        - Hybrid: hybrid_base_fee + max(0, (collections - hybrid_threshold) × hybrid_overage_rate / 100)
     d. Apply minimum_monthly_fee if calculated fee is lower
     e. Generate invoice number (format: INV-YYYYMM-XXXX)
     f. Create ClientInvoice record with line items
     g. Return draft for review

   - generate_all_invoices(period) — Generate for all active practices
   - send_invoice(invoice_id) — Set status to "sent", create PortalNotification, set due date (Net 30)
   - record_payment(invoice_id, amount, method, reference)
   - void_invoice(invoice_id, reason)

2. RevenueReportService:
   - company_revenue_dashboard(period) — Total invoiced, collected, outstanding, overdue
   - client_profitability(date_range) — Revenue per client vs staff hours (from StaffProductivity)
   - revenue_projections() — Based on pipeline and historical patterns

Wire all endpoints in src/api/routes/client_billing.py.
Auth: company_admin and billing_manager only.
Write tests for fee calculation under each fee model.
```


# ═══════════════════════════════════════════════════════════════════
# PHASE 13: ANALYTICS & REPORTING
# ═══════════════════════════════════════════════════════════════════

## Prompt 13.1 — Analytics Service
```
Create src/core/reporting/service.py implementing analytics and reporting.

Read src/api/routes/analytics.py.

Implement:
1. DashboardService (internal staff all-client overview):
   - get_dashboard() — Aggregate KPIs across all practices:
     total_claims, total_collections, avg_denial_rate, avg_days_in_ar,
     clean_claim_rate, top_denial_reasons, sla_compliance

2. PracticeAnalyticsService (per-practice deep dive):
   - revenue_cycle_metrics(practice_id) — Days in AR, clean claim rate,
     denial rate, net collection rate, first pass resolution rate
   - payer_performance(practice_id) — Per-payer metrics
   - ar_aging(practice_id) — Aging buckets with drill-down
   - coding_accuracy() — AI suggestion acceptance rate

3. ReportGenerationService:
   - generate_pdf_report(practice_id, report_type, period) — 
     Generate PDF using the PDF skill for monthly reports

Wire all endpoints in src/api/routes/analytics.py.
Write tests for key metric calculations.
```


# ═══════════════════════════════════════════════════════════════════
# PHASE 14: CELERY BACKGROUND TASKS
# ═══════════════════════════════════════════════════════════════════

## Prompt 14.1 — Background Tasks
```
Create Celery tasks for all async operations:

1. src/core/billing/tasks.py:
   - task: scrub_claim_async(claim_id)
   - task: submit_claim_async(claim_id)
   - task: check_timely_filing_deadlines() — Daily, alert on claims approaching deadline

2. src/core/payment_posting/tasks.py:
   - task: process_era_async(file_id)
   - task: daily_reconciliation() — Daily reconciliation report

3. src/core/denial_management/tasks.py:
   - task: classify_denial_async(denial_id)
   - task: check_appeal_deadlines() — Hourly, alert on approaching appeal deadlines
   - task: analyze_patterns() — Weekly denial pattern analysis

4. src/core/work_queue/tasks.py:
   - task: recalculate_priorities() — Every 15 minutes, update priority scores
   - task: check_sla_breaches() — Every 30 minutes, flag breached items

5. src/core/client_billing/tasks.py:
   - task: generate_monthly_invoices() — 1st of month, generate all invoices
   - task: send_overdue_reminders() — Weekly, remind practices of overdue invoices

6. src/core/provider_portal/tasks.py:
   - task: send_notification_email(notification_id) — Send email for urgent notifications
   - task: send_daily_digest(practice_id) — Daily summary email to practice

Register all tasks in src/infrastructure/queue/celery_app.py beat_schedule.
Write tests for each task (mock external calls).
```


# ═══════════════════════════════════════════════════════════════════
# PHASE 15: FULL TESTING & BUG FIXES
# ═══════════════════════════════════════════════════════════════════

## Prompt 15.1 — Integration Tests
```
Create tests/integration/test_full_lifecycle.py with end-to-end tests:

1. test_complete_claim_lifecycle:
   - Create practice → add provider → add payer enrollment → add patient
   - Submit charge via portal → validate → route to coding
   - Start coding session → approve codes → claim created
   - Scrub claim → submit → mock ERA response → post payment
   - Verify claim status is "paid", provider sees it in portal

2. test_denial_to_appeal_lifecycle:
   - Create a claim that gets denied (from ERA with CO-197)
   - Denial auto-classified
   - Appeal generated by AI
   - Appeal submitted
   - Follow-up task created

3. test_multi_tenant_isolation:
   - Create Practice A and Practice B
   - Create data in both practices
   - Verify Practice A user cannot see Practice B data
   - Verify Practice B user cannot see Practice A data
   - Verify internal staff assigned to A can see A but not B
   - Verify admin can see both

4. test_client_billing_lifecycle:
   - Create practice with percentage fee model at 5.5%
   - Post $100,000 in payments during a period
   - Generate invoice → verify fee is $5,500
   - Send invoice → provider sees notification
   - Record payment → invoice status is "paid"

5. test_work_queue_lifecycle:
   - Submit 5 charges → 5 intake queue items created
   - Staff claims 3 items → status changes to in_progress
   - Staff completes 2 → productivity tracked
   - 1 item breaches SLA → sla_breached flag set

Run all tests and fix every failure.
```

## Prompt 15.2 — Bug Hunt
```
Do a comprehensive bug hunt across the entire codebase:

1. Check every API endpoint for:
   - Missing auth dependencies (no endpoint should be accessible without login)
   - Missing tenant filtering (every DB query must filter by practice_id)
   - Missing input validation (no raw user input should reach the database)
   - Missing error handling (no endpoint should return 500)
   - Missing audit logging (every write operation must be logged)

2. Check for security issues:
   - PHI in error messages or logs
   - SQL injection risks
   - JWT validation bypass
   - CORS misconfiguration
   - Missing rate limiting

3. Check for data integrity issues:
   - Foreign key violations possible?
   - Race conditions in auto-posting?
   - Orphaned records possible?
   - Duplicate claim submission possible?

4. Check for performance issues:
   - N+1 query problems
   - Missing database indexes
   - Unbounded queries (no pagination)
   - Large response payloads

Fix every issue found. Write a test for each bug fixed.
```

## Prompt 15.3 — Production Hardening
```
Prepare the application for production deployment:

1. Add rate limiting middleware:
   - 100 req/min per user for general endpoints
   - 30 req/min for AI endpoints (coding, appeal generation)
   - 10 req/min for bulk operations

2. Add request validation middleware:
   - Max request body size: 10MB (50MB for file uploads)
   - Content-Type validation
   - Request timeout: 30 seconds (120 seconds for AI endpoints)

3. Add structured error responses:
   - Every error returns: {"error": str, "detail": str, "request_id": str}
   - Never expose stack traces in production
   - Never include PHI in error messages

4. Add Prometheus metrics:
   - Request count by endpoint and status
   - Request duration histogram
   - Active database connections
   - Celery queue depths
   - AI API call count and latency

5. Add health check improvements:
   - /health — Always returns 200 (for load balancer)
   - /ready — Checks DB, Redis, Qdrant connectivity, returns details

6. Add graceful shutdown handling

7. Update docker-compose.yml for production:
   - Use gunicorn + uvicorn workers
   - Add nginx reverse proxy
   - Add SSL/TLS termination
   - Add log aggregation

8. Create scripts/healthcheck.py that verifies the entire system is operational

Run all tests one final time: python -m pytest tests/ -v --tb=short
Every test must pass. Zero failures allowed.
```

## Prompt 15.4 — Final Verification
```
Run the complete verification suite:

1. python -m pytest tests/ -v --tb=short  (MUST be 100% pass)
2. python -m pytest tests/ --cov=src --cov-report=term-missing  (report coverage)
3. Start the server: uvicorn src.api.main:app --port 8765 &
4. Hit every endpoint group and verify responses
5. Check Swagger docs at /api/docs render correctly
6. Verify security headers on all responses
7. Verify audit log entries are being created
8. Stop the server

Print a final report:
- Total tests: X passed, 0 failed
- Code coverage: X%
- Total API endpoints: X
- Total database models: X
- Security checks: all passed

If ANYTHING fails, fix it now. Do not stop until everything passes.
```


# ═══════════════════════════════════════════════════════════════════
# PHASE 16: FRONTEND (Optional — separate prompts)
# ═══════════════════════════════════════════════════════════════════

## Prompt 16.1 — Staff Portal Frontend Setup
```
Create the internal staff portal frontend at ui/staff-portal/:

1. Initialize: npx create-vite@latest . --template react-ts
2. Install: npm install @tanstack/react-query axios react-router-dom 
   tailwindcss @tailwindcss/forms lucide-react recharts
   @radix-ui/react-dialog @radix-ui/react-dropdown-menu
3. Set up Tailwind CSS
4. Create src/lib/api.ts — Axios instance with JWT auth header and base URL
5. Create src/lib/auth.ts — Login, logout, token storage, refresh logic
6. Create src/hooks/useAuth.ts — Auth context and hook
7. Create layout: sidebar navigation with client switcher at top
8. Create pages:
   - /login — Login page with MFA support
   - /dashboard — All-client health overview
   - /queues — Work queue interface
   - /claims — Claims management
   - /coding — Coding workbench
   - /payments — Payment posting
   - /denials — Denial worklist
   - /clients — Client management
   - /billing — Invoice management
   - /settings — User settings

Build a professional, clean UI. Not generic — make it look like a real billing platform.
```

## Prompt 16.2 — Provider Portal Frontend Setup
```
Create the provider portal frontend at ui/provider-portal/:

Same tech stack as staff portal but completely separate app.

Pages:
- /login — Login with practice branding
- /dashboard — Practice KPI dashboard with charts
- /claims — Claim status tracker with timeline view
- /charges — Charge entry form + superbill upload
- /denials — Denial alerts
- /messages — Secure inbox
- /reports — Monthly reports with download
- /invoices — View/download invoices
- /settings — Practice settings

This portal must feel simple and transparent — providers are not billing experts.
Use clear language, avoid jargon, show claim status as a visual timeline.
```


# ═══════════════════════════════════════════════════════════════════
# PRODUCTION STARTUP COMMANDS
# ═══════════════════════════════════════════════════════════════════

# After all phases are complete, start the full stack:

# 1. Start infrastructure
docker-compose up -d postgres redis qdrant minio

# 2. Run migrations
alembic upgrade head

# 3. Seed reference data
python scripts/seed_reference_data.py

# 4. Build vector indices
python scripts/build_vector_index.py

# 5. Start API server
uvicorn src.api.main:app --host 0.0.0.0 --port 8000 --workers 4

# 6. Start Celery workers
celery -A src.infrastructure.queue.celery_app worker -l info -Q coding,billing,payments,denials,edi -c 4

# 7. Start Celery beat (scheduler)
celery -A src.infrastructure.queue.celery_app beat -l info

# 8. Start staff portal
cd ui/staff-portal && npm run build && npx serve -s dist -l 3000

# 9. Start provider portal
cd ui/provider-portal && npm run build && npx serve -s dist -l 3001

# Full stack with Docker:
docker-compose up -d
