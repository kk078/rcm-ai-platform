# MedClaim AI — Production Startup Script
# Run from D:\rcm-ai-platform

$ErrorActionPreference = "Stop"
Set-Location "D:\rcm-ai-platform"

function Write-Color($text, $color = "White") {
    Write-Host $text -ForegroundColor $color
}

function Write-Step($text) {
    Write-Host ""
    Write-Color "=== $text ===" "Cyan"
}

function Write-Success($text) {
    Write-Color "  [OK] $text" "Green"
}

function Write-Warn($text) {
    Write-Color "  [WARN] $text" "Yellow"
}

function Write-Err($text) {
    Write-Color "  [ERROR] $text" "Red"
}

# ── Check Docker ──────────────────────────────────────────
Write-Step "Checking prerequisites"

try {
    $dockerVersion = docker version --format "{{.Server.Version}}" 2>$null
    if (-not $dockerVersion) {
        throw "Docker not responding"
    }
    Write-Success "Docker is running (version $dockerVersion)"
} catch {
    Write-Err "Docker is not running. Start Docker Desktop and try again."
    exit 1
}

# ── Check .env.prod ───────────────────────────────────────
Write-Step "Checking configuration"

if (-not (Test-Path ".env.prod")) {
    Write-Err ".env.prod not found. Run scripts/generate_secrets.py first."
    exit 1
}
Write-Success ".env.prod found"

# Check for required values
$envContent = Get-Content ".env.prod" -Raw
$missing = @()

if ($envContent -notmatch 'ANTHROPIC_API_KEY=\S+') {
    $missing += "ANTHROPIC_API_KEY"
    Write-Warn "ANTHROPIC_API_KEY is empty — AI features will not work"
}

if ($envContent -notmatch 'TUNNEL_TOKEN=\S+') {
    $missing += "TUNNEL_TOKEN"
    Write-Warn "TUNNEL_TOKEN is empty — Cloudflare Tunnel will not connect"
}

if ($missing.Count -eq 0) {
    Write-Success "All required keys are set"
}

# ── Build frontends if needed ─────────────────────────────
Write-Step "Building frontends"

$frontends = @(
    @{ Name = "staff-portal"; Path = "ui\staff-portal" },
    @{ Name = "provider-portal"; Path = "ui\provider-portal" }
)

foreach ($portal in $frontends) {
    $distPath = Join-Path $portal.Path "dist\index.html"
    if (Test-Path $distPath) {
        Write-Success "$($portal.Name) already built"
    } else {
        Write-Host "  Building $($portal.Name)..." -ForegroundColor Yellow
        Push-Location $portal.Path
        try {
            npm install 2>$null | Out-Null
            npm run build 2>$null | Out-Null
            if (Test-Path "dist\index.html") {
                Write-Success "$($portal.Name) built successfully"
            } else {
                Write-Err "$($portal.Name) build failed"
                exit 1
            }
        } finally {
            Pop-Location
        }
    }
}

# ── Start Docker services ─────────────────────────────────
Write-Step "Starting Docker services"

docker compose -f docker-compose.prod.yml up -d --build
if ($LASTEXITCODE -ne 0) {
    Write-Err "Docker compose failed. Check logs with: docker compose -f docker-compose.prod.yml logs"
    exit 1
}
Write-Success "Docker services started"

# ── Wait for services to be ready ─────────────────────────
Write-Step "Waiting for services (30 seconds)"

Start-Sleep -Seconds 30
Write-Success "Wait complete"

# ── Run database migrations ────────────────────────────────
Write-Step "Running database migrations"

docker compose -f docker-compose.prod.yml exec api alembic upgrade head
if ($LASTEXITCODE -eq 0) {
    Write-Success "Migrations applied"
} else {
    Write-Warn "Migrations may have failed — check logs above"
}

# ── Seed reference data ───────────────────────────────────
Write-Step "Seeding reference data"

if (Test-Path "scripts\seed_reference_data.py") {
    docker compose -f docker-compose.prod.yml exec api python scripts/seed_reference_data.py
    Write-Success "Reference data seeded"
} else {
    Write-Warn "seed_reference_data.py not found — skipping"
}

# ── Create admin user ─────────────────────────────────────
Write-Step "Creating admin user"

docker compose -f docker-compose.prod.yml exec api python scripts/create_admin.py
Write-Success "Admin user setup complete"

# ── Health check ───────────────────────────────────────────
Write-Step "Running health check"

try {
    $response = Invoke-RestMethod -Uri "http://localhost:8080/health" -TimeoutSec 10 -ErrorAction Stop
    Write-Success "Health check passed: $($response.status)"
} catch {
    Write-Warn "Health check not responding yet — services may still be starting"
    Write-Warn "Try again in a minute: Invoke-RestMethod http://localhost:8080/health"
}

# ── Summary ────────────────────────────────────────────────
Write-Host ""
Write-Color "========================================" "Green"
Write-Color "  MedClaim AI is running!" "Green"
Write-Color "========================================" "Green"
Write-Host ""
Write-Color "  Local:       http://localhost:8080" "White"
Write-Color "  Staff:       https://rcm.aetheraonline.com" "White"
Write-Color "  Provider:    https://portal.rcm.aetheraonline.com" "White"
Write-Color "  Health:      https://rcm.aetheraonline.com/health" "White"
Write-Host ""
Write-Color "  Admin login: admin@aetheraonline.com" "Yellow"
Write-Color "  Password:    MedClaimAdmin2026! (change this immediately!)" "Yellow"
Write-Host ""
Write-Color "  Logs:        docker compose -f docker-compose.prod.yml logs -f" "Gray"
Write-Color "  Stop:        .\scripts\stop.ps1" "Gray"
Write-Host ""