# DEPLOY_NOW.md — Push to GitHub + Deploy to Cloudflare
# You've built the app. This gets it live.


# ═══════════════════════════════════════════════════════════════
# STEP 1: PUSH TO GITHUB (5 minutes)
# ═══════════════════════════════════════════════════════════════

# Open PowerShell, navigate to your project:

```powershell
cd C:\Projects\rcm-ai-platform

# 1. Make sure .gitignore exists and covers secrets
# Verify these lines are in .gitignore:
type .gitignore
# Must contain: .env, .venv/, __pycache__/, node_modules/, *.pyc

# If .gitignore is missing or incomplete:
@"
.env
.env.prod
.venv/
__pycache__/
*.py[cod]
*.egg-info/
node_modules/
dist/
build/
.next/
*.log
.DS_Store
.coverage
htmlcov/
.mypy_cache/
.pytest_cache/
.ruff_cache/
*.db
*.sqlite3
"@ | Out-File -FilePath .gitignore -Encoding utf8

# 2. Initialize git if not already done
git init

# 3. Add remote (use your NEW token, not the exposed one)
# Replace YOUR_NEW_TOKEN with your freshly generated GitHub PAT
git remote add origin https://YOUR_NEW_TOKEN@github.com/kk078/rcm-ai-platform.git

# If remote already exists, update it:
git remote set-url origin https://YOUR_NEW_TOKEN@github.com/kk078/rcm-ai-platform.git

# 4. Stage everything
git add .

# 5. Verify no secrets are being committed
git status
# STOP AND CHECK: .env should NOT appear in the staged files list
# If .env shows up: git rm --cached .env

# 6. Commit and push
git commit -m "MedClaim AI - Complete RCM platform"
git push -u origin main

# If the branch is 'master' instead of 'main':
git branch -M main
git push -u origin main

# If push is rejected (repo has existing content):
git push -u origin main --force
```

# Verify: Go to https://github.com/kk078/rcm-ai-platform
# You should see all your files EXCEPT .env


# ═══════════════════════════════════════════════════════════════
# STEP 2: CHOOSE YOUR HOSTING (Read this first)
# ═══════════════════════════════════════════════════════════════

# Your app has:
#   - FastAPI backend (Python)
#   - Celery workers
#   - PostgreSQL + Redis + Qdrant + MinIO
#   - Two React frontends
#
# This is NOT a static site. It needs a server.
# 
# Cloudflare alone can't host the backend.
# You need: VPS/Server + Cloudflare for DNS/CDN/SSL
#
# OPTIONS:
#
# A) VPS (Recommended: $24-48/month)
#    - DigitalOcean Droplet, Hetzner Cloud, or Vultr
#    - 4 vCPU, 8GB RAM, 80GB SSD
#    - You install Docker, deploy with docker-compose
#    - Cloudflare handles DNS + SSL + CDN + DDoS protection
#
# B) AWS/GCP/Azure (More complex, $50-200/month)
#    - EC2/Compute Engine + RDS + ElastiCache
#    - More scalable but more to manage
#
# C) Railway/Render (Easiest, $25-75/month)
#    - Push to Git, it deploys automatically
#    - Managed databases as add-ons
#    - Less control but zero DevOps

# Below I'll give you OPTION A (VPS + Cloudflare) since you already
# have the Cloudflare account and domain set up.


# ═══════════════════════════════════════════════════════════════
# STEP 3: PROVISION A VPS (15 minutes)
# ═══════════════════════════════════════════════════════════════

# Go to DigitalOcean, Hetzner, or Vultr and create a server:
#   OS: Ubuntu 24.04 LTS
#   Plan: 4 vCPU, 8GB RAM, 80GB SSD (~$24-48/month)
#   Region: Closest to your users (US-East, US-West, or Mumbai/Singapore for India)
#   Auth: SSH key (recommended) or password

# Once server is created, note the IP address: e.g., 143.198.xxx.xxx


# ═══════════════════════════════════════════════════════════════
# STEP 4: SET UP THE SERVER (20 minutes)
# ═══════════════════════════════════════════════════════════════

# SSH into your server from PowerShell:
```powershell
ssh root@YOUR_SERVER_IP
```

# Now run these commands ON THE SERVER (Linux):

```bash
# ── Install Docker ──────────────────────────────────────────
curl -fsSL https://get.docker.com | sh
systemctl enable docker
systemctl start docker

# Install Docker Compose plugin
apt-get update && apt-get install -y docker-compose-plugin

# Verify
docker --version
docker compose version

# ── Install Git ─────────────────────────────────────────────
apt-get install -y git

# ── Clone your repo ─────────────────────────────────────────
mkdir -p /opt/apps
cd /opt/apps
git clone https://github.com/kk078/rcm-ai-platform.git
cd rcm-ai-platform

# ── Create production .env ──────────────────────────────────
cp .env.example .env.prod

# Generate secure keys
python3 -c "
import secrets, base64
print(f'APP_SECRET_KEY={secrets.token_hex(32)}')
print(f'JWT_SECRET_KEY={secrets.token_hex(32)}')
print(f'PHI_ENCRYPTION_KEY={base64.b64encode(secrets.token_bytes(32)).decode()}')
print(f'FIELD_ENCRYPTION_KEY={base64.b64encode(secrets.token_bytes(32)).decode()}')
"
# Copy the output and paste into .env.prod

# Edit .env.prod with your production values:
nano .env.prod
```

### Production .env.prod values to set:
```
APP_ENV=production
APP_DEBUG=false
APP_URL=https://rcm.aetheraonline.com
FRONTEND_URL=https://rcm.aetheraonline.com

# Paste the generated keys:
APP_SECRET_KEY=<generated>
JWT_SECRET_KEY=<generated>
PHI_ENCRYPTION_KEY=<generated>
FIELD_ENCRYPTION_KEY=<generated>

# Your Anthropic API key:
ANTHROPIC_API_KEY=sk-ant-YOUR_REAL_KEY

# Database (Docker internal network):
DATABASE_URL=postgresql+asyncpg://medclaim:STRONG_DB_PASSWORD_HERE@postgres:5432/medclaim_db

# Redis:
REDIS_URL=redis://redis:6379/0

# Qdrant:
QDRANT_URL=http://qdrant:6333

# S3/MinIO:
S3_ENDPOINT=http://minio:9000

# CHANGE the default passwords:
# In docker-compose.prod.yml, update POSTGRES_PASSWORD to match
```

Save and exit (Ctrl+X, Y, Enter in nano).


# ═══════════════════════════════════════════════════════════════
# STEP 5: CREATE PRODUCTION DOCKER COMPOSE (on server)
# ═══════════════════════════════════════════════════════════════

```bash
cat > /opt/apps/rcm-ai-platform/docker-compose.prod.yml << 'DOCKEREOF'
version: "3.9"

services:
  # ── API Server ─────────────────────────────────────────
  api:
    build:
      context: .
      dockerfile: Dockerfile
    restart: always
    env_file: .env.prod
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    networks:
      - internal
    command: >
      gunicorn src.api.main:app
      --workers 4
      --worker-class uvicorn.workers.UvicornWorker
      --bind 0.0.0.0:8000
      --timeout 120
      --access-logfile -
      --error-logfile -

  # ── Celery Worker ──────────────────────────────────────
  celery-worker:
    build:
      context: .
      dockerfile: Dockerfile
    restart: always
    env_file: .env.prod
    depends_on:
      - redis
      - postgres
    networks:
      - internal
    command: >
      celery -A src.infrastructure.queue.celery_app worker
      -l info
      -Q coding,billing,payments,denials,edi
      --concurrency=4

  # ── Celery Beat ────────────────────────────────────────
  celery-beat:
    build:
      context: .
      dockerfile: Dockerfile
    restart: always
    env_file: .env.prod
    depends_on:
      - redis
    networks:
      - internal
    command: celery -A src.infrastructure.queue.celery_app beat -l info

  # ── Nginx Reverse Proxy ────────────────────────────────
  nginx:
    image: nginx:alpine
    restart: always
    ports:
      - "80:80"
    volumes:
      - ./config/nginx/nginx.conf:/etc/nginx/nginx.conf:ro
      - ./ui/staff-portal/dist:/var/www/staff-portal:ro
      - ./ui/provider-portal/dist:/var/www/provider-portal:ro
    depends_on:
      - api
    networks:
      - internal

  # ── PostgreSQL ─────────────────────────────────────────
  postgres:
    image: postgres:16-alpine
    restart: always
    environment:
      POSTGRES_DB: medclaim_db
      POSTGRES_USER: medclaim
      POSTGRES_PASSWORD: STRONG_DB_PASSWORD_HERE
    volumes:
      - postgres_data:/var/lib/postgresql/data
    networks:
      - internal
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U medclaim"]
      interval: 10s
      timeout: 5s
      retries: 5

  # ── Redis ──────────────────────────────────────────────
  redis:
    image: redis:7-alpine
    restart: always
    command: redis-server --appendonly yes --requirepass STRONG_REDIS_PASSWORD
    volumes:
      - redis_data:/data
    networks:
      - internal
    healthcheck:
      test: ["CMD", "redis-cli", "-a", "STRONG_REDIS_PASSWORD", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5

  # ── Qdrant ─────────────────────────────────────────────
  qdrant:
    image: qdrant/qdrant:latest
    restart: always
    volumes:
      - qdrant_data:/qdrant/storage
    networks:
      - internal

  # ── MinIO ──────────────────────────────────────────────
  minio:
    image: minio/minio:latest
    restart: always
    environment:
      MINIO_ROOT_USER: medclaim_minio
      MINIO_ROOT_PASSWORD: STRONG_MINIO_PASSWORD
    volumes:
      - minio_data:/data
    networks:
      - internal
    command: server /data

networks:
  internal:
    driver: bridge

volumes:
  postgres_data:
  redis_data:
  qdrant_data:
  minio_data:
DOCKEREOF
```

# ═══════════════════════════════════════════════════════════════
# STEP 6: CREATE NGINX CONFIG (on server)
# ═══════════════════════════════════════════════════════════════

```bash
mkdir -p /opt/apps/rcm-ai-platform/config/nginx

cat > /opt/apps/rcm-ai-platform/config/nginx/nginx.conf << 'NGINXEOF'
events {
    worker_connections 1024;
}

http {
    include       /etc/nginx/mime.types;
    default_type  application/octet-stream;
    sendfile      on;
    gzip          on;
    gzip_types    text/plain text/css application/json application/javascript text/xml;

    # Rate limiting
    limit_req_zone $binary_remote_addr zone=api:10m rate=100r/m;
    limit_req_zone $binary_remote_addr zone=ai:10m rate=30r/m;

    # ── Staff Portal: rcm.aetheraonline.com ──────────────
    server {
        listen 80;
        server_name rcm.aetheraonline.com;

        # Security headers
        add_header X-Content-Type-Options nosniff always;
        add_header X-Frame-Options DENY always;
        add_header X-XSS-Protection "1; mode=block" always;
        add_header Referrer-Policy strict-origin-when-cross-origin always;
        add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;

        # API routes → FastAPI
        location /api/ {
            limit_req zone=api burst=20 nodelay;
            proxy_pass http://api:8000;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_read_timeout 120s;
            proxy_connect_timeout 10s;
            
            # No caching for API
            add_header Cache-Control "no-store" always;
            add_header Pragma "no-cache" always;
        }

        # Health check
        location /health {
            proxy_pass http://api:8000;
            proxy_set_header Host $host;
        }

        # Staff portal frontend
        location / {
            root /var/www/staff-portal;
            index index.html;
            try_files $uri $uri/ /index.html;

            # Cache static assets
            location ~* \.(js|css|png|jpg|jpeg|gif|ico|svg|woff|woff2)$ {
                expires 30d;
                add_header Cache-Control "public, immutable";
            }
        }
    }

    # ── Provider Portal: portal.rcm.aetheraonline.com ────
    server {
        listen 80;
        server_name portal.rcm.aetheraonline.com;

        # Same security headers
        add_header X-Content-Type-Options nosniff always;
        add_header X-Frame-Options DENY always;
        add_header X-XSS-Protection "1; mode=block" always;
        add_header Referrer-Policy strict-origin-when-cross-origin always;
        add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;

        # API routes → FastAPI (provider portal uses same API)
        location /api/ {
            limit_req zone=api burst=20 nodelay;
            proxy_pass http://api:8000;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_read_timeout 120s;
            
            add_header Cache-Control "no-store" always;
            add_header Pragma "no-cache" always;
        }

        # Provider portal frontend
        location / {
            root /var/www/provider-portal;
            index index.html;
            try_files $uri $uri/ /index.html;

            location ~* \.(js|css|png|jpg|jpeg|gif|ico|svg|woff|woff2)$ {
                expires 30d;
                add_header Cache-Control "public, immutable";
            }
        }
    }
}
NGINXEOF
```


# ═══════════════════════════════════════════════════════════════
# STEP 7: BUILD FRONTENDS (on server)
# ═══════════════════════════════════════════════════════════════

```bash
cd /opt/apps/rcm-ai-platform

# Install Node.js on server
curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
apt-get install -y nodejs

# Build staff portal
cd ui/staff-portal
npm install
# Set the production API URL before building
echo "VITE_API_URL=https://rcm.aetheraonline.com" > .env.production
npm run build
# Output is in ui/staff-portal/dist/

# Build provider portal
cd ../provider-portal
npm install
echo "VITE_API_URL=https://portal.rcm.aetheraonline.com" > .env.production
npm run build
# Output is in ui/provider-portal/dist/

cd /opt/apps/rcm-ai-platform
```


# ═══════════════════════════════════════════════════════════════
# STEP 8: LAUNCH THE APPLICATION (on server)
# ═══════════════════════════════════════════════════════════════

```bash
cd /opt/apps/rcm-ai-platform

# Build and start all services
docker compose -f docker-compose.prod.yml up -d --build

# Wait for everything to start (30 seconds)
sleep 30

# Check all containers are running
docker compose -f docker-compose.prod.yml ps

# Run database migrations
docker compose -f docker-compose.prod.yml exec api alembic upgrade head

# Seed reference data
docker compose -f docker-compose.prod.yml exec api python scripts/seed_reference_data.py

# Create admin user (if you have the script)
docker compose -f docker-compose.prod.yml exec api python -c "
import asyncio
from src.infrastructure.database.session import async_session
from src.infrastructure.database.models import User
from src.infrastructure.auth.service import hash_password

async def create_admin():
    async with async_session() as session:
        admin = User(
            email='admin@aetheraonline.com',
            password_hash=hash_password('YourSecurePassword123!'),
            first_name='Admin',
            last_name='User',
            user_type='internal',
            internal_role='company_admin',
            is_active=True,
            mfa_enabled=False,
        )
        session.add(admin)
        await session.commit()
        print(f'Admin user created: admin@aetheraonline.com')

asyncio.run(create_admin())
"

# Verify the API is responding
curl http://localhost/health
# Expected: {"status":"healthy","version":"0.1.0","env":"production"}

echo "Application is running on port 80"
```


# ═══════════════════════════════════════════════════════════════
# STEP 9: CONFIGURE CLOUDFLARE DNS (5 minutes)
# ═══════════════════════════════════════════════════════════════

# Go to: https://dash.cloudflare.com
# Select domain: aetheraonline.com
# Go to: DNS → Records

# Add these DNS records:

# Record 1 — Staff Portal
#   Type:    A
#   Name:    rcm
#   Content: YOUR_SERVER_IP (e.g., 143.198.xxx.xxx)
#   Proxy:   Proxied (orange cloud ON)
#   TTL:     Auto

# Record 2 — Provider Portal
#   Type:    CNAME
#   Name:    portal.rcm
#   Content: rcm.aetheraonline.com
#   Proxy:   Proxied (orange cloud ON)
#   TTL:     Auto


# ═══════════════════════════════════════════════════════════════
# STEP 10: CONFIGURE CLOUDFLARE SSL (3 minutes)
# ═══════════════════════════════════════════════════════════════

# In Cloudflare dashboard:

# SSL/TLS → Overview:
#   Encryption mode: Full (strict)

# SSL/TLS → Edge Certificates:
#   Always Use HTTPS: ON
#   Minimum TLS Version: TLS 1.2
#   Automatic HTTPS Rewrites: ON

# Security → Settings:
#   Security Level: Medium
#   Challenge Passage: 30 minutes
#   Browser Integrity Check: ON

# Speed → Optimization:
#   Auto Minify: JavaScript ✅, CSS ✅, HTML ✅
#   Brotli: ON

# Caching → Configuration:
#   Caching Level: Standard
#   Browser Cache TTL: Respect Existing Headers

# Page Rules (optional, for extra security):
#   rcm.aetheraonline.com/api/*
#     Cache Level: Bypass
#     Security Level: High


# ═══════════════════════════════════════════════════════════════
# STEP 11: VERIFY EVERYTHING IS LIVE
# ═══════════════════════════════════════════════════════════════

# From your Windows machine, test:

```powershell
# Test API health
Invoke-RestMethod -Uri "https://rcm.aetheraonline.com/health"
# Expected: status=healthy

# Test API endpoint
Invoke-RestMethod -Uri "https://rcm.aetheraonline.com/api/v1/health" -ErrorAction SilentlyContinue

# Test staff portal loads
$response = Invoke-WebRequest -Uri "https://rcm.aetheraonline.com" -UseBasicParsing
Write-Host "Staff Portal: $($response.StatusCode)"
# Expected: 200

# Test provider portal loads
$response = Invoke-WebRequest -Uri "https://portal.rcm.aetheraonline.com" -UseBasicParsing
Write-Host "Provider Portal: $($response.StatusCode)"
# Expected: 200

# Test SSL certificate
# Open browser and go to https://rcm.aetheraonline.com
# You should see the lock icon — Cloudflare issues the SSL certificate automatically
```

# ═══════════════════════════════════════════════════════════════
# STEP 12: SET UP AUTO-DEPLOY FROM GITHUB (10 minutes)
# ═══════════════════════════════════════════════════════════════

# On your SERVER, create a deploy script:

```bash
cat > /opt/apps/rcm-ai-platform/scripts/deploy.sh << 'DEPLOYEOF'
#!/bin/bash
set -e

echo "=== Starting deployment ==="
cd /opt/apps/rcm-ai-platform

# Pull latest code
echo "Pulling latest code..."
git pull origin main

# Rebuild frontends
echo "Building staff portal..."
cd ui/staff-portal && npm install && npm run build && cd ../..

echo "Building provider portal..."
cd ui/provider-portal && npm install && npm run build && cd ../..

# Rebuild and restart Docker services
echo "Rebuilding Docker images..."
docker compose -f docker-compose.prod.yml build

echo "Restarting services..."
docker compose -f docker-compose.prod.yml up -d

# Wait for services
sleep 15

# Run any new migrations
echo "Running migrations..."
docker compose -f docker-compose.prod.yml exec -T api alembic upgrade head

# Health check
echo "Running health check..."
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://localhost/health)
if [ "$HTTP_CODE" = "200" ]; then
    echo "=== Deployment successful! Health check passed ==="
else
    echo "=== WARNING: Health check returned $HTTP_CODE ==="
fi
DEPLOYEOF

chmod +x /opt/apps/rcm-ai-platform/scripts/deploy.sh
```

# Now create a GitHub Actions workflow for auto-deploy:
# On your WINDOWS machine:

```powershell
cd C:\Projects\rcm-ai-platform
mkdir -p .github\workflows
```

# Create the workflow file:

```yaml
# Save this as .github/workflows/deploy.yml

name: Deploy to Production

on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - name: Deploy to server
        uses: appleboy/ssh-action@v1
        with:
          host: ${{ secrets.SERVER_IP }}
          username: root
          key: ${{ secrets.SSH_PRIVATE_KEY }}
          script: /opt/apps/rcm-ai-platform/scripts/deploy.sh
```

# Add GitHub secrets (in GitHub repo → Settings → Secrets → Actions):
#   SERVER_IP      = your VPS IP address
#   SSH_PRIVATE_KEY = your SSH private key for the server

# Now every push to main auto-deploys!
```powershell
git add .
git commit -m "Add CI/CD deployment pipeline"
git push origin main
```


# ═══════════════════════════════════════════════════════════════
# DAILY OPERATIONS
# ═══════════════════════════════════════════════════════════════

# ── Push code updates (from Windows) ────────────────────────
```powershell
cd C:\Projects\rcm-ai-platform
git add .
git commit -m "your changes"
git push origin main
# GitHub Actions will auto-deploy to server
```

# ── Manual deploy (if needed, SSH into server) ──────────────
```bash
ssh root@YOUR_SERVER_IP
/opt/apps/rcm-ai-platform/scripts/deploy.sh
```

# ── View logs ───────────────────────────────────────────────
```bash
ssh root@YOUR_SERVER_IP
cd /opt/apps/rcm-ai-platform

# API logs
docker compose -f docker-compose.prod.yml logs -f api

# All service logs
docker compose -f docker-compose.prod.yml logs -f

# Celery worker logs
docker compose -f docker-compose.prod.yml logs -f celery-worker
```

# ── Restart services ────────────────────────────────────────
```bash
docker compose -f docker-compose.prod.yml restart api
docker compose -f docker-compose.prod.yml restart nginx
docker compose -f docker-compose.prod.yml restart celery-worker
```

# ── Database backup ─────────────────────────────────────────
```bash
# Create backup
docker compose -f docker-compose.prod.yml exec postgres \
  pg_dump -U medclaim medclaim_db > backup_$(date +%Y%m%d).sql

# Set up daily automatic backups (add to crontab):
crontab -e
# Add this line:
# 0 3 * * * cd /opt/apps/rcm-ai-platform && docker compose -f docker-compose.prod.yml exec -T postgres pg_dump -U medclaim medclaim_db > /opt/backups/medclaim_$(date +\%Y\%m\%d).sql
```

# ── Monitor disk/memory ─────────────────────────────────────
```bash
df -h          # Disk usage
free -m        # Memory usage
docker stats   # Container resource usage
```


# ═══════════════════════════════════════════════════════════════
# YOUR LIVE URLs (after deployment)
# ═══════════════════════════════════════════════════════════════

# Staff Portal:      https://rcm.aetheraonline.com
# Provider Portal:   https://portal.rcm.aetheraonline.com
# API Health Check:  https://rcm.aetheraonline.com/health
# API Docs (dev):    https://rcm.aetheraonline.com/api/docs
#                    (disabled in production by default — set APP_DEBUG=true temporarily to access)

# Login:             admin@aetheraonline.com / YourSecurePassword123!
#                    (CHANGE THIS PASSWORD IMMEDIATELY after first login)
