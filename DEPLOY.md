# Aethera AI — Production Deployment Guide

Deploying Aethera AI on a Linux server via Cloudflare Tunnel so the platform is
publicly reachable at **https://rcm.aetherahealthcare.com** without opening
firewall ports or managing TLS certificates on the server.

---

## Prerequisites

| Requirement | Notes |
|---|---|
| Linux server | Ubuntu 22.04+ recommended; 4 vCPU, 8 GB RAM minimum for 50 concurrent users |
| Docker Engine 24+ | https://docs.docker.com/engine/install/ubuntu/ |
| Docker Compose v2 | Bundled with Docker Desktop; `docker compose version` to verify |
| Cloudflare account | With `aetherahealthcare.com` added as a zone |
| Ollama Cloud API key | https://ollama.com → account settings → API keys |
| Python 3.11+ | For `generate_secrets.py` (already in the container; use host Python here) |

---

## Step 1 — Cloudflare Tunnel Setup

Install `cloudflared` on the **server** (not inside Docker):

```bash
# Ubuntu/Debian
curl -L --output cloudflared.deb \
  https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
sudo dpkg -i cloudflared.deb
```

Authenticate and create the tunnel:

```bash
# Opens a browser window — authenticate with your Cloudflare account
cloudflared tunnel login

# Create a named tunnel
cloudflared tunnel create aethera-rcm

# Route the tunnel to your domain
cloudflared tunnel route dns aethera-rcm rcm.aetherahealthcare.com
```

Copy the tunnel token for the next step:

```bash
# The token is printed when you run:
cloudflared tunnel token aethera-rcm
```

Paste that token into your `.env` file as `TUNNEL_TOKEN=<token>`.

> The tunnel runs as a Docker container (`cloudflared` service in
> `docker-compose.prod.yml`) — you do not need to run it as a system service.

---

## Step 2 — Generate Secrets

Run on the server (or your local machine — just copy the output to the server):

```bash
python scripts/generate_secrets.py
```

The script prints all secrets in `.env` format. Copy the output and paste it
into your `.env` file in the next step.

---

## Step 3 — Configure .env

```bash
cp .env.example .env
nano .env   # or vim, whatever you prefer
```

Fill in every section — at minimum these must be non-empty:

| Variable | Where to get it |
|---|---|
| `TUNNEL_TOKEN` | Step 1 above |
| `OLLAMA_API_KEY` | https://ollama.com → account → API keys |
| `JWT_SECRET_KEY` | From `generate_secrets.py` output |
| `PHI_ENCRYPTION_KEY` | From `generate_secrets.py` output |
| `FIELD_ENCRYPTION_KEY` | From `generate_secrets.py` output |
| `APP_SECRET_KEY` | From `generate_secrets.py` output |
| `POSTGRES_PASSWORD` | From `generate_secrets.py` output |
| `MINIO_ROOT_USER` | From `generate_secrets.py` output (`aethera_minio`) |
| `MINIO_ROOT_PASSWORD` | From `generate_secrets.py` output |
| `DATABASE_URL` | From `generate_secrets.py` output |
| `REDIS_URL` | From `generate_secrets.py` output |

Also set:

```dotenv
APP_ENV=production
APP_DEBUG=false
APP_URL=https://rcm.aetherahealthcare.com
```

---

## Step 4 — Deploy

```bash
chmod +x scripts/deploy.sh
./scripts/deploy.sh
```

The script will:

1. Validate all required env vars are set
2. Pull latest base images (postgres, redis, qdrant, minio, cloudflared)
3. Build the application images (api, celery-worker, celery-beat, nginx)
4. Start all services with `docker compose up -d --remove-orphans`
5. Poll `http://localhost:8000/health` every 3 s until healthy (max 60 s)
6. Run `alembic upgrade head` inside the api container
7. Create MinIO buckets (claims, documents, edi-files, exports, audit-logs)
8. Verify the public endpoint at `https://rcm.aetherahealthcare.com/health`
9. Print container status

---

## Step 5 — Verify

```bash
# Public health endpoint (via Cloudflare Tunnel)
curl https://rcm.aetherahealthcare.com/health
# Expected: {"status": "healthy"}

# Readiness (checks all dependencies)
curl https://rcm.aetherahealthcare.com/ready
# Expected: {"status": "ready", "checks": {...}}

# API docs (disable in production by removing the docs location from nginx.conf)
open https://rcm.aetherahealthcare.com/docs
```

If the public URL is not yet responding, the tunnel may take 30–60 s to
propagate after first startup. Check the tunnel container logs:

```bash
docker compose -f docker-compose.prod.yml logs -f cloudflared
```

---

## Optional — Enable Monitoring

Prometheus + Grafana are included under the `monitoring` profile:

```bash
docker compose -f docker-compose.prod.yml --profile monitoring up -d
```

Grafana is available at `https://rcm.aetherahealthcare.com/grafana/`
(default admin password from `GRAFANA_PASSWORD` in `.env`).

---

## Scaling for 50+ Concurrent Users

The defaults in `docker-compose.prod.yml` are sized for ~50 concurrent users.
Key tuning parameters already set:

| Component | Setting | Value |
|---|---|---|
| API (gunicorn) | `-w` workers | 4 |
| Nginx | `keepalive` connections | 32 |
| Celery workers | `--concurrency` | 8 per replica × 2 replicas |
| PostgreSQL | `max_connections` | 200 |
| PostgreSQL | `shared_buffers` | 256 MB |
| Redis | `maxmemory` | 512 MB |
| Redis | eviction policy | `allkeys-lru` |
| API container | memory limit | 1 GB |
| Celery container | memory limit | 2 GB per replica |

For larger workloads (200+ users), consider:

- Moving PostgreSQL to a managed service (RDS, Supabase, Neon)
- Moving Redis to a managed service (Upstash, ElastiCache)
- Running the api and celery-worker on separate servers
- Adding a CDN in front of Cloudflare for static assets

---

## Updating the Application

```bash
git pull origin main
./scripts/deploy.sh
```

The deploy script rebuilds images and runs migrations automatically.
Zero-downtime: old containers serve traffic while new ones are built; Compose
replaces them atomically once the build completes.

---

## Rollback

```bash
# Roll back to the previous image tag (if you tag releases)
docker compose -f docker-compose.prod.yml stop api celery-worker celery-beat
docker tag aethera-ai-api:previous aethera-ai-api:latest
docker compose -f docker-compose.prod.yml up -d api celery-worker celery-beat

# Roll back the database migration
docker compose -f docker-compose.prod.yml exec -T api alembic downgrade -1
```

---

## Useful Commands

```bash
# Tail logs for all services
docker compose -f docker-compose.prod.yml logs -f

# Tail only the API
docker compose -f docker-compose.prod.yml logs -f api

# Open a shell inside the API container
docker compose -f docker-compose.prod.yml exec api bash

# Restart a single service
docker compose -f docker-compose.prod.yml restart celery-worker

# Check resource usage
docker stats

# Inspect all container health
docker compose -f docker-compose.prod.yml ps
```
