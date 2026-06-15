@echo off
echo ================================================================
echo  Aethera -- Deploy All Fixes
echo ================================================================

REM 1. Reload nginx to pick up new provider portal dist files
echo [1/3] Reloading nginx...
docker exec aethera-ai-nginx-1 nginx -s reload
if errorlevel 1 (
  echo Nginx reload failed - trying container restart...
  docker restart aethera-ai-nginx-1
)

REM 2. Reload PM2 admin server (picks up favicon fix + new password)
echo [2/3] Reloading PM2 admin...
cd /d D:\aetherahealthcare-website\aethera-admin
pm2 reload aethera-admin

REM 3. Reset RCM master login password
echo [3/3] Resetting RCM password...
docker exec aethera-ai-api-1 python scripts/reset_pw.py

echo.
echo All done! Provider portal, admin favicon, and passwords updated.
pause
