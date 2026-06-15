@echo off
echo.
echo ============================================================
echo  Aethera RCM -- Rebuild Staff and Provider Portals
echo ============================================================
echo.
cd /d D:\rcm-ai-platform

echo [1/2] Rebuilding Staff Portal...
call D:\rcm-ai-platform\build_staff_portal.bat
echo.

echo [2/2] Rebuilding Provider Portal...
call D:\rcm-ai-platform\build_provider_portal.bat
echo.

echo ============================================================
echo  Done! Both portals rebuilt and live via Docker.
echo  Staff:    https://rcm.aetherahealthcare.com
echo  Provider: https://rcm.aetherahealthcare.com/portal
echo ============================================================
echo.
pause
