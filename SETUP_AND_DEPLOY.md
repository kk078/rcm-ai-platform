# SETUP_AND_DEPLOY.md
# ═══════════════════════════════════════════════════════════════
# MedClaim AI — Complete Setup, Build & Deploy Guide
# Windows 10/11 • 16GB RAM • Python + Docker + Node.js
# GitHub: kk078/rcm-ai-platform
# Domain: rcm.aetheraonline.com (Cloudflare)
# ═══════════════════════════════════════════════════════════════
#
# ⚠️  SECURITY: NEVER put tokens/passwords in code or chat.
#     Store them ONLY in .env files (gitignored) or secret managers.
#     Rotate any credential that was ever exposed.


# ═══════════════════════════════════════════════════════════════
# PART 1: ONE-TIME MACHINE SETUP (15 minutes)
# ═══════════════════════════════════════════════════════════════

## Step 1.1 — Verify Tools (PowerShell)

```powershell
# Open PowerShell (regular, not admin) and check each tool:
python --version        # Need 3.11+ (ideally 3.12)
docker --version        # Need Docker Desktop running
docker compose version  # Need v2+
node --version          # Need 18+
npm --version           # Comes with Node
git --version           # Need Git installed

# If Git is missing:
winget install Git.Git
# Restart PowerShell after installing
```

## Step 1.2 — Install Claude Code

```powershell
# Install Claude Code CLI
npm install -g @anthropic-ai/claude-code

# Verify
claude --version
```

## Step 1.3 — Authenticate Claude Code

```powershell
# Option A: If you have a Max subscription (recommended)
claude
# It will open your browser — log in with your Anthropic account
# Close Claude Code after auth is confirmed (type /exit)

# Option B: If using API key
# Set it as environment variable (replace with your REAL key)
[System.Environment]::SetEnvironmentVariable("ANTHROPIC_API_KEY", "sk-ant-YOUR_REAL_KEY", "User")
# Restart PowerShell for it to take effect
```

## Step 1.4 — Docker Desktop Settings

```
Open Docker Desktop → Settings:
  ✅ General → Use WSL 2 based engine (checked)
  ✅ Resources → Memory: Set to 8GB (half your 16GB)
  ✅ Resources → CPUs: Set to 4
  ✅ Resources → Disk: At least 40GB
  Apply & Restart
```


# ═══════════════════════════════════════════════════════════════
# PART 2: PROJECT SETUP (20 minutes)
# ═══════════════════════════════════════════════════════════════

## Step 2.1 — Clone & Configure

```powershell
# Create workspace
mkdir C:\Projects
cd C:\Projects

# Clone your repo
git clone https://github.com/kk078/rcm-ai-platform.git
cd rcm-ai-platform

# If the repo is empty, unzip the scaffold files into it:
# Copy the rcm-ai-platform.zip contents into this folder

# Create Python virtual environment
python -m venv .venv

# Activate it (DO THIS EVERY TIME you open a new terminal)
.\.venv\Scripts\Activate.ps1

# If execution policy error:
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
# Then retry the activate command

# Install all Python dependencies
pip install -e ".[dev]"
```

## Step 2.2 — Create .env File With Secrets

```powershell
# Copy the template
Copy-Item .env.example .env

# Generate secure random keys
python -c "
import secrets, base64
print('Copy these into your .env file:')
print(f'APP_SECRET_KEY={secrets.token_hex(32)}')
print(f'JWT_SECRET_KEY={secrets.token_hex(32)}')
print(f'PHI_ENCRYPTION_KEY={base64.b64encode(secrets.token_bytes(32)).decode()}')
print(f'FIELD_ENCRYPTION_KEY={base64.b64encode(secrets.token_bytes(32)).decode()}')
"

# Open .env in your editor and paste the generated keys
notepad .env
```

### What to change in .env:
```
APP_SECRET_KEY=<paste-generated-value>
JWT_SECRET_KEY=<paste-generated-value>
PHI_ENCRYPTION_KEY=<paste-generated-value>
FIELD_ENCRYPTION_KEY=<paste-generated-value>
ANTHROPIC_API_KEY=sk-ant-YOUR_REAL_API_KEY_HERE
APP_ENV=development
APP_DEBUG=true
```

## Step 2.3 — Verify Everything Loads

```powershell
# Test the app loads
python -c "from src.api.main import app; print('App loaded successfully')"

# Run all existing tests
python -m pytest tests/ -v

# Expected output: 157 passed, 0 failed
# If anything fails, fix before continuing
```

## Step 2.4 — Start Infrastructure

```powershell
# Make sure Docker Desktop is running first!

# Start all infrastructure services
docker compose up -d postgres redis qdrant minio

# Verify all containers are running
docker compose ps

# Expected: 4 containers, all "running" or "Up"
# - postgres  (port 5432)
# - redis     (port 6379)
# - qdrant    (port 6333)
# - minio     (port 9000)

# Test database connectivity
python -c "
import asyncio, asyncpg
async def test():
    conn = await asyncpg.connect('postgresql://medclaim:password@localhost:5432/medclaim_db')
    print('Database connected:', await conn.fetchval('SELECT 1'))
    await conn.close()
asyncio.run(test())
"
```

## Step 2.5 — Push Initial Code to GitHub

```powershell
# Make sure .env is in .gitignore (it should be already)
# NEVER commit .env to Git

git add .
git commit -m "Initial project scaffold with architecture"
git push origin main
```


# ═══════════════════════════════════════════════════════════════
# PART 3: BUILD WITH CLAUDE CODE — EXACT PROMPTS
# ═══════════════════════════════════════════════════════════════
#
# Open Claude Code in your project directory:
#   cd C:\Projects\rcm-ai-platform
#   .\.venv\Scripts\Activate.ps1
#   claude
#
# Then paste prompts ONE AT A TIME below.
# Wait for each to complete before pasting the next.
# After each PHASE, commit your code:
#   git add . && git commit -m "Phase X complete"
#   git push origin main


# ───────────────────────────────────────────────────────────────
# CONTEXT PROMPT (Paste this at the START of every Claude Code session)
# ───────────────────────────────────────────────────────────────

PROMPT_0_CONTEXT:
```
Read these files to understand the full project before doing anything:

README.md
CLAUDE_CODE_INSTRUCTIONS.md
docs/ARCHITECTURE.md
docs/DATA_MODEL.md
docs/DATA_MODEL_MULTITENANT.md
src/config.py
src/api/main.py
src/api/middleware/tenant.py
src/api/routes/__init__.py

This is a multi-tenant third-party medical billing platform for Windows development.
Infrastructure runs in Docker (Postgres on localhost:5432, Redis on localhost:6379,
Qdrant on localhost:6333, MinIO on localhost:9000).

Confirm you understand the architecture before proceeding.
```

# ───────────────────────────────────────────────────────────────
# PHASE 1: DATABASE (Paste after context prompt)
# ───────────────────────────────────────────────────────────────

PROMPT_1A:
```
Create all SQLAlchemy ORM models in src/infrastructure/database/models.py.

Read docs/DATA_MODEL.md and docs/DATA_MODEL_MULTITENANT.md for the complete schema.

Create EVERY table from both documents as a SQLAlchemy model:

Core tables: Patient, Provider, Payer, Coverage, Encounter, Claim, ClaimLine,
ClaimDiagnosis, ClaimScrubResult, PaymentBatch, PaymentLine, Adjustment,
Denial, Appeal, CodingSession, FeeSchedule, FeeScheduleRate, PayerRule, AuditLog

Multi-tenant tables: Practice, PracticeLocation, ServiceAgreement, PayerEnrollment,
ChargeBatch, ChargeEntry, PortalMessage, PortalNotification, StaffAssignment,
WorkQueueItem, StaffProductivity, ClientInvoice, User, Permission

Rules:
- Every model uses UUID primary key with server_default
- Every model has created_at and updated_at TIMESTAMPTZ columns
- Every tenant-scoped model has: practice_id = Column(UUID, ForeignKey("practices.id"), nullable=False)
- Use proper relationship() declarations
- Use Enum types for status fields
- Import Base from src/infrastructure/database/session.py
- Include all indexes from the data model docs
- Add __tablename__ to every model

After creating the file, verify it imports: python -c "from src.infrastructure.database.models import *; print('OK')"
```

PROMPT_1B:
```
Set up Alembic for database migrations.

1. Run: alembic init data/migrations
2. Edit alembic.ini: set script_location = data/migrations
3. Edit data/migrations/env.py to:
   - Import all models: from src.infrastructure.database.models import *
   - Import Base: from src.infrastructure.database.session import Base
   - Set target_metadata = Base.metadata
   - Configure for async with asyncpg
   - Read database URL from environment or .env file
4. Generate migration: alembic revision --autogenerate -m "initial_schema"
5. Apply migration: alembic upgrade head
6. Verify tables exist: connect to postgres and list tables

The database is running at: postgresql://medclaim:password@localhost:5432/medclaim_db

Test by running: alembic upgrade head
Then verify: python -c "
import asyncio, asyncpg
async def test():
    conn = await asyncpg.connect('postgresql://medclaim:password@localhost:5432/medclaim_db')
    tables = await conn.fetch(\"SELECT tablename FROM pg_tables WHERE schemaname='public'\")
    print(f'{len(tables)} tables created:', [t['tablename'] for t in tables])
    await conn.close()
asyncio.run(test())
"
```

PROMPT_1C:
```
Create Row-Level Security policies for multi-tenant isolation.

Create a new Alembic migration: alembic revision -m "add_row_level_security"

In the migration, add RLS to ALL tables that have practice_id:
patients, encounters, claims, claim_lines, claim_diagnoses, claim_scrub_results,
payment_batches, payment_lines, adjustments, denials, appeals, coding_sessions,
coverages, charge_entries, charge_batches, portal_messages, portal_notifications,
work_queue_items, staff_productivity, client_invoices

For each table add:
  ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
  CREATE POLICY {table}_isolation ON {table}
    USING (practice_id = current_setting('app.current_practice_id', true)::UUID);

Also create src/infrastructure/database/rls.py with:
  async def set_tenant_context(session, user_id: str, role: str, practice_id: str)
  — Executes SET LOCAL for app.current_user_id, app.user_role, app.current_practice_id

Apply: alembic upgrade head
Run all tests to make sure nothing broke: python -m pytest tests/ -v
```

AFTER PHASE 1, RUN:
```powershell
git add .
git commit -m "Phase 1: Database models, migrations, RLS"
git push origin main
python -m pytest tests/ -v
```

# ───────────────────────────────────────────────────────────────
# PHASE 2: AUTHENTICATION
# ───────────────────────────────────────────────────────────────

PROMPT_2A:
```
Build the complete authentication system.

Create src/infrastructure/auth/service.py:
- hash_password(password) → bcrypt hash (work factor 12)
- verify_password(password, hash) → bool
- create_access_token(user_data) → JWT (15 min expiry) containing:
  user_id, user_type, email, internal_role or provider_role,
  practice_id (for provider users), assigned_practice_ids (for internal)
- create_refresh_token(user_id) → JWT (7 day expiry)
- decode_token(token) → dict (raises 401 on invalid/expired)
- generate_mfa_secret() → (secret, provisioning_uri)
- verify_mfa(secret, code) → bool
- validate_password_strength(password) → raises if < 12 chars, no uppercase, no digit, no special

Create src/infrastructure/auth/dependencies.py:
- get_current_user = FastAPI Depends that extracts JWT from Authorization header
- require_role(*roles) = factory that returns Depends checking user role
- require_internal = shortcut for require_role with any internal role
- require_provider = shortcut for provider portal users only

Use python-jose for JWT, passlib[bcrypt] for passwords, pyotp for MFA.
Use settings from src/config.py for all keys and timeouts.

Create tests/unit/test_auth.py testing:
- Password hash/verify roundtrip
- JWT create/decode roundtrip
- Expired token raises error
- MFA generate/verify works
- Weak password rejected
- Role checking works

Run: python -m pytest tests/ -v
```

PROMPT_2B:
```
Implement all auth endpoints in src/api/routes/auth.py:

POST /api/v1/auth/login:
- Accept: {"email": str, "password": str, "mfa_code": str|null}
- Verify credentials against User table in database
- If MFA enabled and no code: return {"mfa_required": true}
- If MFA enabled and code: verify TOTP code
- On success: return {"access_token": ..., "refresh_token": ..., "user": {...}}
- On failure: increment failed_login_count, lock after 5 attempts
- On success: reset failed_login_count, update last_login

POST /api/v1/auth/refresh:
- Accept: {"refresh_token": str}
- Return new access_token

POST /api/v1/auth/logout:
- Invalidate refresh token (store in Redis blacklist with TTL)

POST /api/v1/auth/mfa/setup:
- Requires authenticated user
- Generate TOTP secret, return secret + QR provisioning URI

POST /api/v1/auth/mfa/verify:
- Verify TOTP code, enable MFA on user account

Also implement PHI field encryption in src/infrastructure/auth/encryption.py:
- Class PHIEncryptor with encrypt(plaintext) → bytes and decrypt(ciphertext) → str
- Uses AES-256-GCM with PHI_ENCRYPTION_KEY from settings
- Create an EncryptedString SQLAlchemy TypeDecorator for auto-encrypt/decrypt

Wire the auth middleware into src/api/middleware/tenant.py:
- Import get_current_user
- In TenantMiddleware.dispatch(), decode JWT and set request.state.current_user

Create a seed script to create a default admin user:
  Email: admin@medclaim.ai
  Password: MedClaim2026!Admin
  Role: company_admin

Run: python -m pytest tests/ -v
```

AFTER PHASE 2:
```powershell
git add .
git commit -m "Phase 2: Authentication, JWT, MFA, PHI encryption"
git push origin main
```

# ───────────────────────────────────────────────────────────────
# PHASE 3: CLIENT MANAGEMENT
# ───────────────────────────────────────────────────────────────

PROMPT_3:
```
Implement the complete client management module.

Create src/core/client_management/service.py with business logic for:
- PracticeService: create, list, get, update, activate, suspend, terminate practices
- LocationService: add/list locations for a practice
- ProviderService: add/list providers for a practice (link existing NPI if found)
- PayerEnrollmentService: add/update/list payer enrollments per practice
- FeeScheduleService: import from CSV, list, get rates
- ServiceAgreementService: create/get service agreement with fee model config
- StaffAssignmentService: assign/remove internal staff to practices
- PortalUserService: create/deactivate provider portal users
- OnboardingService: check which onboarding steps are complete

Then fully implement EVERY endpoint in src/api/routes/client_management.py:
- Replace all "raise HTTPException(status_code=501)" with real implementations
- Add auth: require_role("company_admin", "billing_manager") on all endpoints
- Add get_db dependency for database sessions
- Call set_tenant_context() before any DB operation
- Return proper error codes (404 not found, 409 conflict, 422 validation)

Write tests/integration/test_client_management.py:
- Test full onboarding flow: create practice → add providers → add locations →
  add payer enrollments → set service agreement → create portal users → activate
- Test that onboarding checklist reflects completion status
- Test suspend and terminate workflows
- Test staff assignments

Run: python -m pytest tests/ -v
```

AFTER PHASE 3:
```powershell
git add .
git commit -m "Phase 3: Client management, practice onboarding"
git push origin main
```

# ───────────────────────────────────────────────────────────────
# PHASE 4: REFERENCE DATA + CHARGE INTAKE
# ───────────────────────────────────────────────────────────────

PROMPT_4A:
```
Create scripts/seed_reference_data.py that loads essential reference data into the database.

Load:
1. Top 50 CARC codes with descriptions (create a reference table or use JSON)
2. Top 30 RARC codes
3. All CMS Place of Service codes (01-99)
4. 20 major payers: Medicare A, Medicare B, Medicaid, Aetna, Anthem BCBS,
   Cigna, Humana, UnitedHealthcare, Kaiser, Tricare, BCBS-FL, BCBS-TX,
   BCBS-CA, BCBS-NY, Molina, Centene, WellCare, Oscar, Ambetter, Wellmark
5. 100 common NCCI Column1/Column2 edit pairs with modifier indicators
6. MUE values for 100 common CPT codes (E/M 99211-99215, 99281-99285,
   common surgeries, labs 80048-80076, imaging 70553-74177)

Script must be idempotent (safe to run multiple times — use upsert logic).
Run it: python scripts/seed_reference_data.py
Verify data loaded: print counts of each reference data type.
```

PROMPT_4B:
```
Implement the charge intake module.

Create src/core/charge_intake/service.py with:
- submit_charge(): validate fields, match patient, create ChargeEntry,
  create WorkQueueItem(type=intake)
- validate_charge(): check patient exists, provider in practice, codes valid format,
  DOS not future, no duplicate in last 7 days
- request_info(): create PortalMessage + PortalNotification, set status needs_info
- route_to_coding(): set status needs_coding, create WorkQueueItem(type=coding)
- route_to_billing(): create Encounter + Claim from charge, create WorkQueueItem(type=billing)
- reject_charge(): set status rejected, notify provider
- batch_import(): parse CSV, validate rows, create ChargeEntry per row

Fully implement every endpoint in src/api/routes/charge_intake.py:
- Provider portal users can: submit charges, list their charges, upload documents
- Internal staff can: validate, route, reject, request info, see all assigned practices
- Replace all 501 stubs with real implementations

Write tests for: submit charge → validate → route to billing → claim created.

Run: python -m pytest tests/ -v
```

AFTER PHASE 4:
```powershell
git add .
git commit -m "Phase 4: Reference data, charge intake"
git push origin main
```

# ───────────────────────────────────────────────────────────────
# PHASE 5: CODING + CLAIMS + PAYMENTS + DENIALS
# ───────────────────────────────────────────────────────────────

PROMPT_5A:
```
Implement the medical coding engine.

Create src/core/coding/service.py:
- start_session(encounter_id): load encounter docs, call AIService.suggest_codes(),
  validate against NCCI/MUE, create CodingSession, create WorkQueueItem
- approve_codes(session_id, final_codes): record changes, calculate accuracy,
  trigger claim assembly
- get_guidelines(session_id): query Qdrant vector store for relevant guidelines

Create scripts/build_vector_index.py:
- Initialize all Qdrant collections from src/core/nlp/vector_store.py
- Load 30 sample coding guideline documents
- Load 20 sample payer policy documents
- Load 10 sample appeal letter templates
- Handle Qdrant not running gracefully (skip with warning)

Implement all endpoints in src/api/routes/coding.py.
Internal staff (coders) only — provider portal users cannot access.

Write tests for coding session lifecycle.
Run: python -m pytest tests/ -v
```

PROMPT_5B:
```
Implement the claims and billing engine.

Create src/core/billing/service.py:
- create_claim(encounter_id, codes, payer_info): generate claim number,
  create Claim + ClaimLine + ClaimDiagnosis, set status draft
- scrub_claim(claim_id): load claim, load payer rules, run ClaimScrubber.scrub(),
  call AIService.analyze_claim_risk(), save results, update score/status
- submit_claim(claim_id): verify ready, generate EDI 837 using Claim837Generator,
  store in S3/MinIO, set status submitted, log submission
- batch_submit(claim_ids): submit multiple in one EDI batch
- void_claim / submit_corrected: frequency code 7 and 8 workflows

Implement all endpoints in src/api/routes/claims.py.
Write tests for create → scrub → submit lifecycle.
Run: python -m pytest tests/ -v
```

PROMPT_5C:
```
Implement the payment posting engine.

Create src/core/payment_posting/service.py:
- process_era(file_content): parse with ERA835Parser, route to practice by TIN,
  create PaymentBatch, match payments to claims (exact then fuzzy),
  create PaymentLine + Adjustment records, auto-post high-confidence matches,
  route denials to denial management, flag underpayments
- fuzzy_match(patient, dos, cpt, payer, amount): confidence-scored matching
- manual_match(line_id, claim_id): staff manually matches
- generate_reconciliation(period): monthly reconciliation with totals

Implement all endpoints in src/api/routes/payments.py.
Write tests: parse ERA → match → post → denials routed.
Run: python -m pytest tests/ -v
```

PROMPT_5D:
```
Implement the denial management engine.

Create src/core/denial_management/service.py:
- classify_denial(denial_id): map CARC to category, call AIService.classify_denial()
  for deep root cause, score priority (recovery_prob × amount × deadline_urgency)
- get_worklist(user_id): prioritized denials from assigned practices
- generate_appeal(denial_id, level): call AIService.generate_appeal() with full context,
  create Appeal record with draft letter
- submit_appeal(denial_id, letter, docs): update status, schedule follow-up
- analyze_patterns(practice_id, dates): aggregate denials by category/payer/reason

Implement all endpoints in src/api/routes/denials.py.
Write tests for denial lifecycle: intake → classify → appeal → resolution.
Run: python -m pytest tests/ -v
```

AFTER PHASE 5:
```powershell
git add .
git commit -m "Phase 5: Coding, claims, payments, denials engines"
git push origin main
```

# ───────────────────────────────────────────────────────────────
# PHASE 6: WORK QUEUES + PORTAL + INVOICING
# ───────────────────────────────────────────────────────────────

PROMPT_6A:
```
Implement the work queue system.

Create src/core/work_queue/service.py:
- create_item(): create WorkQueueItem with SLA-based due_date
- get_my_queue(user_id): cross-practice prioritized queue
- claim/release/complete/escalate/assign operations
- auto_assign(): distribute by practice assignment + role + workload
- check_sla_breaches(): find past-due items, set sla_breached flag
- track_productivity(): log completions to StaffProductivity

Implement all endpoints in src/api/routes/work_queue.py.
Write tests for queue operations and SLA monitoring.
Run: python -m pytest tests/ -v
```

PROMPT_6B:
```
Implement the provider portal.

Create src/core/provider_portal/service.py:
CRITICAL: Every method MUST enforce practice_id from JWT. Provider users can
NEVER see data from other practices or internal workflow details.

- get_dashboard(practice_id, period): calculate KPIs
- list_claims(practice_id, filters): simplified view, hide internal fields
- get_claim_timeline(claim_id): lifecycle events only
- list_denials(practice_id): with billing team action status
- messaging: list, send, mark_read
- notifications: list, mark_all_read
- reports: monthly collection, AR aging, denial summary, payer performance

Implement all endpoints in src/api/routes/provider_portal.py.
Auth: require user_type == "provider" on all endpoints.

Write tests PROVING provider cannot access other practice's data.
Run: python -m pytest tests/ -v
```

PROMPT_6C:
```
Implement client billing and invoicing.

Create src/core/client_billing/service.py:
- generate_invoice(practice_id, period): load service agreement, calculate collections,
  apply fee model (percentage/per-claim/flat/hybrid), apply minimum fee,
  generate invoice number, create ClientInvoice with line items
- generate_all_invoices(period): batch for all active practices
- send_invoice(id): create portal notification, set due date Net 30
- record_payment(id, amount, method): update invoice
- revenue_dashboard(period): company-wide revenue metrics
- client_profitability(dates): revenue vs staff cost per practice

Implement all endpoints in src/api/routes/client_billing.py.
Auth: company_admin and billing_manager only.

Write tests for fee calculation under each model:
- 5.5% of $100,000 collections = $5,500
- $4.50 × 500 claims = $2,250
- Flat $3,000/month
- Hybrid: $2,000 base + 3% over $50,000 threshold

Run: python -m pytest tests/ -v
```

AFTER PHASE 6:
```powershell
git add .
git commit -m "Phase 6: Work queues, provider portal, invoicing"
git push origin main
```

# ───────────────────────────────────────────────────────────────
# PHASE 7: ANALYTICS + BACKGROUND TASKS
# ───────────────────────────────────────────────────────────────

PROMPT_7A:
```
Implement analytics and reporting.

Create src/core/reporting/service.py:
- all_client_dashboard(): aggregate KPIs across practices
- practice_metrics(practice_id): revenue cycle metrics, denial rate, days in AR
- ar_aging(practice_id): aging buckets with amounts
- payer_performance(practice_id): per-payer payment speed, denial rate
- coding_accuracy(): AI suggestion acceptance rate over time

Implement all endpoints in src/api/routes/analytics.py.
Write tests for key metric calculations.
Run: python -m pytest tests/ -v
```

PROMPT_7B:
```
Implement all Celery background tasks.

Create these task files:
- src/core/billing/tasks.py: scrub_claim_async, submit_claim_async, check_timely_filing (daily)
- src/core/payment_posting/tasks.py: process_era_async, daily_reconciliation
- src/core/denial_management/tasks.py: classify_denial_async, check_appeal_deadlines (hourly), analyze_patterns (weekly)
- src/core/work_queue/tasks.py: recalculate_priorities (15 min), check_sla_breaches (30 min)
- src/core/client_billing/tasks.py: generate_monthly_invoices (1st of month), send_overdue_reminders (weekly)
- src/core/provider_portal/tasks.py: send_notification_email, send_daily_digest

Register all in src/infrastructure/queue/celery_app.py beat_schedule.
Write tests for each task (mock external API calls).
Run: python -m pytest tests/ -v
```

AFTER PHASE 7:
```powershell
git add .
git commit -m "Phase 7: Analytics, reporting, background tasks"
git push origin main
```

# ───────────────────────────────────────────────────────────────
# PHASE 8: INTEGRATION TESTING + BUG FIXES
# ───────────────────────────────────────────────────────────────

PROMPT_8A:
```
Write comprehensive integration tests in tests/integration/test_full_lifecycle.py.

Test 1 — Complete claim lifecycle:
  Create practice → add provider → add payer enrollment → add patient →
  submit charge via portal → validate → route to coding → approve codes →
  claim created → scrub → submit → mock ERA payment → post payment →
  verify claim paid, provider sees it in portal dashboard

Test 2 — Denial to appeal lifecycle:
  Submit claim → ERA comes back with denial (CO-197) → denial auto-classified →
  appeal generated → appeal submitted → follow-up scheduled

Test 3 — Multi-tenant isolation:
  Create Practice A and Practice B → create data in both →
  verify Practice A user CANNOT see Practice B data →
  verify internal staff assigned to A can see A but NOT B →
  verify company_admin can see BOTH

Test 4 — Client billing lifecycle:
  Create practice with 5.5% fee model → post $100K in payments →
  generate invoice → verify fee = $5,500 → send → provider sees notification →
  record payment → invoice status = paid

Test 5 — Work queue lifecycle:
  Submit 5 charges → 5 intake queue items created →
  staff claims 3 → staff completes 2 → productivity tracked →
  1 item breaches SLA → sla_breached flag set

Run: python -m pytest tests/ -v --tb=short
Fix EVERY failure before proceeding.
```

PROMPT_8B:
```
Do a comprehensive bug hunt across the entire codebase.

Check EVERY endpoint for:
1. Missing auth dependencies (no endpoint accessible without login)
2. Missing tenant filtering (every query filters by practice_id)
3. Missing input validation (no raw input reaches database unsanitized)
4. Missing error handling (no 500 errors — always proper error response)
5. Missing audit logging (every write operation logged)

Check for security issues:
- PHI in error messages or logs
- SQL injection risks (use parameterized queries only)
- JWT validation bypass
- Missing CORS restrictions
- Rate limiting missing on AI endpoints

Check for data integrity:
- Foreign key violations possible?
- Race conditions in auto-posting?
- Duplicate claim submission possible?

Check for performance:
- N+1 query problems (use joinedload/selectinload)
- Missing database indexes
- Unbounded queries (all list endpoints need pagination)
- Large responses (add field limiting)

Fix EVERY issue found. Write a test for each bug fixed.
Run: python -m pytest tests/ -v --tb=short
ZERO FAILURES ALLOWED.
```

PROMPT_8C:
```
Production hardening.

1. Add rate limiting middleware to src/api/main.py:
   - 100 req/min per user for general endpoints
   - 30 req/min for AI endpoints (coding, appeals)
   - 10 req/min for bulk operations
   Use slowapi library.

2. Add structured error handling:
   - Global exception handler returning {"error": str, "detail": str, "request_id": str}
   - Never expose stack traces in production (check APP_DEBUG setting)
   - Never include PHI in error messages

3. Add Prometheus metrics endpoint at /metrics:
   - Request count by endpoint and status
   - Request duration histogram
   - Active DB connections

4. Improve health checks:
   - GET /health always returns 200 (for load balancer)
   - GET /ready checks DB + Redis + Qdrant, returns status of each

5. Create scripts/healthcheck.py that tests the full system:
   - Check DB connectivity
   - Check Redis connectivity
   - Check all API endpoint groups respond
   - Print pass/fail report

Run: python -m pytest tests/ -v --tb=short
Run: python scripts/healthcheck.py
```

AFTER PHASE 8:
```powershell
git add .
git commit -m "Phase 8: Integration tests, bug fixes, production hardening"
git push origin main
```

# ───────────────────────────────────────────────────────────────
# PHASE 9: FRONTEND
# ───────────────────────────────────────────────────────────────

PROMPT_9A:
```
Create the internal staff portal frontend at ui/staff-portal/.

Initialize:
  cd ui/staff-portal
  npm create vite@latest . -- --template react-ts
  npm install @tanstack/react-query axios react-router-dom tailwindcss
  npm install @radix-ui/react-dialog @radix-ui/react-dropdown-menu
  npm install lucide-react recharts date-fns
  npx tailwindcss init -p

Set up:
- src/lib/api.ts — Axios client with JWT auth header, base URL http://localhost:8000/api/v1
- src/lib/auth.ts — Login, token storage in memory (not localStorage for HIPAA), refresh
- src/contexts/AuthContext.tsx — Auth provider with useAuth hook
- src/contexts/PracticeContext.tsx — Active practice context (client switcher)

Layout:
- Sidebar: Dashboard, Queues, Claims, Coding, Payments, Denials, Clients, Billing, Settings
- Top bar: Practice switcher dropdown, user menu, notifications bell
- Content area with breadcrumbs

Pages (create all with real API calls):
- /login — Email + password + MFA form
- /dashboard — All-client health cards (one card per practice with key metrics)
- /queues — Tabbed queue view (Intake | Coding | Billing | Posting | Denial | Follow-up)
  with claim/release/complete actions, priority indicators, SLA badges
- /claims — Claim list with filters, scrub results, batch submit button
- /coding — Split view: document on left, code suggestions on right, approve button
- /payments — ERA upload, payment matching grid, unmatched queue
- /denials — Priority-sorted worklist, denial detail with appeal editor
- /clients — Practice list with status badges, onboarding wizard
- /clients/:id — Practice detail tabs: Info, Providers, Payers, Fee Schedules, Agreement, Staff, Portal Users
- /billing — Invoice list, generate button, revenue dashboard with charts
- /settings — User profile, change password, MFA setup

Use a professional dark sidebar with light content area.
Use shadcn/ui-style components (clean, minimal, professional).
The UI should look like a real enterprise billing platform, not a generic template.

Build and verify: npm run build
```

PROMPT_9B:
```
Create the provider portal frontend at ui/provider-portal/.

This is a SEPARATE React app for practice clients (doctors/office staff).

Initialize same way as staff portal but different design:
- Lighter, friendlier design
- Simpler navigation (providers are not billing experts)
- Clear, jargon-free labels

Pages:
- /login — Clean login with practice branding support
- /dashboard — KPI cards (collections, AR, denial rate), AR aging donut chart,
  recent activity feed, pending items count
- /charges — Charge entry form with favorite codes list, superbill upload button,
  batch import, list of submitted charges with status
- /claims — Claim tracker with search, status filter, timeline visualization
  (visual dots: Submitted → Accepted → Paid or Submitted → Denied → Appealing)
- /denials — Denial alerts with what billing team is doing, upload supporting docs button
- /messages — Inbox with threading, compose with claim linking
- /reports — Monthly collection, AR aging, denial summary, payer performance
  Each with download PDF button
- /invoices — Invoice list from billing company, view detail, download PDF
- /settings — Practice info, provider list, notification preferences

API calls go to: http://localhost:8000/api/v1/portal/*
Auth: provider JWT (practice-locked)

This portal must feel SIMPLE and TRANSPARENT.
Use claim status as visual timeline, not tables.
Use plain language ("Your claim was paid $450" not "Adjudicated - CO-45 applied").

Build and verify: npm run build
```

AFTER PHASE 9:
```powershell
git add .
git commit -m "Phase 9: Staff portal + Provider portal frontends"
git push origin main
```

# ───────────────────────────────────────────────────────────────
# PHASE 10: DOCKERIZE + DEPLOY TO CLOUDFLARE
# ───────────────────────────────────────────────────────────────

PROMPT_10A:
```
Create production Docker configuration.

1. Update Dockerfile for production:
   - Multi-stage build (builder + runtime)
   - Install only production dependencies
   - Run as non-root user
   - Health check built in
   - Proper signal handling for graceful shutdown

2. Create ui/staff-portal/Dockerfile:
   - Build React app
   - Serve with nginx
   - nginx.conf with proper caching headers and SPA fallback

3. Create ui/provider-portal/Dockerfile:
   - Same as staff portal

4. Create docker-compose.prod.yml with:
   - API server (gunicorn + uvicorn workers, 4 workers)
   - Celery worker (4 concurrency)
   - Celery beat
   - Staff portal (nginx, port 3000)
   - Provider portal (nginx, port 3001)
   - Nginx reverse proxy (port 80/443) routing:
     - rcm.aetheraonline.com/api/* → API server
     - rcm.aetheraonline.com/* → Staff portal
     - portal.rcm.aetheraonline.com/* → Provider portal
   - PostgreSQL with persistent volume
   - Redis with persistence
   - Qdrant with persistent volume
   - MinIO with persistent volume

5. Create config/nginx/nginx.conf:
   - SSL/TLS termination (Cloudflare handles this)
   - Proxy headers (X-Real-IP, X-Forwarded-For)
   - Security headers (HSTS, X-Frame-Options, CSP)
   - Gzip compression
   - Rate limiting at nginx level too
   - Health check endpoint passthrough

6. Create scripts/deploy.sh:
   - Pull latest code
   - Build all Docker images
   - Run migrations
   - Seed reference data
   - Restart services with zero downtime

Test locally: docker compose -f docker-compose.prod.yml up --build
Verify all services start and API responds at http://localhost/api/v1/health
```

PROMPT_10B:
```
Set up Cloudflare deployment configuration.

Create config/cloudflare/ directory with:

1. DNS Configuration docs (manual steps):
   - A record: rcm.aetheraonline.com → server IP
   - CNAME: portal.rcm.aetheraonline.com → rcm.aetheraonline.com
   - Proxy status: Proxied (orange cloud) for DDoS protection
   - SSL/TLS: Full (strict) mode

2. Create a Cloudflare Pages or Workers config if applicable,
   OR document the VPS deployment approach:

   Option A (Recommended for this project): Deploy to a VPS
   - Provision a VPS (DigitalOcean, Hetzner, or AWS EC2)
   - Minimum: 4 vCPU, 8GB RAM, 80GB SSD
   - Install Docker + Docker Compose
   - Clone repo, copy .env.prod, run docker compose -f docker-compose.prod.yml up -d
   - Point Cloudflare DNS to VPS IP

   Option B: Cloudflare Tunnel (no public IP needed)
   - Create cloudflared tunnel config
   - Route rcm.aetheraonline.com through tunnel to localhost:80

3. Create config/cloudflare/tunnel.yml:
   tunnel: <tunnel-id>
   credentials-file: /etc/cloudflared/credentials.json
   ingress:
     - hostname: rcm.aetheraonline.com
       service: http://localhost:80
     - hostname: portal.rcm.aetheraonline.com
       service: http://localhost:80
     - service: http_status:404

4. Create scripts/setup_server.sh:
   - Install Docker on fresh Ubuntu server
   - Install cloudflared
   - Clone repo
   - Set up systemd services for docker compose and cloudflared
   - Enable automatic restarts

5. Create .github/workflows/deploy.yml:
   - On push to main branch
   - SSH into server
   - Pull latest code
   - Rebuild and restart Docker services
   - Run healthcheck
   - Notify on failure

Document everything in docs/DEPLOYMENT.md
```

AFTER PHASE 10:
```powershell
git add .
git commit -m "Phase 10: Docker production config, Cloudflare deployment"
git push origin main
```


# ═══════════════════════════════════════════════════════════════
# PHASE 11: FINAL VERIFICATION
# ═══════════════════════════════════════════════════════════════

PROMPT_FINAL:
```
Run the COMPLETE verification suite. Do not stop until everything passes.

1. Run ALL tests:
   python -m pytest tests/ -v --tb=short
   MUST BE: 100% pass, 0 failures

2. Run coverage:
   python -m pytest tests/ --cov=src --cov-report=term-missing
   Report the coverage percentage

3. Start the full stack locally:
   docker compose up -d
   Wait 30 seconds for services to start

4. Run healthcheck:
   python scripts/healthcheck.py

5. Test critical API flows:
   - Login as admin → get JWT
   - Create a practice
   - Add a provider
   - Submit a charge
   - Verify claim lifecycle

6. Test both frontends build:
   cd ui/staff-portal && npm run build
   cd ui/provider-portal && npm run build

7. Check security:
   - All endpoints require auth (except /health, /ready, /login)
   - Security headers present on all responses
   - PHI not in any error messages
   - .env not committed to git

Print FINAL REPORT:
- Total tests: X passed, 0 failed
- Code coverage: X%
- Total API endpoints: X
- Total database tables: X
- Both frontends build: YES
- Security checks: ALL PASSED
- Docker full stack: RUNNING

If ANYTHING fails, fix it. Do not stop until this report shows all green.
```


# ═══════════════════════════════════════════════════════════════
# PRODUCTION STARTUP COMMANDS (After deployment to server)
# ═══════════════════════════════════════════════════════════════

```bash
# On your production server:

# 1. Clone and configure
git clone https://github.com/kk078/rcm-ai-platform.git
cd rcm-ai-platform
cp .env.example .env.prod
# Edit .env.prod with production values (real API keys, strong passwords)

# 2. Start everything
docker compose -f docker-compose.prod.yml up -d

# 3. Run migrations
docker compose -f docker-compose.prod.yml exec api alembic upgrade head

# 4. Seed reference data
docker compose -f docker-compose.prod.yml exec api python scripts/seed_reference_data.py

# 5. Create admin user
docker compose -f docker-compose.prod.yml exec api python scripts/create_admin.py

# 6. Verify
curl https://rcm.aetheraonline.com/api/v1/health

# Your app is live at:
# Staff Portal:    https://rcm.aetheraonline.com
# Provider Portal: https://portal.rcm.aetheraonline.com
# API Docs:        https://rcm.aetheraonline.com/api/docs (disable in production)
```


# ═══════════════════════════════════════════════════════════════
# DAILY DEVELOPMENT WORKFLOW (After initial setup)
# ═══════════════════════════════════════════════════════════════

```powershell
# 1. Open PowerShell, navigate to project
cd C:\Projects\rcm-ai-platform

# 2. Activate virtual environment
.\.venv\Scripts\Activate.ps1

# 3. Make sure Docker infra is running
docker compose up -d postgres redis qdrant minio

# 4. Start the API server (for local testing)
uvicorn src.api.main:app --reload --port 8000

# 5. In another terminal, start Celery (if needed)
celery -A src.infrastructure.queue.celery_app worker -l info

# 6. In another terminal, start frontend (if needed)
cd ui\staff-portal
npm run dev

# 7. Open Claude Code for development
claude

# 8. After making changes, always:
python -m pytest tests/ -v
git add .
git commit -m "description of changes"
git push origin main
```


# ═══════════════════════════════════════════════════════════════
# TROUBLESHOOTING
# ═══════════════════════════════════════════════════════════════

# Docker won't start:
#   → Make sure Docker Desktop is running (check system tray)
#   → Check WSL2 is enabled: wsl --status
#   → Restart Docker Desktop

# Port already in use:
#   → Find what's using it: netstat -ano | findstr :5432
#   → Kill it: taskkill /PID <PID> /F

# Python venv activation fails:
#   → Run: Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
#   → Then retry: .\.venv\Scripts\Activate.ps1

# Database connection refused:
#   → Check postgres is running: docker compose ps
#   → Check port: docker compose port postgres 5432
#   → Restart: docker compose restart postgres

# Claude Code session expired:
#   → Re-paste PROMPT_0_CONTEXT at the start
#   → Tell it which phase you're on: "We completed Phase X. Continue with Phase Y."

# Tests fail after changes:
#   → Tell Claude Code: "These tests are failing: [paste output]. Fix them."

# Out of disk space (Docker):
#   → Clean Docker: docker system prune -a
#   → This removes unused images/containers. Re-run docker compose up -d after.

# Claude Code hits usage limit:
#   → Wait for the reset window
#   → Start new session with PROMPT_0_CONTEXT
#   → Tell it which phase/prompt you're on
