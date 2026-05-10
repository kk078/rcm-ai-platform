# CLAUDE_CODE_INSTRUCTIONS.md
# Master Implementation Guide — Third-Party Medical Billing Platform

> **This file is the build plan.** Give it to Claude Code along with the full project.
> The architecture scaffolding, API stubs, data models, middleware, AI service,
> EDI parser, and rules engine are already in place. Claude Code implements the logic.

---

## WHAT THIS IS

MedClaim AI is the operating system for a **third-party medical billing company**
that manages revenue cycle for multiple provider practices. It is NOT a single-practice
tool. Everything is multi-tenant with strict data isolation.

**Two portals:**
- **Internal Staff Portal** — Your coders, billers, posters, denial analysts
- **Provider Portal** — Your clients (doctors/practices) see their claims, submit charges, view reports

**Core business flow:**
Provider submits charges → You code, scrub, submit claims → Payer pays or denies →
You post payments, work denials, appeal → Provider sees results → You invoice the provider

---

## CRITICAL ARCHITECTURAL DECISIONS

### Multi-Tenancy: Row-Level Security
Every table with practice-specific data has `practice_id UUID NOT NULL`.
PostgreSQL RLS enforces isolation at the DB level. The `TenantMiddleware`
(src/api/middleware/tenant.py) sets the tenant context per request.

**Every single DB query in this application must be tenant-aware.
This is not optional. A data leak between practices is a HIPAA violation
AND a business-ending event.**

### Two User Types
- `user_type = "internal"` → Your billing company staff. Has `internal_role`.
  Access controlled by `staff_assignments` table (which practices they're assigned to).
- `user_type = "provider"` → Practice portal users. Has `provider_role` and `practice_id`.
  Can ONLY see their own practice's data. Ever.

### Request Headers
Internal staff send `X-Practice-ID` header to set active practice context when
working on a specific client. Without it, they get cross-practice data from all
assigned practices (for unified work queues).

---

## BUILD ORDER (Follow this sequence)

### Phase 1: Foundation + Multi-Tenancy
```
1.1   Database models with Alembic migrations
      - Start with: practices, users, staff_assignments, permissions
      - Then: patients, providers, encounters (all with practice_id)
      - Then: claims, claim_lines, claim_diagnoses
      - Then: payment_batches, payment_lines, adjustments
      - Then: denials, appeals, coding_sessions
      - Then: charge_entries, charge_batches
      - Then: portal_messages, portal_notifications
      - Then: work_queue_items, staff_productivity
      - Then: service_agreements, payer_enrollments, fee_schedules
      - Then: client_invoices
      - Then: audit_logs
      REFERENCE: docs/DATA_MODEL.md + docs/DATA_MODEL_MULTITENANT.md

1.2   Row-Level Security policies on ALL tenant tables
      Apply RLS as documented in DATA_MODEL_MULTITENANT.md

1.3   Authentication (JWT + RBAC)
      - Login returns JWT with: user_id, user_type, internal_role OR provider_role,
        practice_id (for provider users), assigned_practice_ids (for internal users)
      - Refresh tokens
      - MFA (TOTP)
      - Password policy (12+ chars, bcrypt work factor 12)
      - Account lockout after 5 failed attempts

1.4   Tenant middleware (already scaffolded in src/api/middleware/tenant.py)
      - Wire into auth: extract user info from JWT, set tenant context
      - Implement set_rls_context() call on every DB session

1.5   HIPAA audit logging (fully implement TODOs in main.py)
      - Log every request with user, resource, action, timestamp, IP
      - Flag PHI access
      - Immutable audit log table

1.6   PHI encryption utilities
      - Field-level AES-256 for SSN, DOB, TIN
      - Key management (rotate without re-encrypting everything)

1.7   S3/MinIO storage service (per-practice prefix isolation)
1.8   Redis cache service (key prefix by practice_id)
1.9   Base error handling + response schemas
```

### Phase 2: Client Management (NEW — Critical for Third-Party Billing)
```
2.1   Practice CRUD (create, list, get, update, activate, suspend, terminate)
2.2   Practice location management
2.3   Provider management (add providers to practices)
2.4   Payer enrollment configuration per practice
2.5   Fee schedule import (CSV/Excel → fee_schedule_rates)
2.6   Service agreement configuration (fee model, SLAs)
2.7   Staff assignment management (assign internal users to practices)
2.8   Portal user management (create provider portal accounts)
2.9   Onboarding checklist tracking
2.10  Data migration endpoints (patient import, open AR import)
      IMPLEMENT: src/api/routes/client_management.py
```

### Phase 3: Reference Data
```
3.1   ICD-10-CM code database (load from CMS files)
3.2   CPT/HCPCS code database
3.3   NCCI edit pairs (Column 1/Column 2) from CMS quarterly releases
3.4   MUE values from CMS
3.5   CARC/RARC code descriptions
3.6   Place of Service codes
3.7   Payer master data (major commercial + Medicare + Medicaid)
```

### Phase 4: Charge Intake (NEW — How Providers Send You Work)
```
4.1   Charge entry via portal (provider submits encounter + codes)
4.2   Superbill upload with AI extraction (OCR + Claude)
4.3   Batch import from CSV/Excel
4.4   Clinical document upload → route to coding queue
4.5   Charge validation pipeline (patient, provider, payer, codes)
4.6   Missing info request workflow (message provider via portal)
4.7   Route to coding queue or billing queue based on completeness
4.8   Intake dashboard for internal staff
      IMPLEMENT: src/api/routes/charge_intake.py
```

### Phase 5: AI/ML Infrastructure
```
5.1   Vector store initialization (Qdrant collections)
5.2   Embedding pipeline — coding guidelines
5.3   Embedding pipeline — payer policies per practice
5.4   PHI redaction (expand Presidio NER integration)
5.5   Implement all AIService methods (src/core/nlp/ai_service.py)
5.6   Prompt template testing
5.7   Token usage tracking per practice (for cost allocation)
```

### Phase 6: Medical Coding Engine
```
6.1   Clinical document ingestion (PDF, TXT, HL7 CDA)
6.2   NLP entity extraction
6.3   Code suggestion workflow (RAG → Claude → validate → rank)
6.4   Coding session management (creates work_queue_item)
6.5   Code approval with diff tracking
6.6   Route approved codes → claim assembly
      IMPLEMENT: src/api/routes/coding.py
```

### Phase 7: Claims & Billing Engine
```
7.1   Claim assembly from charge_entry + approved codes
7.2   Full ClaimScrubber implementation (src/core/rules_engine/scrubber.py):
      - Load real NCCI edits from reference data
      - Load real MUE data
      - Complete modifier logic
      - Implement duplicate detection (DB query by practice)
      - Payer-specific rule evaluation from payer_enrollments
7.3   AI denial risk prediction
7.4   EDI 837P/837I generator (full X12 5010 per practice's clearinghouse config)
7.5   Clearinghouse submission (route by practice → payer enrollment → clearinghouse)
7.6   277 / 999 response processing
      IMPLEMENT: src/api/routes/claims.py
```

### Phase 8: Payment Posting Engine
```
8.1   ERA/835 parsing (src/services/edi/parser.py — extend edge cases)
8.2   ERA routing: parse payee TIN → match to practice_id
8.3   Payment matching (exact claim # match → fuzzy patient+DOS+CPT match)
8.4   Auto-posting (configurable rules per practice)
8.5   Underpayment detection (paid vs fee_schedule_rates for this practice+payer)
8.6   Denial routing → create denial record + work_queue_item
8.7   Reconciliation per practice
      IMPLEMENT: src/api/routes/payments.py
```

### Phase 9: Denial Management Engine
```
9.1   Denial intake (from payment posting + manual entry)
9.2   AI denial classification (CARC/RARC → category → root cause)
9.3   Priority scoring (recovery probability × amount × deadline)
9.4   Worklist generation (cross-practice for internal staff)
9.5   Appeal letter generation with practice-specific context
9.6   Appeal submission tracking
9.7   Denial pattern analysis per practice + cross-practice
      IMPLEMENT: src/api/routes/denials.py
```

### Phase 10: Work Queue System (NEW — Cross-Client Unified Queues)
```
10.1  Work queue item creation (triggered by other modules)
10.2  Priority calculation engine
10.3  SLA deadline calculation (from service_agreements)
10.4  Auto-assignment algorithm (by practice assignment + role + workload)
10.5  Queue operations (claim, release, complete, escalate, assign)
10.6  SLA breach detection (Celery beat job)
10.7  Productivity tracking (log time per queue item)
10.8  Staff workload dashboard
       IMPLEMENT: src/api/routes/work_queue.py
```

### Phase 11: Provider Portal
```
11.1  Portal dashboard (practice KPIs)
11.2  Claim status tracker (simplified view — no internal details)
11.3  Claim timeline visualization
11.4  Denial alerts + appeal status
11.5  Messaging (portal_messages) between practice and billing team
11.6  Notifications system (portal_notifications)
11.7  Reports: monthly collection, AR aging, denial summary, payer performance
11.8  Practice profile view
11.9  Invoice viewing + download
       IMPLEMENT: src/api/routes/provider_portal.py
```

### Phase 12: Client Billing & Invoicing (NEW — How You Get Paid)
```
12.1  Invoice generation per service agreement:
      - Calculate collections for period
      - Apply fee model (percentage, per-claim, flat, hybrid)
      - Apply minimum fee
      - Add line items (credentialing, special projects)
12.2  Batch invoice generation (all active practices)
12.3  Invoice PDF generation
12.4  Send invoice (portal + email)
12.5  Payment tracking
12.6  Company revenue dashboard
12.7  Client profitability report (revenue vs staff cost per practice)
12.8  Overdue invoice management
       IMPLEMENT: src/api/routes/client_billing.py
```

### Phase 13: Reporting & Analytics
```
13.1  Internal analytics dashboard (all-client overview)
13.2  Per-practice dashboards (KPIs by client)
13.3  SLA compliance reporting
13.4  Staff productivity reports
13.5  AI performance metrics (coding accuracy, appeal success)
13.6  Client health scorecards (flag at-risk clients)
13.7  Revenue cycle waterfall charts
13.8  AR aging reports (per practice and aggregate)
       IMPLEMENT: src/api/routes/analytics.py
```

### Phase 14: Frontend — Internal Staff Portal (React)
```
14.1  Project setup: Vite + React 18 + TypeScript + Tailwind + shadcn/ui
14.2  Auth: Login, MFA, role-based navigation
14.3  Client Switcher (top nav — select active practice or "All Clients")
14.4  All-Client Dashboard: health of every practice at a glance
14.5  Work Queues:
      - Unified queue view (all assigned practices)
      - Filter by queue type, practice, status
      - Claim/release/complete actions
      - SLA indicators (green/yellow/red)
14.6  Charge Intake:
      - Intake queue with validation status
      - Charge detail editor
      - "Request info" button → sends portal message
14.7  Coding Workbench:
      - Document viewer + AI code suggestions side-by-side
      - Code search/lookup
      - Approve/modify flow
14.8  Claims Management:
      - Claim list with scrub results
      - Batch submission
      - Status tracking
14.9  Payment Posting:
      - ERA upload
      - Payment matching review
      - Unmatched queue
      - Reconciliation dashboard
14.10 Denial Management:
      - Priority worklist
      - Denial detail + appeal editor
      - Pattern analytics
14.11 Client Management:
      - Practice list + onboarding wizard
      - Practice detail (providers, payers, fee schedules, agreement)
      - Staff assignment manager
14.12 Client Billing:
      - Invoice list + generation
      - Revenue dashboard
      - Profitability view
14.13 Settings & Admin:
      - User management (internal staff)
      - Role/permission management
      - System configuration
```

### Phase 15: Frontend — Provider Portal (React — Separate App)
```
15.1  Separate React app (different build, different subdomain: portal.medclaim.ai)
15.2  Auth: Login, MFA
15.3  Dashboard: Practice KPIs, AR aging, recent activity
15.4  Charge Entry:
      - Manual charge form with favorite codes
      - Superbill upload
      - Batch import
      - Document upload
15.5  Claim Tracker: search, filter, status timeline
15.6  Denial Alerts: list, detail, upload supporting docs
15.7  Messages: inbox, compose, reply
15.8  Reports: monthly collection, aging, denial, payer performance
15.9  Invoices: view, download PDF
15.10 Practice Settings: providers, locations, users
```

---

## CRITICAL IMPLEMENTATION NOTES

### Multi-Tenancy (Non-Negotiable)
- EVERY DB query must filter by practice_id (RLS handles this if set_rls_context is called)
- EVERY API endpoint must verify tenant access before returning data
- EVERY Celery task must set tenant context before processing
- S3 keys: `{practice_id}/{document_type}/{file_id}`
- Redis keys: `practice:{practice_id}:{key_name}`
- NEVER join data across practices in user-facing queries
- Admin reports that aggregate across practices must not expose individual patient data

### Provider Portal Security
- Provider portal is a SEPARATE API prefix (/api/v1/portal/)
- Provider JWT tokens contain practice_id — this CANNOT be overridden
- Provider users NEVER see: internal notes, staff assignments, scrub details, work queue info
- Provider endpoints return simplified, client-friendly data models
- Provider users can ONLY write: charges, messages, document uploads
- Provider users can ONLY read: their own claims, denials, reports, invoices, notifications

### HIPAA Compliance
- All PHI encrypted at rest (AES-256) and in transit (TLS 1.3)
- Audit log every PHI access with practice_id context
- PHI redaction before ANY external API call (Claude, clearinghouse)
- Session timeout 15 minutes
- BAA with Anthropic for Claude API usage
- 7-year audit log retention

### Work Queue Design
- Queue items are created automatically by other modules (e.g., charge intake creates intake queue item)
- Priority is recalculated periodically (SLA deadline proximity changes priority)
- SLA breaches trigger alerts to managers
- Completed items log time_spent for productivity tracking
- Each module's "route to" actions create the appropriate queue item

### Event Flow (How Modules Connect)
```
charge_entry.created       → work_queue_item(type=intake) created
charge_entry.validated     → if needs_coding: work_queue_item(type=coding)
                           → if ready: work_queue_item(type=billing)
coding_session.approved    → charge_entry → encounter → claim created
                           → work_queue_item(type=billing) created
claim.scrubbed (clean)     → work_queue_item(type=billing).completed
                           → claim submitted
era.received               → match to practice by TIN
                           → work_queue_item(type=posting) created
payment.denial_found       → denial created
                           → work_queue_item(type=denial) created
denial.appeal_generated    → work_queue_item(type=denial) updated
appeal.submitted           → follow-up scheduled
claim.paid                 → portal_notification to practice
claim.denied               → portal_notification to practice
invoice.sent               → portal_notification to practice
info.requested             → portal_message + portal_notification
```

---

## FILE STRUCTURE

```
rcm-ai-platform/
├── README.md
├── CLAUDE_CODE_INSTRUCTIONS.md       ← YOU ARE HERE
├── docker-compose.yml
├── pyproject.toml
├── .env.example
├── docs/
│   ├── ARCHITECTURE.md               ← Multi-tenant architecture
│   ├── DATA_MODEL.md                 ← Core tables
│   └── DATA_MODEL_MULTITENANT.md     ← Multi-tenant additions
├── src/
│   ├── config.py
│   ├── api/
│   │   ├── main.py                   ← FastAPI app + all middleware
│   │   ├── middleware/
│   │   │   └── tenant.py             ← Tenant isolation middleware
│   │   └── routes/
│   │       ├── auth.py
│   │       ├── claims.py             ← Billing engine
│   │       ├── coding.py             ← Coding engine
│   │       ├── denials.py            ← Denial management
│   │       ├── payments.py           ← Payment posting
│   │       ├── patients.py
│   │       ├── payers.py
│   │       ├── analytics.py
│   │       ├── client_management.py  ← Practice onboarding + config
│   │       ├── charge_intake.py      ← How providers send charges
│   │       ├── provider_portal.py    ← What providers see
│   │       ├── work_queue.py         ← Cross-client work queues
│   │       └── client_billing.py     ← How you invoice practices
│   ├── core/
│   │   ├── coding/
│   │   ├── billing/
│   │   ├── payment_posting/
│   │   ├── denial_management/
│   │   ├── client_management/
│   │   ├── charge_intake/
│   │   ├── provider_portal/
│   │   ├── reporting/
│   │   ├── nlp/
│   │   │   ├── ai_service.py         ← Claude API + RAG
│   │   │   ├── prompts.py            ← All prompt templates
│   │   │   ├── phi_redaction.py      ← PHI de-identification
│   │   │   └── vector_store.py       ← Qdrant RAG service
│   │   └── rules_engine/
│   │       └── scrubber.py           ← NCCI/MUE/modifier rules
│   ├── services/
│   │   ├── edi/
│   │   │   └── parser.py             ← X12 835/837 parser/generator
│   │   ├── fhir/
│   │   └── payer_intelligence/
│   └── infrastructure/
│       ├── database/
│       │   └── session.py
│       ├── queue/
│       │   └── celery_app.py
│       └── auth/
├── tests/
├── scripts/
├── config/
└── ui/
    ├── staff-portal/                  ← Internal staff React app
    └── provider-portal/               ← Provider client React app
```

---

## GET STARTED

1. `docker-compose up -d` to start infrastructure
2. Begin with Phase 1 — database models + multi-tenancy + auth
3. Phase 2 — Client management (you need practices before anything else works)
4. Work sequentially through each phase
5. Test tenant isolation at every step
6. Refer to docs/ for detailed data models and architecture
