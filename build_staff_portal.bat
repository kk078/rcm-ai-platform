@echo off
cd /d D:\rcm-ai-platform\ui\staff-portal
echo Building Aethera AI Staff Portal...
call npm run build
if %errorlevel% neq 0 (
  echo BUILD FAILED. Check errors above.
  pause
  exit /b 1
)
echo Reloading nginx to pick up new build...
docker compose -f D:\rcm-ai-platform\docker-compose.prod.yml exec nginx nginx -s reload
echo.
echo Done! Staff portal deployed.
pause
