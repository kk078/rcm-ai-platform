@echo off
setlocal
title AI Auto-Debugger E2E Test

echo.
echo ╔══════════════════════════════════════════╗
echo ║   AI Auto-Debugger E2E Test v2           ║
echo ╚══════════════════════════════════════════╝
echo.

REM ── Wait for Docker engine to be accessible (up to 60s) ─────────────────
echo [0/3] Waiting for Docker engine...
set DOCKER_WAIT=0
:WAIT_DOCKER
docker info >nul 2>&1
if not errorlevel 1 goto DOCKER_READY
set /a DOCKER_WAIT+=5
if %DOCKER_WAIT% geq 60 (
    echo [ERROR] Docker engine not available after 60s.
    echo         Please start Docker Desktop manually.
    pause
    exit /b 1
)
echo         Not ready yet, waiting 5s... (%DOCKER_WAIT%s elapsed)
timeout /t 5 /nobreak >nul
goto WAIT_DOCKER

:DOCKER_READY
echo         Docker engine ready.
echo.

REM ── Check/start the rcm-ai-platform stack ────────────────────────────────
echo [1/3] Checking container status...
docker inspect --format="{{.State.Status}}" rcm-ai-platform-api-1 >nul 2>&1
if errorlevel 1 (
    echo         Container not found — starting stack with docker compose up -d...
    cd /d "D:\rcm-ai-platform"
    docker compose up -d
    if errorlevel 1 (
        echo [ERROR] docker compose up failed.
        pause
        exit /b 1
    )
    echo         Waiting 20s for containers to initialize...
    timeout /t 20 /nobreak >nul
) else (
    for /f %%s in ('docker inspect --format="{{.State.Status}}" rcm-ai-platform-api-1') do set CSTATE=%%s
    echo         Container status: %CSTATE%
    if not "%CSTATE%"=="running" (
        echo         Container not running — starting it...
        docker compose -f "D:\rcm-ai-platform\docker-compose.yml" up -d
        timeout /t 15 /nobreak >nul
    )
)

REM ── Verify API container is running ──────────────────────────────────────
for /f %%s in ('docker inspect --format={{.State.Status}} rcm-ai-platform-api-1 2^>nul') do set API_STATE=%%s
if not "%API_STATE%"=="running" (
    echo [ERROR] rcm-ai-platform-api-1 is not running (state: %API_STATE%).
    pause
    exit /b 1
)
echo         API container is running.
echo.

REM ── Copy the test script into the container ─────────────────────────────
echo [2/3] Copying test script into container...
docker cp "D:\rcm-ai-platform\scripts\test_e2e_patcher.py" rcm-ai-platform-api-1:/app/scripts/test_e2e_patcher.py
if errorlevel 1 (
    echo [ERROR] docker cp failed
    pause
    exit /b 1
)
echo       Copied OK
echo.

REM ── Run the test (may take up to 3 minutes) ──────────────────────────────
echo [3/3] Running E2E test (up to 3 min for AI analysis + patching)...
echo.
docker exec -e PYTHONPATH=/app rcm-ai-platform-api-1 python /app/scripts/test_e2e_patcher.py

set EXIT_CODE=%errorlevel%
echo.
if %EXIT_CODE% equ 0 (
    echo ╔══════════════╗
    echo ║  Test done.  ║
    echo ╚══════════════╝
) else (
    echo Test exited with code %EXIT_CODE%.
)

echo.
pause
endlocal
exit /b %EXIT_CODE%
