@echo off
echo.
echo ============================================================
echo  Aethera -- Set Master Login (kirkmar078@gmail.com)
echo  Password: AetheraisGr8!
echo ============================================================
echo.

REM ── 1. RCM Staff + Provider Portals (FastAPI / PostgreSQL) ────
echo [1/2] Resetting password on RCM portals (Staff + Provider)...
echo        Running reset_pw.py inside the api container...
docker exec aethera-ai-api-1 python scripts/reset_pw.py
if %ERRORLEVEL% NEQ 0 (
  echo.
  echo  Trying alternate container name...
  docker exec rcm-ai-platform-api-1 python scripts/reset_pw.py
)
echo.

REM ── 2. Admin Dashboard (restart Express to pick up new .env) ──
echo [2/2] Restarting Admin server to apply new password...
cd /d D:\aetherahealthcare-website\aethera-admin
call restart-admin.bat
echo.

echo ============================================================
echo  Master login set! Use these credentials on all sites:
echo.
echo  Email/Username : kirkmar078@gmail.com
echo  Password       : AetheraisGr8!
echo.
echo  Sites:
echo    RCM Staff    : https://rcm.aetherahealthcare.com/login
echo    RCM Provider : https://rcm.aetherahealthcare.com/portal/login
echo    Admin        : https://admin.aetherahealthcare.com  (password only)
echo    CRM          : https://crm.aetherahealthcare.com    (ALREADY LIVE)
echo ============================================================
echo.
pause
