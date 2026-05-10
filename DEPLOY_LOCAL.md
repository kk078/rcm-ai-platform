# DEPLOY_LOCAL.md — Run on Your PC + Cloudflare Tunnel
# No VPS. Your Windows PC is the server.
# Cloudflare Tunnel connects your PC to rcm.aetheraonline.com


# ═══════════════════════════════════════════════════════════════
# HOW THIS WORKS
# ═══════════════════════════════════════════════════════════════
#
#   Browser → rcm.aetheraonline.com
#       ↓
#   Cloudflare Edge (SSL, CDN, DDoS protection)
#       ↓ (encrypted tunnel)
#   cloudflared on your PC (outbound connection, no ports to open)
#       ↓
#   Docker on your PC (nginx → api, postgres, redis, etc.)
#
# Your PC does NOT need a public IP or port forwarding.
# cloudflared creates an outbound tunnel TO Cloudflare.
# As long as your PC is on and Docker is running, the site is live.


# ═══════════════════════════════════════════════════════════════
# STEP 1: PUSH TO GITHUB (5 minutes)
# ═══════════════════════════════════════════════════════════════

# Open PowerShell:

```powershell
cd C:\Projects\rcm-ai-platform

# Make sure .env is gitignored
if (!(Select-String -Path .gitignore -Pattern "^\.env$" -Quiet)) {
    Add-Content .gitignore ".env"
    Add-Content .gitignore ".env.prod"
}

# Initialize and push
git init
git add .
git commit -m "MedClaim AI - Complete RCM platform"

# Add remote (use your NEW rotated GitHub token)
git remote add origin https://github.com/kk078/rcm-ai-platform.git
# If remote exists: git remote set-url origin https://github.com/kk078/rcm-ai-platform.git

git branch -M main
git push -u origin main --force
```


# ═══════════════════════════════════════════════════════════════
# STEP 2: CONFIGURE DOCKER DESKTOP FOR 16GB RAM (2 minutes)
# ═══════════════════════════════════════════════════════════════

# Open Docker Desktop → Settings → Resources:
#   Memory:  6 GB  (leaves 10GB for Windows + Claude Code)
#   CPUs:    4
#   Swap:    2 GB
#   Disk:    40 GB minimum
# Click "Apply & Restart"


# ═══════════════════════════════════════════════════════════════
# STEP 3: CREATE PRODUCTION ENVIRONMENT (5 minutes)
# ═══════════════════════════════════════════════════════════════

```powershell
cd C:\Projects\rcm-ai-platform

# Generate secure keys
python -c "
import secrets, base64
print('=== COPY THESE INTO .env.prod ===')
print(f'APP_SECRET_KEY={secrets.token_hex(32)}')
print(f'JWT_SECRET_KEY={secrets.token_hex(32)}')
print(f'PHI_ENCRYPTION_KEY={base64.b64encode(secrets.token_bytes(32)).decode()}')
print(f'FIELD_ENCRYPTION_KEY={base64.b64encode(secrets.token_bytes(32)).decode()}')
print(f'POSTGRES_PASSWORD={secrets.token_hex(16)}')
print(f'REDIS_PASSWORD={secrets.token_hex(16)}')
print(f'MINIO_PASSWORD={secrets.token_hex(16)}')
"

# Create .env.prod (copy .env.example first)
Copy-Item .env.example .env.prod
notepad .env.prod
```

### Edit .env.prod with these values:
```env
# App
APP_ENV=production
APP_DEBUG=false
APP_PORT=8000
APP_URL=https://rcm.aetheraonline.com
FRONTEND_URL=https://rcm.aetheraonline.com

# Paste your generated keys here:
APP_SECRET_KEY=<generated>
JWT_SECRET_KEY=<generated>
PHI_ENCRYPTION_KEY=<generated>
FIELD_ENCRYPTION_KEY=<generated>

# Your Anthropic key:
ANTHROPIC_API_KEY=sk-ant-YOUR_KEY_HERE

# Database (Docker internal hostnames, not localhost):
DATABASE_URL=postgresql+asyncpg://medclaim:<POSTGRES_PASSWORD>@postgres:5432/medclaim_db

# Redis:
REDIS_URL=redis://default:<REDIS_PASSWORD>@redis:6379/0

# Qdrant:
QDRANT_URL=http://qdrant:6333

# MinIO:
S3_ENDPOINT=http://minio:9000
S3_ACCESS_KEY=medclaim_minio
S3_SECRET_KEY=<MINIO_PASSWORD>
```
Save and close.


# ═══════════════════════════════════════════════════════════════
# STEP 4: CREATE DOCKER COMPOSE FOR YOUR PC (copy-paste this)
# ═══════════════════════════════════════════════════════════════

```powershell
# Create the production compose file
@"
version: "3.9"

services:
  # ── API Server ─────────────────────────────────────────
  api:
    build:
      context: .
      dockerfile: Dockerfile
    restart: unless-stopped
    env_file: .env.prod
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    networks:
      - rcm-network
    command: >
      uvicorn src.api.main:app
      --host 0.0.0.0
      --port 8000
      --workers 2

  # ── Celery Worker ──────────────────────────────────────
  celery-worker:
    build:
      context: .
      dockerfile: Dockerfile
    restart: unless-stopped
    env_file: .env.prod
    depends_on:
      - redis
      - postgres
    networks:
      - rcm-network
    command: >
      celery -A src.infrastructure.queue.celery_app worker
      -l info -Q coding,billing,payments,denials,edi
      --concurrency=2

  # ── Celery Beat (Scheduler) ────────────────────────────
  celery-beat:
    build:
      context: .
      dockerfile: Dockerfile
    restart: unless-stopped
    env_file: .env.prod
    depends_on:
      - redis
    networks:
      - rcm-network
    command: celery -A src.infrastructure.queue.celery_app beat -l info

  # ── Nginx (Reverse Proxy + Frontends) ──────────────────
  nginx:
    image: nginx:alpine
    restart: unless-stopped
    ports:
      - "8080:80"
    volumes:
      - ./config/nginx/nginx.conf:/etc/nginx/nginx.conf:ro
      - ./ui/staff-portal/dist:/var/www/staff-portal:ro
      - ./ui/provider-portal/dist:/var/www/provider-portal:ro
    depends_on:
      - api
    networks:
      - rcm-network

  # ── PostgreSQL ─────────────────────────────────────────
  postgres:
    image: postgres:16-alpine
    restart: unless-stopped
    environment:
      POSTGRES_DB: medclaim_db
      POSTGRES_USER: medclaim
      POSTGRES_PASSWORD: CHANGE_TO_GENERATED_PASSWORD
    volumes:
      - pgdata:/var/lib/postgresql/data
    networks:
      - rcm-network
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U medclaim"]
      interval: 10s
      timeout: 5s
      retries: 5

  # ── Redis ──────────────────────────────────────────────
  redis:
    image: redis:7-alpine
    restart: unless-stopped
    command: redis-server --appendonly yes
    volumes:
      - redisdata:/data
    networks:
      - rcm-network
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5

  # ── Qdrant (Vector DB) ────────────────────────────────
  qdrant:
    image: qdrant/qdrant:latest
    restart: unless-stopped
    volumes:
      - qdrantdata:/qdrant/storage
    networks:
      - rcm-network

  # ── MinIO (Object Storage) ────────────────────────────
  minio:
    image: minio/minio:latest
    restart: unless-stopped
    environment:
      MINIO_ROOT_USER: medclaim_minio
      MINIO_ROOT_PASSWORD: CHANGE_TO_GENERATED_PASSWORD
    volumes:
      - miniodata:/data
    networks:
      - rcm-network
    command: server /data

  # ── Cloudflare Tunnel ──────────────────────────────────
  cloudflared:
    image: cloudflare/cloudflared:latest
    restart: unless-stopped
    command: tunnel run
    environment:
      TUNNEL_TOKEN: YOUR_TUNNEL_TOKEN_HERE
    networks:
      - rcm-network
    depends_on:
      - nginx

networks:
  rcm-network:
    driver: bridge

volumes:
  pgdata:
  redisdata:
  qdrantdata:
  miniodata:
"@ | Out-File -FilePath docker-compose.prod.yml -Encoding utf8
```

### IMPORTANT: Edit docker-compose.prod.yml
```powershell
notepad docker-compose.prod.yml
```
Replace:
- `CHANGE_TO_GENERATED_PASSWORD` (postgres) → your generated POSTGRES_PASSWORD
- `CHANGE_TO_GENERATED_PASSWORD` (minio) → your generated MINIO_PASSWORD
- `YOUR_TUNNEL_TOKEN_HERE` → we'll get this in Step 6


# ═══════════════════════════════════════════════════════════════
# STEP 5: CREATE NGINX CONFIG
# ═══════════════════════════════════════════════════════════════

```powershell
# Create nginx config directory
New-Item -ItemType Directory -Force -Path config\nginx

@"
events {
    worker_connections 512;
}

http {
    include       /etc/nginx/mime.types;
    default_type  application/octet-stream;
    sendfile      on;
    gzip          on;
    gzip_types    text/plain text/css application/json application/javascript text/xml;

    # Staff Portal + API: rcm.aetheraonline.com
    server {
        listen 80;
        server_name rcm.aetheraonline.com;

        add_header X-Content-Type-Options nosniff always;
        add_header X-Frame-Options DENY always;
        add_header Strict-Transport-Security "max-age=31536000" always;
        add_header Cache-Control "no-store" always;

        # API
        location /api/ {
            proxy_pass http://api:8000;
            proxy_set_header Host `$host;
            proxy_set_header X-Real-IP `$remote_addr;
            proxy_set_header X-Forwarded-For `$proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto https;
            proxy_read_timeout 120s;
        }

        location /health {
            proxy_pass http://api:8000;
            proxy_set_header Host `$host;
        }

        location /ready {
            proxy_pass http://api:8000;
            proxy_set_header Host `$host;
        }

        # Staff frontend
        location / {
            root /var/www/staff-portal;
            index index.html;
            try_files `$uri `$uri/ /index.html;

            location ~* \.(js|css|png|jpg|jpeg|gif|ico|svg|woff|woff2)$ {
                expires 30d;
                add_header Cache-Control "public, immutable";
            }
        }
    }

    # Provider Portal: portal.rcm.aetheraonline.com
    server {
        listen 80;
        server_name portal.rcm.aetheraonline.com;

        add_header X-Content-Type-Options nosniff always;
        add_header X-Frame-Options DENY always;
        add_header Strict-Transport-Security "max-age=31536000" always;

        location /api/ {
            proxy_pass http://api:8000;
            proxy_set_header Host `$host;
            proxy_set_header X-Real-IP `$remote_addr;
            proxy_set_header X-Forwarded-For `$proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto https;
            proxy_read_timeout 120s;
        }

        location / {
            root /var/www/provider-portal;
            index index.html;
            try_files `$uri `$uri/ /index.html;

            location ~* \.(js|css|png|jpg|jpeg|gif|ico|svg|woff|woff2)$ {
                expires 30d;
                add_header Cache-Control "public, immutable";
            }
        }
    }
}
"@ | Out-File -FilePath config\nginx\nginx.conf -Encoding utf8
```


# ═══════════════════════════════════════════════════════════════
# STEP 6: CREATE CLOUDFLARE TUNNEL (10 minutes)
# ═══════════════════════════════════════════════════════════════

# Do this in your browser:

# 1. Go to: https://one.dash.cloudflare.com
# 2. Select your account
# 3. Go to: Networks → Tunnels
# 4. Click "Create a tunnel"
# 5. Select "Cloudflared" connector type
# 6. Name it: rcm-platform
# 7. Click "Save tunnel"
#
# 8. You'll see a page with a TUNNEL TOKEN. It looks like:
#    eyJhIjoiMTk2OTg3Zjl... (very long string)
#    COPY THIS TOKEN — you'll paste it into docker-compose.prod.yml
#
# 9. Skip the "Install connector" step (we run it in Docker)
# 10. Click "Next"
#
# 11. Add your first public hostname:
#     Subdomain: rcm
#     Domain: aetheraonline.com
#     Service Type: HTTP
#     URL: nginx:80
#     Click "Save hostname"
#
# 12. Add second hostname (click "Add a public hostname"):
#     Subdomain: portal.rcm
#     Domain: aetheraonline.com
#     Service Type: HTTP
#     URL: nginx:80
#     Click "Save hostname"
#
# 13. Click "Save tunnel"

# Now paste the tunnel token into docker-compose.prod.yml:

```powershell
notepad docker-compose.prod.yml
# Find: YOUR_TUNNEL_TOKEN_HERE
# Replace with: the actual token from step 8
# Save and close
```


# ═══════════════════════════════════════════════════════════════
# STEP 7: BUILD FRONTENDS
# ═══════════════════════════════════════════════════════════════

```powershell
cd C:\Projects\rcm-ai-platform

# Build staff portal
cd ui\staff-portal
"VITE_API_URL=https://rcm.aetheraonline.com" | Out-File .env.production -Encoding utf8
npm install
npm run build
cd ..\..

# Build provider portal
cd ui\provider-portal
"VITE_API_URL=https://portal.rcm.aetheraonline.com" | Out-File .env.production -Encoding utf8
npm install
npm run build
cd ..\..

# Verify both built successfully
Test-Path ui\staff-portal\dist\index.html
Test-Path ui\provider-portal\dist\index.html
# Both should return: True
```


# ═══════════════════════════════════════════════════════════════
# STEP 8: LAUNCH EVERYTHING
# ═══════════════════════════════════════════════════════════════

```powershell
cd C:\Projects\rcm-ai-platform

# Build and start all containers
docker compose -f docker-compose.prod.yml up -d --build

# This will take 3-5 minutes on first run (building Python image)
# Watch the progress:
docker compose -f docker-compose.prod.yml logs -f

# Press Ctrl+C to stop watching logs (containers keep running)

# Check all containers are running (should show 8 services):
docker compose -f docker-compose.prod.yml ps
```

### Expected output:
```
NAME                STATUS
api                 Up
celery-worker       Up
celery-beat         Up
nginx               Up
postgres            Up (healthy)
redis               Up (healthy)
qdrant              Up
minio               Up
cloudflared         Up
```

### If any container is not "Up":
```powershell
# Check its logs:
docker compose -f docker-compose.prod.yml logs api
docker compose -f docker-compose.prod.yml logs cloudflared
docker compose -f docker-compose.prod.yml logs nginx
```


# ═══════════════════════════════════════════════════════════════
# STEP 9: INITIALIZE DATABASE & SEED DATA
# ═══════════════════════════════════════════════════════════════

```powershell
cd C:\Projects\rcm-ai-platform

# Run database migrations
docker compose -f docker-compose.prod.yml exec api alembic upgrade head

# Seed reference data (CARC codes, payers, NCCI edits, etc.)
docker compose -f docker-compose.prod.yml exec api python scripts/seed_reference_data.py

# Create your admin user
docker compose -f docker-compose.prod.yml exec api python -c "
import asyncio
from src.infrastructure.database.session import async_session
from src.infrastructure.database.models import User
from src.infrastructure.auth.service import hash_password

async def create_admin():
    async with async_session() as session:
        admin = User(
            email='admin@aetheraonline.com',
            password_hash=hash_password('ChangeThisPassword123!'),
            first_name='Admin',
            last_name='User',
            user_type='internal',
            internal_role='company_admin',
            is_active=True,
            mfa_enabled=False,
        )
        session.add(admin)
        await session.commit()
        print('Admin created: admin@aetheraonline.com')

asyncio.run(create_admin())
"
```


# ═══════════════════════════════════════════════════════════════
# STEP 10: VERIFY EVERYTHING IS LIVE
# ═══════════════════════════════════════════════════════════════

```powershell
# Test locally first (nginx on port 8080)
Invoke-RestMethod -Uri "http://localhost:8080/health"
# Expected: status = healthy

# Test through Cloudflare Tunnel (the real URL)
Invoke-RestMethod -Uri "https://rcm.aetheraonline.com/health"
# Expected: status = healthy

# Test staff portal
$r = Invoke-WebRequest -Uri "https://rcm.aetheraonline.com" -UseBasicParsing
Write-Host "Staff Portal: $($r.StatusCode)"
# Expected: 200

# Test provider portal
$r = Invoke-WebRequest -Uri "https://portal.rcm.aetheraonline.com" -UseBasicParsing
Write-Host "Provider Portal: $($r.StatusCode)"
# Expected: 200

# Open in browser
Start-Process "https://rcm.aetheraonline.com"
```

# ✅ If you see your login page, YOU'RE LIVE!
# Login: admin@aetheraonline.com / ChangeThisPassword123!
# CHANGE THE PASSWORD after first login.


# ═══════════════════════════════════════════════════════════════
# DAILY OPERATIONS
# ═══════════════════════════════════════════════════════════════

### Start the platform (after PC restart):
```powershell
cd C:\Projects\rcm-ai-platform
docker compose -f docker-compose.prod.yml up -d
# Cloudflare tunnel reconnects automatically
```

### Stop the platform:
```powershell
docker compose -f docker-compose.prod.yml down
# Site goes offline until you start again
```

### View logs:
```powershell
# All services
docker compose -f docker-compose.prod.yml logs -f

# Specific service
docker compose -f docker-compose.prod.yml logs -f api
docker compose -f docker-compose.prod.yml logs -f celery-worker
docker compose -f docker-compose.prod.yml logs -f cloudflared
```

### Update code and redeploy:
```powershell
cd C:\Projects\rcm-ai-platform

# Make your code changes, then:
git add .
git commit -m "your changes"
git push origin main

# Rebuild and restart
docker compose -f docker-compose.prod.yml up -d --build

# If you changed database models, run migrations:
docker compose -f docker-compose.prod.yml exec api alembic upgrade head
```

### Backup database:
```powershell
$date = Get-Date -Format "yyyyMMdd"
docker compose -f docker-compose.prod.yml exec -T postgres pg_dump -U medclaim medclaim_db > "backup_$date.sql"
```

### Check resource usage:
```powershell
docker stats
# Watch CPU and memory per container
# Press Ctrl+C to exit
```


# ═══════════════════════════════════════════════════════════════
# MAKE IT START AUTOMATICALLY WHEN PC BOOTS
# ═══════════════════════════════════════════════════════════════

# Docker Desktop can auto-start on login:
# Docker Desktop → Settings → General → "Start Docker Desktop when you sign in" ✅

# Docker containers with "restart: unless-stopped" will auto-start
# when Docker Desktop starts. So your app comes back online
# automatically after a PC restart.

# To verify after a reboot:
```powershell
docker compose -f docker-compose.prod.yml ps
# All services should be "Up"
```


# ═══════════════════════════════════════════════════════════════
# MEMORY OPTIMIZATION FOR 16GB (if things are slow)
# ═══════════════════════════════════════════════════════════════

# If your PC feels sluggish, reduce Docker resource usage:

# Option 1: Reduce worker counts in docker-compose.prod.yml:
#   api: --workers 1 (instead of 2)
#   celery-worker: --concurrency=1 (instead of 2)

# Option 2: Stop non-essential services when not needed:
```powershell
# Stop Qdrant if you're not using AI features right now:
docker compose -f docker-compose.prod.yml stop qdrant

# Stop MinIO if you're not uploading documents:
docker compose -f docker-compose.prod.yml stop minio

# Restart them when needed:
docker compose -f docker-compose.prod.yml start qdrant minio
```

# Option 3: Docker Desktop → Settings → Resources → Memory: 4GB (minimum)


# ═══════════════════════════════════════════════════════════════
# TROUBLESHOOTING
# ═══════════════════════════════════════════════════════════════

# "cloudflared" container keeps restarting:
#   → Check tunnel token is correct in docker-compose.prod.yml
#   → Check tunnel is active in Cloudflare dashboard (Networks → Tunnels)
#   → docker compose -f docker-compose.prod.yml logs cloudflared

# Site shows "502 Bad Gateway":
#   → API container might not be ready yet. Wait 30 seconds.
#   → Check: docker compose -f docker-compose.prod.yml logs api

# Site shows Cloudflare error page:
#   → Tunnel is connected but nginx can't reach API
#   → Check: docker compose -f docker-compose.prod.yml ps
#   → All services need to be "Up"

# "Cannot connect to database":
#   → Check postgres is running: docker compose -f docker-compose.prod.yml ps postgres
#   → Check password in .env.prod matches docker-compose.prod.yml POSTGRES_PASSWORD

# Frontend shows blank page:
#   → Rebuild: cd ui\staff-portal && npm run build
#   → Restart nginx: docker compose -f docker-compose.prod.yml restart nginx

# PC is very slow:
#   → docker stats (check memory usage)
#   → Reduce Docker memory in Docker Desktop settings
#   → Stop non-essential containers (qdrant, minio)

# Need to completely reset:
```powershell
docker compose -f docker-compose.prod.yml down -v   # -v removes all data volumes!
docker compose -f docker-compose.prod.yml up -d --build
# Then re-run migrations and seed data (Step 9)
```


# ═══════════════════════════════════════════════════════════════
# YOUR LIVE URLS
# ═══════════════════════════════════════════════════════════════

# Staff Portal:      https://rcm.aetheraonline.com
# Provider Portal:   https://portal.rcm.aetheraonline.com
# API Health:        https://rcm.aetheraonline.com/health
# Local (bypass CF): http://localhost:8080

# ⚠️ Your PC must be ON and Docker running for the site to be accessible.
# When your PC sleeps or Docker stops, the site goes offline.
# Consider disabling sleep: Settings → System → Power → Screen and sleep → Never
