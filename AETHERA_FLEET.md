# AETHERA FLEET MAP

> **Shared, synchronized doc.** Canonical copy lives in `D:\_aethera_shared\AETHERA_FLEET.md`.
> An identical copy is placed in every project root so any agent (or human) working
> inside a single folder understands the whole fleet. **Do not edit the per-project
> copies directly** — edit the canonical copy and re-run `D:\_aethera_shared\sync-docs.bat`.
> Last synced: see `SYNC_STAMP` at bottom.

This file is the single source of truth for how the Aethera applications fit together,
which ones depend on Docker, what ports they use, and how they reach the internet.

---

## 1. Cloudflare account (the backbone)

| Item | Value |
|---|---|
| Account ID | `2c268625d9e6e4c084ff296fcdf5f3bd` |
| Primary zone | `aetherahealthcare.com` (zone id `5a1a7671dcdc739688b76fb46c77a737`) |
| Plan | **Free** (per-zone WAF only; constraints documented in Aethera Sentinel) |
| NOT in this account | `aetheraonline.com` — different account, out of scope |

All public apps are **subdomains of `aetherahealthcare.com`**, served either by
Cloudflare Pages/Workers (serverless, always-on) or by a Cloudflare **Tunnel**
(`cloudflared`) that points back to the local Docker stack on this machine.

| Subdomain | Served by | Backed by project |
|---|---|---|
| `aetherahealthcare.com` (apex) | Pages | aetherahealthcare-website |
| `crm.` | Pages | aethera-crm |
| `os.` | Pages | rcm-ai-platform (frontend) |
| `rcm.` | Tunnel (`cfargotunnel`) | rcm-ai-platform (API, this machine's Docker) |
| `admin.` / `origin.` | Tunnel | rcm-ai-platform / admin tunnel |
| `kia.` | Pages + worker `kia-api-proxy` | (AI key proxy) |
| `ai.` / `agents.` | Workers | AIAgents |
| `*` (all) | WAF + monitor | Aethera Sentinel |

**Why this matters for the Docker problem:** `rcm.` / `admin.` reach this machine
through the `cloudflared` container. If Docker is down, those subdomains go dark even
though Pages-served subdomains (`crm.`, `os.` static, apex) keep working. The
serverless apps are independent of Docker; the RCM API and the agent workers are not.

---

## 2. Projects at a glance

| Project (folder) | What it is | Runtime | Needs local Docker? |
|---|---|---|---|
| **rcm-ai-platform** | Flagship RCM / medical-billing platform (FastAPI + Celery + AI) | Docker Compose | **YES** (core) |
| **AIAgents** | LangGraph supervisor + specialist billing agents | Docker Compose (`workers/`) + CF Workers | **YES** (workers) |
| **aethera-crm** | Healthcare provider CRM | Cloudflare Workers + Pages + D1 | No (serverless) |
| **aetherahealthcare-website** | Marketing site | Next.js + Cloudflare | No |
| **Aethera Sentinel** | Account-wide CF security + uptime monitor + AI-key proxy | Cloudflare Workers | No |
| **Aethera AI** | `healthcare-ai-agent` (early) | TBD | TBD |
| **ERA** | Payer remittance PDFs (data, not an app) | — | No |
| **Aethera Authenticator / OTP** | Placeholders (empty) | — | No |

---

## 3. The local container stack (what Docker actually runs)

Two Compose projects run on this Windows machine via Docker:

### 3a. `rcm-ai-platform/docker-compose.yml`
| Service | Image / build | Host port | Health |
|---|---|---|---|
| postgres | postgres:16-alpine | 5432 | healthcheck ✓ |
| redis | redis:7-alpine | 6379 | healthcheck ✓ |
| qdrant | qdrant/qdrant | 6333 | healthcheck ✓ |
| minio | minio/minio | 9000 / 9001 | healthcheck ✓ |
| api | build . (gunicorn/uvicorn) | 8000 | healthcheck ✓ |
| ai-agents | build (gunicorn main:app) | — | healthcheck ✓ |
| celery-worker | build (celery worker) | — | healthcheck ✓ |
| celery-beat | build (celery beat) | — | healthcheck ✓ |
| nginx | build | 8088 | healthcheck ✓ |
| cloudflared | cloudflare/cloudflared | — (tunnel) | — |

### 3b. `AIAgents/workers/docker-compose.yml`
| Service | Image / build | Host port | Health |
|---|---|---|---|
| db | postgres:15-alpine | — | healthcheck ✓ |
| redis | redis:7-alpine | 6379 | healthcheck ✓ |
| worker | build Dockerfile.worker (celery) | — | healthcheck ✓ |
| beat | build Dockerfile.beat (celery beat) | — | healthcheck ✓ |

> **Port collision note:** both stacks publish `redis` on host `6379`. Only one can
> bind it at a time. If both stacks must run together, change one mapping (see
> `SAFE_FAIL.md` §Port hygiene).

Plus standalone helper containers seen on this host: `litellm-proxy`
(127.0.0.1:4000) and `aethera-admin-tunnel` (cloudflared).

---

## 4. Runtime dependency chain

```
Internet ──► Cloudflare edge
              ├─ Pages/Workers  ──► crm. / os. / apex / ai. / agents.   (NO Docker)
              └─ Tunnel (cloudflared container) ──► nginx:8088 ──► api:8000
                                                          │
                            ┌─────────────────────────────┼───────────────┐
                            ▼              ▼               ▼               ▼
                        postgres        redis           qdrant          minio
                            ▲              ▲
                       celery-worker / celery-beat / ai-agents
```

If the **container engine** is down, everything below the Tunnel line is down.
The fix and the self-healing for that engine live in `CONTAINER_RUNTIME.md` and
`SAFE_FAIL.md` (also synced into every project folder).

---

## 5. Companion shared docs (synced everywhere)

- **`CONTAINER_RUNTIME.md`** — permanent, Docker-Desktop-independent way to run the
  stack on Windows, with boot auto-start. Read this first if containers won't start.
- **`SAFE_FAIL.md`** — self-healing model: restart policies, healthchecks, the
  watchdog, port hygiene, and graceful-degradation rules.

<!-- SYNCED: 2026-06-05T15:36:39Z from D:_aethera_shared (canonical). Do not edit per-project copies. -->
