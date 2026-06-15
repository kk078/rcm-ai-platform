@echo off
echo.
echo ============================================================
echo  Aethera -- Deploy Favicon Fixes (cache-busted v2)
echo ============================================================
echo.

REM ── 1. RCM Portals (staff + provider) ─────────────────────────
echo [1/3] Rebuilding Staff Portal (favicon cache-bust)...
call D:\rcm-ai-platform\build_staff_portal.bat

echo.
echo [2/3] Rebuilding Provider Portal (favicon cache-bust)...
call D:\rcm-ai-platform\build_provider_portal.bat

echo.

REM ── 3. Admin (restart Express to serve updated HTML) ──────────
echo [3/3] Restarting Admin server (new favicon links)...
cd /d D:\aetherahealthcare-website\aethera-admin
call restart-admin.bat

echo.
echo ============================================================
echo  ALSO NEEDED (run separately):
echo  Rebuild marketing website at D:\aetherahealthcare-website
echo    > rebuild-website.bat
echo  (Next.js rebuild + Cloudflare Pages deploy)
echo ============================================================
echo.
pause
