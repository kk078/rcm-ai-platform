# Architecture Deep Dive — Third-Party Billing Company Platform

## What This Platform Is

This is the **operating system for a third-party medical billing company** that manages
revenue cycle for multiple provider clients. Every feature is designed around:

- You manage 10, 50, 200+ provider practices simultaneously
- Each practice has its own providers, payers, fee schedules, and specialties
- Your billing staff works across multiple client accounts
- Providers need visibility into their claims without calling you
- You need to demonstrate your value to retain clients
- You bill your clients based on collections or per-claim fees
- Data between clients must be strictly isolated (HIPAA + business)

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                    PROVIDER PORTAL (React)                           │
│  Client Dashboard │ Claim Status │ Charge Entry │ Reports │ Inbox   │
│  (Each provider sees ONLY their own practice data)                  │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
┌──────────────────────────────┼──────────────────────────────────────┐
│                    INTERNAL STAFF PORTAL (React)                     │
│  Workbench │ All-Client Dashboard │ Assignments │ Productivity      │
│  Coding Queue │ Posting Queue │ Denial Queue │ Client Management    │
│  (Your billing company's staff sees their assigned clients)         │
└──────────────────────────────┬──────────────────────────────────────┘
                               │ REST + WebSocket
┌──────────────────────────────▼──────────────────────────────────────┐
│                      API GATEWAY (FastAPI)                           │
│  Auth │ Tenant Isolation │ RBAC │ Audit │ Rate Limiting             │
│  ┌────────────────────────────────────────────────────────┐         │
│  │  TENANT MIDDLEWARE — Every request scoped to practice   │         │
│  │  Internal users: can access assigned practices          │         │
│  │  Provider users: can ONLY access their own practice     │         │
│  └────────────────────────────────────────────────────────┘         │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────────┐
│                    MULTI-TENANT CORE ENGINES                        │
│  All data operations filtered by practice_id (tenant)               │
└──┬────────┬────────┬────────┬────────┬────────┬────────┬───────────┘
   │        │        │        │        │        │        │
   ▼        ▼        ▼        ▼        ▼        ▼        ▼
┌──────┐┌──────┐┌──────┐┌──────┐┌──────┐┌──────┐┌──────────────┐
│CLIENT││CHARGE││CODING││CLAIM ││PYMT  ││DENIAL││REPORTING &   │
│MGMT  ││INTAKE││ENGINE││ENGINE││POST  ││MGMT  ││CLIENT BILLING│
│      ││      ││      ││      ││      ││      ││              │
│Onbrd ││Super-││AI    ││Scrub ││ERA   ││Class-││Practice Rpts │
│Config││bills ││Code  ││Submit││835   ││ify   ││Collection Rpt│
│Payers││Batch ││Sug-  ││Track ││Match ││Prior-││Statements    │
│Fees  ││Entry ││gest  ││EDI   ││Auto  ││itize ││Your Invoices │
│SLAs  ││EHR   ││Review││      ││Post  ││Appeal││Productivity  │
└──────┘└──────┘└──────┘└──────┘└──────┘└──────┘└──────────────┘
   │        │        │        │        │        │        │
   ▼        ▼        ▼        ▼        ▼        ▼        ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    AI / ML LAYER                                     │
│  Claude API (RAG) │ Vector DB (Qdrant) │ ML Models                  │
│  PHI Redaction │ Per-Practice Context │ Cross-Practice Learning     │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────────┐
│                    DATA LAYER (Multi-Tenant)                        │
│  PostgreSQL (Row-Level Security by practice_id)                     │
│  Redis (Cache per tenant) │ Qdrant │ S3 (Prefix per practice)      │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────────┐
│                    INTEGRATION LAYER                                 │
│  EDI 837/835/270/271 │ Multiple Clearinghouses │ EHR Connectors     │
│  Practice Mgmt System Imports │ Superbill Intake │ Fax/Document     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 1. Multi-Tenancy Model

Every row in the database that contains practice-specific data has a `practice_id` column.
PostgreSQL Row-Level Security (RLS) enforces isolation at the database level.

```sql
ALTER TABLE claims ENABLE ROW LEVEL SECURITY;
CREATE POLICY claims_tenant_isolation ON claims
    USING (practice_id = current_setting('app.current_practice_id')::UUID);
SET app.current_practice_id = '<practice-uuid>';
```

### Tenant Hierarchy
```
Billing Company (you — single deployment)
  └── Practice (client)
        ├── Providers (doctors)
        ├── Locations / Facilities
        ├── Payer Enrollments + Fee Schedules
        ├── Patients
        ├── Encounters → Claims → Payments → Denials
        └── Portal Users (practice staff who log in)
```

---

## 2. Two Portals, Two Audiences

### Internal Staff Portal (Your Billing Team)

Cross-client worklists, client switching, assignment management, productivity tracking.

| Role | Access |
|------|--------|
| Company Admin | Everything — client management, staff, billing |
| Billing Manager | Assigned practices — all RCM functions + staff assignments |
| Coder | Assigned practices — coding queue |
| Payment Poster | Assigned practices — ERA, matching |
| Denial Analyst | Assigned practices — denial worklist, appeals |
| QA Reviewer | All practices — audit, compliance |

### Provider Portal (Your Clients)

Each practice gets a portal showing only their data. This is your retention tool.

| Role | Access |
|------|--------|
| Practice Admin | Full dashboard, reports, user management |
| Provider/Doctor | Own patients' claims, charge entry |
| Office Manager | Charge entry, claim status, reports |
| Front Desk | Charge entry, patient demographics |

**Provider portal features:**
- Dashboard with their KPIs (charges, collections, AR, denial rate)
- Real-time claim status tracker
- Charge entry / superbill submission
- Document upload (clinical notes, EOBs)
- Denial notifications and appeal status
- Monthly reports and statements
- Secure messaging with your billing team

---

## 3. Charge Intake — How Work Gets To You

### Intake Methods
1. **Superbill Upload** — PDF/image scan → AI extraction
2. **Portal Charge Entry** — Guided form with specialty-specific code favorites
3. **Batch Import** — CSV/Excel from practice management systems
4. **EHR Integration** — HL7/FHIR feeds from Epic, Cerner, eCW, athenahealth
5. **Fax Intake** — Fax-to-digital with OCR processing

### Intake Pipeline
```
Charge arrives → Validate completeness → Missing info? → Portal message to provider
                                       → Complete? → Route to coding or billing queue
```

---

## 4. Client Management Module

### Client Onboarding Workflow
1. Create Practice (name, TIN, group NPI, address, specialty, contacts)
2. Add Providers (individual NPIs, credentials, taxonomy codes)
3. Configure Payer Enrollments (payer IDs, group numbers, ERA/EFT status)
4. Load Fee Schedules (contracted rates per payer)
5. Set Up Clearinghouse (EDI sender/receiver IDs)
6. Configure Portal Access (provider portal users)
7. Set Service Agreement (fee model, SLAs, included services)
8. Initial Data Migration (open AR, patients, historical data)

### Service Agreement Configuration
```
fee_model: "percentage" | "per_claim" | "flat_fee" | "hybrid"
fee_rate: 5.5%  or  $4.50/claim  or  $3000/month
services_included: [coding, billing, posting, denials, credentialing]
sla_clean_claim_rate: 95%
sla_days_to_submit: 2
sla_appeal_turnaround_days: 5
```

---

## 5. Claim Lifecycle (Third-Party Billing Flow)

```
PROVIDER'S OFFICE                        YOUR BILLING COMPANY
─────────────────                        ────────────────────
Patient visit
  → Provider completes note
  → Superbill / charge entry ──────────→ INTAKE QUEUE
                                              │
                                        Validate completeness
                                        Missing info? → Message provider
                                              │
                                        CODING QUEUE (if needed)
                                        AI suggests → Coder reviews
                                              │
                                        BILLING QUEUE
                                        Scrub → Fix → Generate 837 → Submit
                                              │
Provider sees status ←─────────────── TRACKING
in portal                              Monitor 277 responses
                                              │
                                        PAYMENT POSTING
                                        ERA/835 → Match → Post → Route denials
                                              │
Provider gets ←─────────────────────── DENIAL MANAGEMENT
denial alert                            Classify → Prioritize → Appeal
                                              │
Provider gets ←─────────────────────── REPORTING
monthly report                          Collection report → Your invoice
```

---

## 6. Reporting & Client Billing

### Reports FOR Your Clients
- Monthly Collection Report (charges, payments, adjustments, net)
- AR Aging Report (0-30, 31-60, 61-90, 91-120, 120+)
- Denial Summary (rate, reasons, outcomes)
- Payer Performance (speed, denial rates)
- Provider Productivity (charges per provider)

### Reports FOR Your Business
- Client Profitability (revenue vs cost per client)
- Staff Productivity (claims per staff member)
- SLA Compliance per client
- Pipeline Dashboard (charges in pipeline, projected revenue)
- AI Performance metrics

### Client Billing (How You Get Paid)
Monthly cycle: calculate collections per practice → apply fee model → generate invoice → track payment

---

## 7. Internal Workflow Management

### Cross-Client Work Queues
Each queue pulls from ALL assigned practices, sorted by priority:

- **Intake Queue**: New charges awaiting review (oldest first, SLA deadline)
- **Coding Queue**: Encounters needing codes (lowest AI confidence first)
- **Billing Queue**: Claims ready for scrub + submit (timely filing deadline)
- **Posting Queue**: ERA files + unmatched payments (date received, amount)
- **Denial Queue**: Denials awaiting action (recovery probability × amount × deadline)
- **Follow-Up Queue**: Pending claims >30 days, appeal responses pending

### Auto-Assignment
Staff assigned to practices by specialty and workload. Managers configure rules.

---

## 8. Integration: Multiple Clearinghouses

```
Practice A → Availity    → Sender ID: PRACTICE_A_123
Practice B → Availity    → Sender ID: PRACTICE_B_456
Practice C → Change HC   → Sender ID: PRACTICE_C_789
```

ERA routing: parse ISA/GS headers → match payee TIN → route to correct practice tenant.

---

## 9. Multi-Tenant Security

### Isolation Layers
1. Database RLS on practice_id
2. API middleware sets tenant context from JWT
3. S3 prefix isolation per practice
4. Redis key prefixing by practice_id
5. Full audit trail of cross-tenant access

### Access Matrix
```
                    │ Own Practice │ Assigned Practices │ All Practices
────────────────────┼──────────────┼────────────────────┼──────────────
Provider Portal     │      ✓       │         ✗          │      ✗
Billing Staff       │      ✗       │         ✓          │      ✗
Billing Manager     │      ✗       │         ✓          │      ✗
Company Admin       │      ✗       │         ✗          │      ✓
QA Reviewer         │      ✗       │         ✗          │      ✓
```
