@echo off
echo ── Aethera AI: Full Frontend + Backend Redeploy ──
cd /d "%~dp0.."

echo [1/3] Rebuilding nginx (new config + SPA routing)...
docker compose -f docker-compose.prod.yml build nginx

echo [2/3] Restarting nginx (picks up new dist volumes)...
docker compose -f docker-compose.prod.yml up -d nginx

echo [3/3] Restarting API (new user management endpoints)...
docker compose -f docker-compose.prod.yml up -d api

echo.
echo Waiting 8 seconds for services to be healthy...
timeout /t 8 /nobreak >nul

echo.
echo Container status:
docker compose -f docker-compose.prod.yml ps nginx api

echo.
echo Staff portal:   https://rcm.aetherahealthcare.com
echo Provider portal: https://rcm.aetherahealthcare.com/portal/
echo API docs:        https://rcm.aetherahealthcare.com/api/docs
pause
