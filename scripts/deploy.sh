#!/bin/bash
# ── Aethera AI — Production Deploy Script ─────────────────────────────────────
# Usage: chmod +x scripts/deploy.sh && ./scripts/deploy.sh
# Requires: Docker, Docker Compose v2, .env file in project root
set -euo pipefail

COMPOSE="docker compose -f docker-compose.prod.yml"
HEALTH_URL="https://rcm.aetherahealthcare.com/health"
MAX_WAIT=60
POLL_INTERVAL=3

# ── Colors ────────────────────────────────────────────────────────────────────
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

info()    { echo -e "${GREEN}[deploy]${NC} $*"; }
warn()    { echo -e "${YELLOW}[warn]${NC}  $*"; }
error()   { echo -e "${RED}[error]${NC} $*" >&2; }
die()     { error "$*"; exit 1; }

# ── Step 1: Check required env vars ──────────────────────────────────────────
info "Checking required environment variables..."

if [ ! -f ".env" ]; then
    die ".env file not found. Copy .env.example to .env and fill in secrets."
fi

# Source .env to check values (strip export prefix if present)
set -a
# shellcheck disable=SC1091
source <(grep -v '^#' .env | grep -v '^$' | sed 's/^export //')
set +a

REQUIRED_VARS=(
    TUNNEL_TOKEN
    JWT_SECRET_KEY
    OLLAMA_API_KEY
    PHI_ENCRYPTION_KEY
    POSTGRES_PASSWORD
    MINIO_ROOT_USER
    MINIO_ROOT_PASSWORD
)

MISSING=()
for var in "${REQUIRED_VARS[@]}"; do
    val="${!var:-}"
    if [ -z "$val" ]; then
        MISSING+=("$var")
    fi
done

if [ ${#MISSING[@]} -gt 0 ]; then
    error "The following required environment variables are not set in .env:"
    for v in "${MISSING[@]}"; do
        error "  - $v"
    done
    die "Set all required variables and retry."
fi
info "All required environment variables present."

# ── Step 2: Pull latest base images ──────────────────────────────────────────
info "Pulling latest Docker base images..."
$COMPOSE pull --ignore-pull-failures postgres redis qdrant minio cloudflared prometheus grafana

# ── Step 3: Build application images ─────────────────────────────────────────
info "Building application images..."
$COMPOSE build --no-cache api celery-worker celery-beat nginx

# ── Step 4: Bring up all services ────────────────────────────────────────────
info "Starting services..."
$COMPOSE up -d --remove-orphans

# ── Step 5: Wait for API health check ────────────────────────────────────────
info "Waiting for API to become healthy (max ${MAX_WAIT}s)..."
elapsed=0
while true; do
    HTTP_CODE=$(curl -sk -o /dev/null -w "%{http_code}" "http://localhost:8000/health" 2>/dev/null || echo "000")
    if [ "$HTTP_CODE" = "200" ]; then
        info "API is healthy."
        break
    fi
    if [ "$elapsed" -ge "$MAX_WAIT" ]; then
        warn "API health check timed out after ${MAX_WAIT}s (last HTTP code: ${HTTP_CODE})."
        warn "Check logs with: docker compose -f docker-compose.prod.yml logs api"
        # Don't exit — migrations may still be needed
        break
    fi
    sleep "$POLL_INTERVAL"
    elapsed=$((elapsed + POLL_INTERVAL))
    echo -n "."
done
echo ""

# ── Step 6: Run database migrations ──────────────────────────────────────────
info "Running database migrations..."
$COMPOSE exec -T api alembic upgrade head
info "Migrations complete."

# ── Step 7: Create MinIO buckets if they don't exist ─────────────────────────
info "Ensuring MinIO buckets exist..."
$COMPOSE exec -T minio sh -c '
    mc alias set local http://localhost:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" --quiet 2>/dev/null || true
    for bucket in claims documents edi-files exports audit-logs; do
        mc mb --ignore-existing "local/$bucket" 2>/dev/null || true
        echo "  bucket: $bucket"
    done
' 2>/dev/null || warn "MinIO bucket creation skipped (mc not available in container — run manually if needed)."

# ── Step 8: Verify public endpoint ───────────────────────────────────────────
info "Verifying public endpoint..."
sleep 3
HTTP_CODE=$(curl -sk -o /dev/null -w "%{http_code}" "$HEALTH_URL" 2>/dev/null || echo "000")
if [ "$HTTP_CODE" = "200" ]; then
    echo ""
    echo -e "${GREEN}✓ Aethera AI deployed at https://rcm.aetherahealthcare.com${NC}"
    echo ""
else
    warn "Public health check returned HTTP $HTTP_CODE — tunnel may still be warming up."
    warn "Verify manually: curl -I $HEALTH_URL"
fi

# ── Step 9: Show container status ────────────────────────────────────────────
echo ""
info "Container status:"
$COMPOSE ps
echo ""
info "To tail logs: docker compose -f docker-compose.prod.yml logs -f"
info "To enable monitoring: docker compose -f docker-compose.prod.yml --profile monitoring up -d"
