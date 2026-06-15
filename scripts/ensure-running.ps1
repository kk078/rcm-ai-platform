#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Aethera Stack Watchdog - ensures all Docker Compose stacks are running.
    Run at startup via Task Scheduler, and every 5 min.

.DESCRIPTION
    1. Waits for Docker daemon to be ready (up to 3 minutes)
    2. Brings up D:\rcm-ai-platform   (production stack - API, nginx, cloudflared, etc.)
    3. Brings up D:\AIAgents\workers  (AI worker stack)
    4. Logs result to D:\rcm-ai-platform\logs\watchdog.log
#>

$ErrorActionPreference = "Stop"

# -- Config -------------------------------------------------------------------
$RCM_DIR     = "D:\rcm-ai-platform"
$WORKERS_DIR = "D:\AIAgents\workers"
$LOG_DIR     = "D:\rcm-ai-platform\logs"
$LOG_FILE    = "$LOG_DIR\watchdog.log"
$MAX_LOG_MB  = 10

# -- Helpers ------------------------------------------------------------------
function Log {
    param([string]$msg, [string]$level = "INFO")
    $ts  = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "[$ts] [$level] $msg"
    Write-Host $line
    Add-Content -Path $LOG_FILE -Value $line
}

function Rotate-Log {
    if (Test-Path $LOG_FILE) {
        $sizeBytes = (Get-Item $LOG_FILE).Length
        if ($sizeBytes -gt ($MAX_LOG_MB * 1MB)) {
            $archive = $LOG_FILE -replace "\.log$", "-$(Get-Date -Format 'yyyyMMdd-HHmmss').log"
            Rename-Item $LOG_FILE $archive
            Log "Log rotated to $archive"
        }
    }
}

function Wait-ForDocker {
    param([int]$TimeoutSeconds = 180)
    Log "Waiting for Docker daemon..."
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $null = & docker info 2>$null
            if ($LASTEXITCODE -eq 0) {
                Log "Docker daemon is ready."
                return $true
            }
        } catch {}
        Start-Sleep -Seconds 5
    }
    Log "Docker daemon did not start within ${TimeoutSeconds}s." "WARN"
    return $false
}

function Ensure-Stack {
    param(
        [string]$Dir,
        [string]$ComposeFile,
        [string]$Name
    )
    Push-Location $Dir
    try {
        Log "Checking stack: $Name ($Dir)"

        # Count running containers for this project
        $running = & docker compose -f $ComposeFile ps --status running --quiet 2>$null
        $total   = & docker compose -f $ComposeFile ps --quiet 2>$null

        if (-not $total) {
            Log "Stack $Name: no containers exist - running 'up -d'..." "WARN"
            & docker compose -f $ComposeFile up -d --remove-orphans
            if ($LASTEXITCODE -ne 0) {
                Log "Stack $Name: 'up -d' failed (exit $LASTEXITCODE)." "ERROR"
            } else {
                Log "Stack $Name: started successfully."
            }
        } elseif (($running | Measure-Object).Count -lt ($total | Measure-Object).Count) {
            Log "Stack $Name: some containers are down - running 'up -d'..." "WARN"
            & docker compose -f $ComposeFile up -d --remove-orphans
            if ($LASTEXITCODE -ne 0) {
                Log "Stack $Name: recovery 'up -d' failed (exit $LASTEXITCODE)." "ERROR"
            } else {
                Log "Stack $Name: recovered."
            }
        } else {
            Log "Stack $Name: all containers running OK."
        }
    } finally {
        Pop-Location
    }
}

# -- Main ---------------------------------------------------------------------
if (-not (Test-Path $LOG_DIR)) { New-Item -ItemType Directory -Path $LOG_DIR | Out-Null }
Rotate-Log
Log "=== Aethera watchdog started ==="

if (-not (Wait-ForDocker -TimeoutSeconds 180)) {
    Log "Aborting - Docker not available." "ERROR"
    exit 1
}

Ensure-Stack -Dir $RCM_DIR     -ComposeFile "docker-compose.prod.yml" -Name "rcm-ai-platform"
Ensure-Stack -Dir $WORKERS_DIR -ComposeFile "docker-compose.yml"      -Name "ai-workers"

Log "=== Watchdog run complete ==="
