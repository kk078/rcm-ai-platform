@echo off
setlocal EnableDelayedExpansion

:: ============================================================
:: run_tests.bat — rcm-ai-platform Test Runner (Windows)
:: Runs all tests for the RCM platform (rcm.aetherahealthcare.com)
:: ============================================================

set "SCRIPT_DIR=%~dp0"
set "PLATFORM_NAME=rcm-ai-platform (rcm.aetherahealthcare.com)"
set "EXIT_CODE=0"
set "FAIL_COUNT=0"

set "GREEN=[92m"
set "RED=[91m"
set "YELLOW=[93m"
set "CYAN=[96m"
set "BOLD=[1m"
set "RESET=[0m"

echo.
echo %CYAN%============================================================%RESET%
echo %BOLD%  %PLATFORM_NAME% Test Suite%RESET%
echo %CYAN%============================================================%RESET%
echo   Started: %DATE% %TIME%
echo.

cd /d "%SCRIPT_DIR%"

:: ----------------------------------------------------------
:: 1. Locate Python
:: ----------------------------------------------------------
where python >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo %RED%[ERROR] Python not found in PATH. Aborting.%RESET%
    exit /b 1
)
for /f "tokens=*" %%v in ('python --version 2^>^&1') do set "PYTHON_VER=%%v"
echo   Python : %PYTHON_VER%

:: ----------------------------------------------------------
:: 2. Activate virtual environment
:: ----------------------------------------------------------
if exist "%SCRIPT_DIR%venv\Scripts\activate.bat" (
    call "%SCRIPT_DIR%venv\Scripts\activate.bat"
    echo   Venv   : %SCRIPT_DIR%venv
) else if exist "%SCRIPT_DIR%.venv\Scripts\activate.bat" (
    call "%SCRIPT_DIR%.venv\Scripts\activate.bat"
    echo   Venv   : %SCRIPT_DIR%.venv
) else (
    echo   Venv   : none ^(using system Python^)
)

:: ----------------------------------------------------------
:: 3. Environment variables
:: ----------------------------------------------------------
set "PYTHONPATH=%SCRIPT_DIR%;%PYTHONPATH%"
set "TEST_MODE=true"
set "DATABASE_URL=sqlite:///:memory:"
set "REDIS_URL=redis://localhost:6379/15"
set "SECRET_KEY=test-secret-key-not-for-production"
set "JWT_SECRET_KEY=test-jwt-secret-not-for-production"

:: ----------------------------------------------------------
:: 4. Ensure pytest
:: ----------------------------------------------------------
python -m pytest --version >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo %YELLOW%[WARN] pytest not found — installing...%RESET%
    python -m pip install pytest pytest-asyncio pytest-cov httpx --quiet
)

echo.
echo %CYAN%------------------------------------------------------------%RESET%
echo %BOLD%  Running UNIT tests...%RESET%
echo %CYAN%------------------------------------------------------------%RESET%

:: ----------------------------------------------------------
:: 5. Unit test suites
:: ----------------------------------------------------------
set UNIT_SUITES=0
set "UNIT[0]=AI Dispatch         :tests\unit\test_ai_dispatch.py"
set "UNIT[1]=Analytics           :tests\unit\test_analytics.py"
set "UNIT[2]=Auth                :tests\unit\test_auth.py"
set "UNIT[3]=Billing             :tests\unit\test_billing.py"
set "UNIT[4]=Charge Intake       :tests\unit\test_charge_intake.py"
set "UNIT[5]=Client Billing      :tests\unit\test_client_billing.py"
set "UNIT[6]=Client Management   :tests\unit\test_client_management.py"
set "UNIT[7]=Coding              :tests\unit\test_coding.py"
set "UNIT[8]=Denials             :tests\unit\test_denials.py"
set "UNIT[9]=Full Platform       :tests\unit\test_full_platform.py"
set "UNIT[10]=Payments           :tests\unit\test_payments.py"
set "UNIT[11]=Provider Portal    :tests\unit\test_provider_portal.py"
set "UNIT[12]=Queues             :tests\unit\test_queues.py"
set "UNIT[13]=Scrubber           :tests\unit\test_scrubber.py"
set "UNIT[14]=Tasks              :tests\unit\test_tasks.py"

for /L %%i in (0,1,14) do (
    for /f "tokens=1,2 delims=:" %%a in ("!UNIT[%%i]!") do (
        set "SUITE_NAME=%%a"
        set "SUITE_FILE=%%b"
    )
    set "SUITE_FILE=!SUITE_FILE: =!"

    if exist "!SUITE_FILE!" (
        echo.
        echo %BOLD%  Suite: !SUITE_NAME!%RESET%
        python -m pytest "!SUITE_FILE!" -v --tb=short --no-header -q 2>&1
        if !ERRORLEVEL! NEQ 0 (
            set /a FAIL_COUNT+=1
            set EXIT_CODE=1
        )
    ) else (
        echo %YELLOW%  [SKIP] !SUITE_NAME! — not found%RESET%
    )
)

:: ----------------------------------------------------------
:: 6. Integration tests (if any)
:: ----------------------------------------------------------
echo.
echo %CYAN%------------------------------------------------------------%RESET%
echo %BOLD%  Running INTEGRATION tests...%RESET%
echo %CYAN%------------------------------------------------------------%RESET%
if exist "tests\integration\" (
    python -m pytest tests\integration\ -v --tb=short -q 2>&1
    if %ERRORLEVEL% NEQ 0 (
        echo %YELLOW%  [WARN] Integration tests had failures (may need live services)%RESET%
    )
) else (
    echo   No integration tests found.
)

:: ----------------------------------------------------------
:: 7. Coverage
:: ----------------------------------------------------------
echo.
echo %CYAN%------------------------------------------------------------%RESET%
echo %BOLD%  Coverage Report%RESET%
echo %CYAN%------------------------------------------------------------%RESET%
python -m pytest tests\unit\ ^
    --cov=app --cov=workers --cov-report=term-missing ^
    --cov-report=html:coverage_html -q 2>&1
if %ERRORLEVEL% EQU 0 (
    echo %GREEN%  Coverage report: coverage_html\index.html%RESET%
) else (
    echo %YELLOW%  Coverage report had warnings%RESET%
)

:: ----------------------------------------------------------
:: 8. Summary
:: ----------------------------------------------------------
echo.
echo %CYAN%============================================================%RESET%
echo %BOLD%  TEST SUMMARY — %PLATFORM_NAME%%RESET%
echo %CYAN%============================================================%RESET%
echo   Finished : %DATE% %TIME%
if %EXIT_CODE% EQU 0 (
    echo   Result   : %GREEN%ALL SUITES PASSED%RESET%
) else (
    echo   Result   : %RED%FAILED SUITES: %FAIL_COUNT%%RESET%
)
echo %CYAN%============================================================%RESET%
echo.

exit /b %EXIT_CODE%
