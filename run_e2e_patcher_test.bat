@echo off
setlocal

echo.
echo === AI Auto-Debugger E2E Test ===
echo Runs test_e2e_patcher.py inside the API container
echo.

REM ── Check container is running ──────────────────────────────────────────
docker inspect --format="{{.State.Status}}" rcm-ai-platform-api-1 >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Container rcm-ai-platform-api-1 not found.
    echo         Start the stack with: docker compose up -d
    exit /b 1
)

REM ── Copy the test script into the container ─────────────────────────────
echo [1/2] Copying test script into container...
docker cp "D:\rcm-ai-platform\scripts\test_e2e_patcher.py" rcm-ai-platform-api-1:/app/scripts/test_e2e_patcher.py
if errorlevel 1 (
    echo [ERROR] docker cp failed
    exit /b 1
)
echo       Copied OK

REM ── Run the test ─────────────────────────────────────────────────────────
echo [2/2] Running E2E test (may take up to 3 minutes for AI analysis)...
echo.
docker exec -e PYTHONPATH=/app rcm-ai-platform-api-1 python /app/scripts/test_e2e_patcher.py

set EXIT_CODE=%errorlevel%
echo.
if %EXIT_CODE% equ 0 (
    echo Test exited cleanly.
) else (
    echo Test exited with code %EXIT_CODE%.
)

endlocal
exit /b %EXIT_CODE%
