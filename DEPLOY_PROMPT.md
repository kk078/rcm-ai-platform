# DEPLOY_PROMPT.md
# Copy the prompt below and paste it into Claude Code.
# One prompt. It sets up everything.


## Paste this into Claude Code:

```
Read DEPLOY_LOCAL.md to understand the deployment architecture. Then do ALL of the following in order. Do not stop until everything is complete.

This is a Windows 10/11 PC with 16GB RAM, Docker Desktop installed, Python + Node.js installed. The project is at C:\Projects\rcm-ai-platform. We're deploying to rcm.aetheraonline.com using Cloudflare Tunnel (no VPS). My Cloudflare account ID is 196987f9fa53f4b0cb757aa5c77ff0a2 and domain is aetheraonline.com.

=== TASK 1: FIX .gitignore ===

Make sure .gitignore exists and contains these entries (add any missing ones, don't remove existing):
.env
.env.prod
.venv/
__pycache__/
*.py[cod]
*.egg-info/
node_modules/
dist/
build/
*.log
.DS_Store
.coverage
.mypy_cache/
.pytest_cache/
*.db
*.sqlite3

=== TASK 2: GENERATE PRODUCTION SECRETS ===

Create a Python script scripts/generate_secrets.py that:
1. Generates cryptographically secure random values for:
   - APP_SECRET_KEY (64 hex chars)
   - JWT_SECRET_KEY (64 hex chars)
   - PHI_ENCRYPTION_KEY (32 bytes, base64 encoded)
   - FIELD_ENCRYPTION_KEY (32 bytes, base64 encoded)
   - POSTGRES_PASSWORD (32 hex chars)
   - REDIS_PASSWORD (32 hex chars)
   - MINIO_PASSWORD (32 hex chars)
2. Prints them in KEY=VALUE format
3. Also creates .env.prod by copying .env.example and inserting the generated values with these additional settings:
   - APP_ENV=production
   - APP_DEBUG=false
   - APP_URL=https://rcm.aetheraonline.com
   - FRONTEND_URL=https://rcm.aetheraonline.com
   - DATABASE_URL=postgresql+asyncpg://medclaim:{POSTGRES_PASSWORD}@postgres:5432/medclaim_db
   - REDIS_URL=redis://default:{REDIS_PASSWORD}@redis:6379/0
   - REDIS_CACHE_DB=1
   - REDIS_CELERY_DB=2
   - CELERY_BROKER_URL=redis://default:{REDIS_PASSWORD}@redis:6379/2
   - CELERY_RESULT_BACKEND=redis://default:{REDIS_PASSWORD}@redis:6379/2
   - QDRANT_URL=http://qdrant:6333
   - S3_ENDPOINT=http://minio:9000
   - S3_ACCESS_KEY=medclaim_minio
   - S3_SECRET_KEY={MINIO_PASSWORD}
   - ANTHROPIC_API_KEY= (leave blank, user fills in manually)
   - LOG_LEVEL=WARNING
   - LOG_FORMAT=json
4. Prints a reminder: "IMPORTANT: Edit .env.prod and add your ANTHROPIC_API_KEY"

Run the script immediately after creating it.

=== TASK 3: CREATE docker-compose.prod.yml ===

Create docker-compose.prod.yml at the project root with these services:

1. api:
   - Build from ./Dockerfile
   - restart: unless-stopped
   - env_file: .env.prod
   - depends_on postgres (healthy) and redis (healthy)
   - network: rcm-network
   - command: uvicorn src.api.main:app --host 0.0.0.0 --port 8000 --workers 2
   - No port mapping (nginx handles external access)

2. celery-worker:
   - Same build as api
   - restart: unless-stopped
   - env_file: .env.prod
   - depends_on redis, postgres
   - network: rcm-network
   - command: celery -A src.infrastructure.queue.celery_app worker -l info -Q coding,billing,payments,denials,edi --concurrency=2

3. celery-beat:
   - Same build as api
   - restart: unless-stopped
   - env_file: .env.prod
   - depends_on redis
   - network: rcm-network
   - command: celery -A src.infrastructure.queue.celery_app beat -l info

4. nginx:
   - image: nginx:alpine
   - restart: unless-stopped
   - ports: 8080:80 (local access only, Cloudflare Tunnel handles public)
   - volumes: mount config/nginx/nginx.conf, ui/staff-portal/dist, ui/provider-portal/dist
   - depends_on api
   - network: rcm-network

5. postgres:
   - image: postgres:16-alpine
   - restart: unless-stopped
   - environment: POSTGRES_DB=medclaim_db, POSTGRES_USER=medclaim, POSTGRES_PASSWORD read from .env.prod somehow — actually hardcode it by reading the generated password from .env.prod. Or better: use a variable. Use the POSTGRES_PASSWORD value you generated. Put it directly in the compose file since .env.prod has it.
   - Actually, the cleanest approach: read POSTGRES_PASSWORD from .env.prod in the script and inject it into docker-compose.prod.yml. 
   - volume: pgdata:/var/lib/postgresql/data
   - healthcheck: pg_isready -U medclaim
   - network: rcm-network

6. redis:
   - image: redis:7-alpine
   - restart: unless-stopped
   - command: redis-server --appendonly yes
   - volume: redisdata:/data
   - healthcheck: redis-cli ping
   - network: rcm-network

7. qdrant:
   - image: qdrant/qdrant:latest
   - restart: unless-stopped
   - volume: qdrantdata:/qdrant/storage
   - network: rcm-network

8. minio:
   - image: minio/minio:latest
   - restart: unless-stopped
   - environment: MINIO_ROOT_USER=medclaim_minio, MINIO_ROOT_PASSWORD from generated value
   - volume: miniodata:/data
   - command: server /data
   - network: rcm-network

9. cloudflared:
   - image: cloudflare/cloudflared:latest
   - restart: unless-stopped
   - command: tunnel run
   - environment: TUNNEL_TOKEN=${TUNNEL_TOKEN}
   - network: rcm-network
   - depends_on nginx

The TUNNEL_TOKEN should be read from .env.prod so the user can set it there.
Add TUNNEL_TOKEN= (blank) to .env.prod with a comment saying to fill it in.

Networks: rcm-network (bridge)
Volumes: pgdata, redisdata, qdrantdata, miniodata

=== TASK 4: CREATE NGINX CONFIG ===

Create config/nginx/nginx.conf with:

Server block 1 — rcm.aetheraonline.com:
- listen 80
- /api/* → proxy_pass http://api:8000 with proper headers (Host, X-Real-IP, X-Forwarded-For, X-Forwarded-Proto https), read timeout 120s, Cache-Control no-store
- /health and /ready → proxy_pass http://api:8000
- / → serve /var/www/staff-portal with try_files for SPA routing
- Static assets (js, css, png, jpg, svg, woff2) → 30 day cache
- Security headers: X-Content-Type-Options nosniff, X-Frame-Options DENY, HSTS

Server block 2 — portal.rcm.aetheraonline.com:
- listen 80
- /api/* → same proxy to api:8000
- / → serve /var/www/provider-portal with SPA routing
- Same security headers and caching

Enable gzip for text/plain, text/css, application/json, application/javascript.

=== TASK 5: CREATE/VERIFY DOCKERFILE ===

Check if Dockerfile exists and is correct. If not, create a production-ready Dockerfile:
- FROM python:3.12-slim
- Install system deps: build-essential, libpq-dev
- Copy pyproject.toml, install Python deps
- Copy source code
- Create non-root user called "appuser"
- Switch to appuser
- Expose 8000
- Default CMD: uvicorn src.api.main:app --host 0.0.0.0 --port 8000
- Add HEALTHCHECK: curl -f http://localhost:8000/health || exit 1

=== TASK 6: CREATE ADMIN USER SEED SCRIPT ===

Create scripts/create_admin.py that:
1. Connects to the database using DATABASE_URL from environment/.env.prod
2. Checks if admin@aetheraonline.com already exists, skips if so
3. Creates a User with:
   - email: admin@aetheraonline.com
   - password: hashed version of "MedClaimAdmin2026!" (using the project's auth service)
   - first_name: Admin
   - last_name: User
   - user_type: internal
   - internal_role: company_admin
   - is_active: True
   - mfa_enabled: False
4. Prints success message with the email
5. Prints reminder to change password after first login

=== TASK 7: CREATE STARTUP SCRIPT ===

Create scripts/start.ps1 (PowerShell) that automates the full startup:

```powershell
# MedClaim AI — Full Stack Startup Script for Windows

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  MedClaim AI — Starting Platform" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

# Check Docker is running
$docker = docker info 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Docker is not running. Start Docker Desktop first." -ForegroundColor Red
    exit 1
}

# Check .env.prod exists
if (!(Test-Path .env.prod)) {
    Write-Host "ERROR: .env.prod not found. Run: python scripts/generate_secrets.py" -ForegroundColor Red
    exit 1
}

# Check TUNNEL_TOKEN is set
$tunnelToken = Select-String -Path .env.prod -Pattern "^TUNNEL_TOKEN=.+" -Quiet
if (!$tunnelToken) {
    Write-Host "WARNING: TUNNEL_TOKEN not set in .env.prod. Cloudflare Tunnel won't work." -ForegroundColor Yellow
    Write-Host "Create tunnel at https://one.dash.cloudflare.com → Networks → Tunnels" -ForegroundColor Yellow
}

# Check ANTHROPIC_API_KEY is set
$apiKey = Select-String -Path .env.prod -Pattern "^ANTHROPIC_API_KEY=sk-" -Quiet
if (!$apiKey) {
    Write-Host "WARNING: ANTHROPIC_API_KEY not set in .env.prod. AI features won't work." -ForegroundColor Yellow
}

# Check frontends are built
if (!(Test-Path ui\staff-portal\dist\index.html)) {
    Write-Host "Building staff portal..." -ForegroundColor Yellow
    Push-Location ui\staff-portal
    npm install
    npm run build
    Pop-Location
}

if (!(Test-Path ui\provider-portal\dist\index.html)) {
    Write-Host "Building provider portal..." -ForegroundColor Yellow
    Push-Location ui\provider-portal
    npm install
    npm run build
    Pop-Location
}

# Start all services
Write-Host "`nStarting Docker services..." -ForegroundColor Green
docker compose -f docker-compose.prod.yml up -d --build

Write-Host "`nWaiting for services to start..." -ForegroundColor Yellow
Start-Sleep -Seconds 30

# Check health
Write-Host "`nChecking services..." -ForegroundColor Yellow
docker compose -f docker-compose.prod.yml ps

# Run migrations
Write-Host "`nRunning database migrations..." -ForegroundColor Green
docker compose -f docker-compose.prod.yml exec -T api alembic upgrade head 2>$null

# Seed data
Write-Host "Seeding reference data..." -ForegroundColor Green
docker compose -f docker-compose.prod.yml exec -T api python scripts/seed_reference_data.py 2>$null

# Create admin user
Write-Host "Creating admin user..." -ForegroundColor Green
docker compose -f docker-compose.prod.yml exec -T api python scripts/create_admin.py 2>$null

# Health check
Write-Host "`nRunning health check..." -ForegroundColor Yellow
try {
    $health = Invoke-RestMethod -Uri "http://localhost:8080/health" -TimeoutSec 10
    Write-Host "API Health: $($health.status)" -ForegroundColor Green
} catch {
    Write-Host "API not responding yet. Wait a minute and check http://localhost:8080/health" -ForegroundColor Yellow
}

Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "  MedClaim AI — Platform Running!" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Local:           http://localhost:8080" -ForegroundColor White
Write-Host "  Staff Portal:    https://rcm.aetheraonline.com" -ForegroundColor White
Write-Host "  Provider Portal: https://portal.rcm.aetheraonline.com" -ForegroundColor White
Write-Host "  Login:           admin@aetheraonline.com" -ForegroundColor White
Write-Host ""
Write-Host "  Stop:  docker compose -f docker-compose.prod.yml down" -ForegroundColor Gray
Write-Host "  Logs:  docker compose -f docker-compose.prod.yml logs -f" -ForegroundColor Gray
```

Make the script handle errors gracefully.

=== TASK 8: CREATE STOP SCRIPT ===

Create scripts/stop.ps1:
- Runs docker compose -f docker-compose.prod.yml down
- Prints confirmation

=== TASK 9: CREATE GITHUB ACTIONS WORKFLOW ===

Create .github/workflows/test.yml:
- Triggers on push to main and pull requests
- Sets up Python 3.12
- Installs dependencies
- Runs pytest
- Reports results

Note: We don't auto-deploy since the server is the user's PC, not a remote server. The workflow just runs tests to catch issues before the user pulls and restarts locally.

=== TASK 10: VERIFY EVERYTHING ===

After creating all files, run these checks:
1. Verify .gitignore contains .env and .env.prod
2. Verify .env.prod was created with all required keys
3. Verify docker-compose.prod.yml is valid YAML: docker compose -f docker-compose.prod.yml config
4. Verify Dockerfile exists and has correct syntax
5. Verify config/nginx/nginx.conf exists
6. Verify scripts/generate_secrets.py works: python scripts/generate_secrets.py (run it if not already run)
7. Verify scripts/create_admin.py exists
8. Verify scripts/start.ps1 exists
9. Verify scripts/stop.ps1 exists
10. Verify .github/workflows/test.yml exists
11. List all files created/modified

Print a summary of what was created and what the user needs to do next:
1. Edit .env.prod → add ANTHROPIC_API_KEY
2. Create Cloudflare Tunnel → paste TUNNEL_TOKEN into .env.prod
3. Run: .\scripts\start.ps1
4. Open: https://rcm.aetheraonline.com

Do NOT run docker compose up. Do NOT try to connect to databases. Just create all the files and verify they're syntactically correct. The user will run start.ps1 themselves.
```
