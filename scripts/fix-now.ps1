# Aethera Stack Fix + Verify Script
# Runs as Administrator - output saved to logs\fix-output.txt

$LOG = "D:\rcm-ai-platform\logs\fix-output.txt"
$PROD_COMPOSE = "D:\rcm-ai-platform\docker-compose.prod.yml"
$WORKERS_DIR  = "D:\AIAgents\workers"

function Log($msg) {
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "[$ts] $msg"
    Write-Host $line
    Add-Content -Path $LOG -Value $line
}

# Ensure log dir exists
if (-not (Test-Path "D:\rcm-ai-platform\logs")) {
    New-Item -ItemType Directory -Path "D:\rcm-ai-platform\logs" | Out-Null
}

Add-Content -Path $LOG -Value ""
Add-Content -Path $LOG -Value ("=" * 60)
Log "=== Aethera Fix+Verify Run ==="

# -- 1. Check current prod stack status ---------------------------
Log "--- Current prod stack status ---"
$psOut = docker compose -f $PROD_COMPOSE ps 2>&1
$psOut | ForEach-Object { Log $_ }

# -- 2. Bring up prod stack (idempotent) --------------------------
Log "--- Bringing up prod stack ---"
$upOut = docker compose -f $PROD_COMPOSE up -d --remove-orphans 2>&1
$upOut | ForEach-Object { Log $_ }

# -- 3. Wait for healthchecks -------------------------------------
Log "--- Waiting 60s for healthchecks to settle ---"
Start-Sleep -Seconds 60

# -- 4. Final prod stack status -----------------------------------
Log "--- Final prod stack status ---"
$psOut2 = docker compose -f $PROD_COMPOSE ps 2>&1
$psOut2 | ForEach-Object { Log $_ }

# Count unhealthy
$unhealthy = ($psOut2 | Where-Object { $_ -match "unhealthy|Exit|Error" }).Count
$healthy   = ($psOut2 | Where-Object { $_ -match "healthy" }).Count
Log "Healthy services: $healthy  |  Unhealthy/Error: $unhealthy"

# -- 5. Workers stack ---------------------------------------------
Log "--- Bringing up workers stack ---"
if (Test-Path $WORKERS_DIR) {
    Push-Location $WORKERS_DIR
    $wUp = docker compose up -d --remove-orphans 2>&1
    $wUp | ForEach-Object { Log $_ }
    Start-Sleep -Seconds 30
    $wPs = docker compose ps 2>&1
    $wPs | ForEach-Object { Log $_ }
    Pop-Location
} else {
    Log "WARNING: Workers dir not found: $WORKERS_DIR"
}

# -- 6. Register watchdog task ------------------------------------
Log "--- Registering AetheraWatchdog scheduled task ---"
$watchdogScript = "D:\rcm-ai-platform\scripts\register-startup-task.ps1"
if (Test-Path $watchdogScript) {
    $regOut = & powershell.exe -ExecutionPolicy Bypass -File $watchdogScript 2>&1
    $regOut | ForEach-Object { Log $_ }
} else {
    Log "WARNING: Watchdog registration script not found: $watchdogScript"
}

# -- 7. Verify watchdog task registered ---------------------------
Log "--- Watchdog task status ---"
$task = Get-ScheduledTask -TaskName "AetheraWatchdog" -ErrorAction SilentlyContinue
if ($task) {
    Log "AetheraWatchdog task: $($task.State)  RunAs: SYSTEM"
} else {
    Log "WARNING: AetheraWatchdog task NOT found - manual registration required"
}

Log "=== Done. Review output above. ==="
Add-Content -Path $LOG -Value ("=" * 60)
