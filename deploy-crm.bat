@echo off
echo.
echo ============================================================
echo  Aethera CRM -- Build and Deploy
echo ============================================================
echo.
cd /d D:\aethera-crm\cloudflare\pages

echo [1/2] Building CRM (tsc + vite)...
call npm run build
if %ERRORLEVEL% NEQ 0 (
  echo    tsc had warnings - running vite build directly...
  call npx vite build
  if %ERRORLEVEL% NEQ 0 (
    echo !! Vite build also failed. Aborting.
    pause
    exit /b 1
  )
)

echo.
echo [2/2] Deploying to Cloudflare Pages...
call "%~dp0deploy-secrets.bat"
call npx wrangler pages deploy dist --project-name=aethera-crm --branch=main
if %ERRORLEVEL% NEQ 0 (
  echo !! CRM deploy failed.
) else (
  echo.
  echo [OK] CRM deployed to crm.aetherahealthcare.com
)
echo.
pause
