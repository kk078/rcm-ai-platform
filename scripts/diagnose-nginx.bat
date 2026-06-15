@echo off
echo ============================================================
echo  Nginx Deep Diagnosis
echo ============================================================
echo.

echo [1] Port 8080 usage (netstat):
netstat -ano | findstr ":8080"
echo.

echo [2] Docker inspect nginx container (State section):
docker inspect rcm-ai-platform-nginx-1 --format "{{json .State}}" 2>&1
echo.

echo [3] Full docker compose up -d nginx (with stderr):
docker compose -f D:\rcm-ai-platform\docker-compose.prod.yml up -d --force-recreate nginx 2>&1
echo.

echo [4] Wait 5 seconds...
timeout /t 5 /nobreak >nul
echo.

echo [5] Container status after force-recreate:
docker compose -f D:\rcm-ai-platform\docker-compose.prod.yml ps -a 2>&1
echo.

echo [6] Nginx logs after attempt:
docker compose -f D:\rcm-ai-platform\docker-compose.prod.yml logs nginx --tail=30 2>&1
echo.

echo [7] Docker events (last relevant):
docker events --since 5m --until 0s --filter container=rcm-ai-platform-nginx-1 2>&1
echo.

echo Saving output...
(
netstat -ano | findstr ":8080"
echo ===
docker inspect rcm-ai-platform-nginx-1 --format "{{json .State}}"
echo ===
docker compose -f D:\rcm-ai-platform\docker-compose.prod.yml logs nginx --tail=50
echo ===
docker compose -f D:\rcm-ai-platform\docker-compose.prod.yml ps -a
) > D:\rcm-ai-platform\logs\nginx-diagnose.txt 2>&1

echo Done. Results in D:\rcm-ai-platform\logs\nginx-diagnose.txt
echo.
pause
