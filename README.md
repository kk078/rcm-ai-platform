# Aethera AI — Intelligent Revenue Cycle Management

**Aethera AI** is a production-grade, AI-powered Revenue Cycle Management (RCM) platform built for third-party medical billing companies and healthcare practices. It combines Ollama Cloud LLMs, a 9-pass claim scrubbing engine, RAG-powered coding assistance, and automated denial management to maximize clean claim rates and accelerate revenue recovery.

---

## Quick Start

### Prerequisites
- Docker + Docker Compose v2
- Python 3.12+
- Ollama Cloud API key
- Cloudflare account (for production)

### Development
```bash
cp .env.example .env
# Fill in OLLAMA_API_KEY and generate secrets:
python scripts/generate_secrets.py

docker compose up -d
# API available at http://localhost:8000
# Docs at http://localhost:8000/api/docs (when APP_DEBUG=true)
```

### Production (Cloudflare Tunnel)
See [DEPLOY.md](DEPLOY.md) for the full deployment guide.

```bash
./scripts/deploy.sh
# Deploys to https://rcm.aetherahealthcare.com
```

---

## Architecture

| Layer | Technology |
|-------|-----------|
| API | FastAPI (Python 3.12), async/await |
| AI | Ollama Cloud (qwen3-coder:480b-cloud + deepseek-v3.1:671-cloud) |
| RAG | Qdrant vector DB + Voyage AI embeddings |
| Database | PostgreSQL 16 + SQLAlchemy async |
| Queue | Celery + Redis |
| Storage | MinIO (S3-compatible) |
| Frontend | React 18 + TypeScript + Vite + Tailwind CSS |
| Auth | JWT + TOTP MFA + bcrypt + Redis token blacklist |
| Deployment | Docker + Cloudflare Tunnel |

---

## Key Features

- **AI Medical Coding** — RAG-powered ICD-10/CPT code suggestions via Ollama Cloud
- **9-Pass Claim Scrubber** — NCCI, MUE, modifier, POS, age/gender, payer-specific checks
- **Denial Management** — AI classification, automated appeal drafting, priority scoring
- **Payment Posting** — ERA/835 parsing, auto-reconciliation
- **EDI Processing** — 837P/837I submission, 835 posting
- **Multi-Tenant** — Practice-level row isolation with AES-256 PHI encryption
- **HIPAA Compliant** — Audit logging, session timeout, PHI redaction before AI calls

---

## Environment Variables

See `.env.example` for a full annotated list. Critical variables:

| Variable | Description |
|----------|-------------|
| `OLLAMA_API_KEY` | Ollama Cloud API key |
| `JWT_SECRET_KEY` | 32-byte hex secret (`python -c "import secrets; print(secrets.token_hex(32))"`) |
| `PHI_ENCRYPTION_KEY` | Fernet key for PHI column encryption |
| `TUNNEL_TOKEN` | Cloudflare Tunnel token |
| `DATABASE_URL` | PostgreSQL async connection string |

---

## License

Proprietary — Aethera Healthcare. All rights reserved.
