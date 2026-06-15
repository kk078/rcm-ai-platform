#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Registers the Aethera watchdog as a Windows Scheduled Task.
    Run once as Administrator. Re-run to update if paths change.

.DESCRIPTION
    Creates two triggers:
      1. At system startup  - ensures stacks come up after a reboot
      2. Every 5 minutes    - continuous watchdog cadence

    The task runs as SYSTEM (no user login required) with highest privileges.
#>

$TASK_NAME   = "AetheraWatchdog"
$SCRIPT_PATH = "D:\rcm-ai-platform\scripts\ensure-running.ps1"
$LOG_DIR     = "D:\rcm-ai-platform\logs"

# -- Pre-flight ---------------------------------------------------------------
if (-not (Test-Path $SCRIPT_PATH)) {
    Write-Error "Watchdog script not found at: $SCRIPT_PATH"
    exit 1
}

if (-not (Test-Path $LOG_DIR)) {
    New-Item -ItemType Directory -Path $LOG_DIR | Out-Null
    Write-Host "[INFO] Created log directory: $LOG_DIR"
}

# -- Remove existing task (idempotent re-registration) ------------------------
$existing = Get-ScheduledTask -TaskName $TASK_NAME -ErrorAction SilentlyContinue
if ($existing) {
    Unregister-ScheduledTask -TaskName $TASK_NAME -Confirm:$false
    Write-Host "[INFO] Removed existing task: $TASK_NAME"
}

# -- Action -------------------------------------------------------------------
$action = New-ScheduledTaskAction `
    -Execute    "powershell.exe" `
    -Argument   "-NonInteractive -ExecutionPolicy Bypass -File `"$SCRIPT_PATH`""

# -- Triggers -----------------------------------------------------------------
# Trigger 1: at system startup (with a 30-second delay to let networking settle)
$triggerStartup = New-ScheduledTaskTrigger -AtStartup
$triggerStartup.Delay = "PT30S"   # ISO 8601 - 30 seconds

# Trigger 2: repeat every 5 minutes, indefinitely
$triggerRepeat = New-ScheduledTaskTrigger -RepetitionInterval (New-TimeSpan -Minutes 5) `
    -Once -At (Get-Date)
# RepetitionDuration - use max TimeSpan for indefinite
$triggerRepeat.Repetition.Duration  = ""         # empty string = indefinite in XML
$triggerRepeat.Repetition.StopAtDurationEnd = $false

# -- Principal (SYSTEM, highest privileges) -----------------------------------
$principal = New-ScheduledTaskPrincipal `
    -UserId    "SYSTEM" `
    -LogonType ServiceAccount `
    -RunLevel  Highest

# -- Settings -----------------------------------------------------------------
$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit     (New-TimeSpan -Minutes 10) `
    -MultipleInstances      IgnoreNew `
    -RestartCount           3 `
    -RestartInterval        (New-TimeSpan -Minutes 1) `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable:$false `
    -WakeToRun:$false

# -- Register -----------------------------------------------------------------
Register-ScheduledTask `
    -TaskName   $TASK_NAME `
    -Action     $action `
    -Trigger    @($triggerStartup, $triggerRepeat) `
    -Principal  $principal `
    -Settings   $settings `
    -Description "Aethera Stack Watchdog - ensures Docker Compose stacks stay running after reboot or crash." `
    -Force | Out-Null

# -- Verify -------------------------------------------------------------------
$task = Get-ScheduledTask -TaskName $TASK_NAME -ErrorAction Stop
Write-Host ""
Write-Host "======================================================"
Write-Host "  Aethera Watchdog registered successfully"
Write-Host "======================================================"
Write-Host ""
Write-Host "  Task name   : $($task.TaskName)"
Write-Host "  State       : $($task.State)"
Write-Host "  Run as      : SYSTEM (no login required)"
Write-Host "  Triggers    : at startup (+30s delay)  +  every 5 min"
Write-Host "  Script      : $SCRIPT_PATH"
Write-Host "  Log file    : $LOG_DIR\watchdog.log"
Write-Host ""
Write-Host "  Run now to test:"
Write-Host "    Start-ScheduledTask -TaskName '$TASK_NAME'"
Write-Host ""
