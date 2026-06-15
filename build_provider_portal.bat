@echo off
cd /d D:\rcm-ai-platform
echo ============================================================
echo  Aethera AI — Build + Deploy Provider Portal (Redesign)
echo ============================================================

REM ── 1. Install dependencies ──────────────────────────────────
echo.
echo [1/3] Installing npm dependencies...
cd ui\provider-portal
call npm install --legacy-peer-deps
if errorlevel 1 (echo ERROR: npm install failed & pause & exit /b 1)
echo Dependencies installed.

REM ── 2. Build to temp dir (avoids nginx EPERM on dist/) ───────
echo.
echo [2/3] Building provider portal...
set TMPOUT=C:\Temp\provider-dist-%RANDOM%
call npx vite build --outDir %TMPOUT%
if errorlevel 1 (echo ERROR: Vite build failed & pause & exit /b 1)
echo Build successful.

REM ── 3. Copy to nginx-served dist/ ────────────────────────────
echo.
echo [3/3] Deploying to dist/...
if not exist dist mkdir dist
xcopy /E /Y /I %TMPOUT%\* dist\
rmdir /S /Q %TMPOUT%
echo Deployed.

cd ..\..

echo.
echo ============================================================
echo  Provider portal redesign is LIVE!
echo  Visit: https://rcm.aetherahealthcare.com/portal/login
echo ============================================================
pause
