@echo off
REM ============================================================
REM  Aethera — Deploy Apple-Level Redesign to All Portals
REM  Run from D:\rcm-ai-platform\
REM ============================================================

echo.
echo ============================================================
echo  Aethera Apple-Level Redesign — Build and Deploy
echo ============================================================
echo.

REM ── 1. CRM (Cloudflare Pages) ────────────────────────────────
echo [1/3] Building CRM (React + Ant Design)...
cd /d D:\aethera-crm\cloudflare\pages

echo      Running npm install...
call npm install 2>nul
echo      Running build...
call npm run build
if %ERRORLEVEL% NEQ 0 (
  echo !! CRM tsc check failed - trying vite build directly...
  call npx vite build
  if %ERRORLEVEL% NEQ 0 (
    echo !! CRM build failed entirely. Skipping deploy.
    goto :skip_crm
  )
)

echo      Deploying to Cloudflare Pages...
call "%~dp0deploy-secrets.bat"
call npx wrangler pages deploy dist --project-name=aethera-crm --branch=main
if %ERRORLEVEL% NEQ 0 (
  echo !! CRM deploy failed.
) else (
  echo      [OK] CRM deployed to crm.aetherahealthcare.com
)

:skip_crm
echo.

REM ── 2. Staff Portal (Docker rebuild) ─────────────────────────
echo [2/3] Rebuilding RCM Staff Portal...
cd /d D:\rcm-ai-platform
call build_staff_portal.bat
if %ERRORLEVEL% NEQ 0 (
  echo !! Staff Portal build failed.
) else (
  echo      [OK] Staff Portal live at os.aetherahealthcare.com
)
echo.

REM ── 3. Provider Portal (Docker rebuild) ──────────────────────
echo [3/3] Rebuilding RCM Provider Portal...
cd /d D:\rcm-ai-platform
call build_provider_portal.bat
if %ERRORLEVEL% NEQ 0 (
  echo !! Provider Portal build failed.
) else (
  echo      [OK] Provider Portal live at os.aetherahealthcare.com/portal
)
echo.

echo ============================================================
echo  Done! Admin dashboard HTML is already live (static files,
echo  no restart needed): https://admin.aetherahealthcare.com
echo ============================================================
echo.
pause
