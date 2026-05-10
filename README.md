# MedClaim AI — Intelligent Revenue Cycle Management Platform

## Overview

MedClaim AI is an end-to-end AI-powered Revenue Cycle Management (RCM) platform that automates medical coding, claim submission, payment posting, and denial management. It combines large language models (Claude API), rules engines, and ML models to maximize clean claim rates and revenue recovery.

## Architecture Summary

```
┌─────────────────────────────────────────────────────────────────┐
│                        FRONTEND (React)                         │
│  Dashboard │ Coding Workbench │ Denials Queue │ Payment Center  │
└──────────────────────────┬──────────────────────────────────────┘
                           │ REST + WebSocket
┌──────────────────────────▼──────────────────────────────────────┐
│                      API GATEWAY (FastAPI)                       │
│         Auth │ Rate Limiting │ Audit Logging │ HIPAA Middleware  │
└──────────────────────────┬──────────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────────┐
│                    ORCHESTRATION LAYER                           │
│              Celery Task Queue + Event Bus                       │
└───┬──────────┬──────────┬──────────┬──────────┬─────────────────┘
    │          │          │          │          │
    ▼          ▼          ▼          ▼          ▼
┌────────┐┌────────┐┌────────┐┌────────┐┌──────────┐
│CODING  ││BILLING ││PAYMENT ││DENIAL  ││PAYER     │
│ENGINE  ││ENGINE  ││POSTING ││MANAGER ││INTEL     │
│        ││        ││        ││        ││          │
│- NLP   ││- Claim ││- ERA   ││- Root  ││- Rules   │
│- ICD10 ││  Scrub ││  835   ││  Cause ││- Fees    │
│- CPT   ││- NCCI  ││- Match ││- Appeal││- Policies│
│- HCPCs ││- Edits ││- Recon ││  Gen   ││- LCD/NCD │
└───┬────┘└───┬────┘└───┬────┘└───┬────┘└────┬─────┘
    │         │         │         │           │
    ▼         ▼         ▼         ▼           ▼
┌─────────────────────────────────────────────────────────────────┐
│                     AI / ML LAYER                                │
│  Claude API (RAG) │ Fine-tuned Models │ Classification Models   │
│  Vector DB (Qdrant) │ Embedding Pipeline │ Feedback Loop        │
└──────────────────────────┬──────────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────────┐
│                     DATA LAYER                                   │
│  PostgreSQL (Claims/Patients) │ Redis (Cache/Sessions)          │
│  Qdrant (Embeddings) │ S3 (Documents) │ TimescaleDB (Analytics) │
└──────────────────────────┬──────────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────────┐
│                  INTEGRATION LAYER                               │
│  HL7/FHIR │ EDI 837/835/277/999 │ Clearinghouse APIs           │
│  EHR Connectors (Epic/Cerner) │ Payer Portals                  │
└─────────────────────────────────────────────────────────────────┘
```

## Tech Stack

| Layer              | Technology                                      |
|--------------------|------------------------------------------------|
| Frontend           | React 18 + TypeScript + Tailwind + shadcn/ui   |
| API                | FastAPI (Python 3.12)                           |
| Task Queue         | Celery + Redis                                  |
| Primary DB         | PostgreSQL 16 + SQLAlchemy ORM                  |
| Vector DB          | Qdrant (coding guidelines, payer policies)      |
| Cache              | Redis                                           |
| AI/LLM             | Anthropic Claude API (claude-sonnet-4-20250514)    |
| Embeddings         | Voyage AI or OpenAI text-embedding-3-large      |
| Object Storage     | S3-compatible (MinIO for local dev)             |
| Analytics DB       | TimescaleDB (time-series denial/payment data)   |
| EDI Processing     | Custom Python EDI parser (X12)                  |
| FHIR               | HAPI FHIR client                                |
| Auth               | OAuth2 + JWT + RBAC                             |
| Deployment         | Docker + Kubernetes                             |
| CI/CD              | GitHub Actions                                  |
| Monitoring         | Prometheus + Grafana + Sentry                   |

## Quick Start

```bash
# 1. Clone and install
git clone <repo-url> && cd rcm-ai-platform
cp .env.example .env  # Fill in API keys

# 2. Start infrastructure
docker-compose up -d postgres redis qdrant minio

# 3. Run migrations
python scripts/migrate.py

# 4. Seed reference data (ICD-10, CPT, NCCI edits, payer rules)
python scripts/seed_reference_data.py

# 5. Build vector indices
python scripts/build_vector_index.py

# 6. Start API server
uvicorn src.api.main:app --reload

# 7. Start Celery workers
celery -A src.infrastructure.queue.celery_app worker -l info

# 8. Start frontend
cd ui && npm install && npm run dev
```

## Module Overview

See `/docs/` for detailed documentation on each module:
- `ARCHITECTURE.md` — Full system architecture deep dive
- `DATA_MODEL.md` — Database schema and relationships
- `CODING_ENGINE.md` — Medical coding AI pipeline
- `BILLING_ENGINE.md` — Claim scrubbing and submission
- `PAYMENT_POSTING.md` — ERA/835 processing
- `DENIAL_MANAGEMENT.md` — Denial workflow and appeal generation
- `PAYER_INTELLIGENCE.md` — Payer rules and fee schedule management
- `COMPLIANCE.md` — HIPAA, security, and audit requirements
- `API_REFERENCE.md` — REST API documentation
- `DEPLOYMENT.md` — Production deployment guide

## Compliance

This platform is designed for HIPAA compliance:
- All PHI encrypted at rest (AES-256) and in transit (TLS 1.3)
- Role-based access control with minimum necessary principle
- Complete audit trail for every data access and modification
- BAA-compliant AI API usage (Anthropic HIPAA-eligible tier)
- PHI redaction pipeline before any external API calls
- Automatic session timeout and access logging
