@echo off
REM ============================================================
REM  Aethera — Deploy Logo & Favicon Update to All Sites
REM  Run from D:\rcm-ai-platform\
REM ============================================================

echo.
echo ============================================================
echo  Aethera Logo Update — Build and Deploy All Sites
echo ============================================================
echo.

REM ── 1. Marketing Website (Next.js → Cloudflare Pages) ────────
echo [1/4] Deploying Marketing Website...
cd /d D:\aetherahealthcare-website
call deploy-now.bat
echo.

REM ── 2. CRM (React + Vite → Cloudflare Pages) ─────────────────
echo [2/4] Building and deploying CRM...
cd /d D:\aethera-crm\cloudflare\pages
call npm run build
if %ERRORLEVEL% NEQ 0 (
  echo !! CRM build failed. Trying vite directly...
  call npx vite build
)
call "%~dp0deploy-secrets.bat"
call npx wrangler pages deploy dist --project-name=aethera-crm --branch=main
echo.

REM ── 3. RCM Staff Portal (Docker rebuild) ─────────────────────
echo [3/4] Rebuilding RCM Staff Portal...
cd /d D:\rcm-ai-platform
call build_staff_portal.bat
echo.

REM ── 4. RCM Provider Portal (Docker rebuild) ──────────────────
echo [4/4] Rebuilding RCM Provider Portal...
cd /d D:\rcm-ai-platform
call build_provider_portal.bat
echo.

echo ============================================================
echo  Done! All sites updated with new Aethera monogram logo.
echo  Admin dashboard is static HTML — no restart needed.
echo  (favicon.svg and favicon.ico already in place)
echo ============================================================
echo.
pause
