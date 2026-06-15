@echo off
echo ============================================================
echo  Nginx Health Check Debug
echo ============================================================

echo [1] Nginx container status:
docker inspect rcm-ai-platform-nginx-1 --format "State: {{.State.Status}} | Health: {{.State.Health.Status}}" 2>&1
echo.

echo [2] Last 5 health check results:
docker inspect rcm-ai-platform-nginx-1 --format "{{range .State.Health.Log}}Exit={{.ExitCode}} Output={{.Output}}{{end}}" 2>&1
echo.

echo [3] Full nginx logs (last 50):
docker compose -f D:\rcm-ai-platform\docker-compose.prod.yml logs nginx --tail=50 2>&1
echo.

echo [4] Test wget inside container:
docker exec rcm-ai-platform-nginx-1 wget -qO- http://localhost/health 2>&1
echo Exit code: %ERRORLEVEL%
echo.

echo [5] Test curl inside container (if available):
docker exec rcm-ai-platform-nginx-1 curl -sf http://localhost/health 2>&1
echo Exit code: %ERRORLEVEL%
echo.

echo [6] Check nginx process inside container:
docker exec rcm-ai-platform-nginx-1 nginx -t 2>&1
echo.

echo [7] Check if nginx is listening:
docker exec rcm-ai-platform-nginx-1 netstat -tlnp 2>&1
echo.

echo Saving results...
(
echo === CONTAINER STATE ===
docker inspect rcm-ai-platform-nginx-1 --format "State: {{.State.Status}} | Health: {{.State.Health.Status}}"
echo.
echo === HEALTH CHECK LOG ===
docker inspect rcm-ai-platform-nginx-1 --format "{{range .State.Health.Log}}ExitCode={{.ExitCode}} Output={{.Output}}---END---{{end}}"
echo.
echo === NGINX LOGS ===
docker compose -f D:\rcm-ai-platform\docker-compose.prod.yml logs nginx --tail=100
echo.
echo === WGET TEST ===
docker exec rcm-ai-platform-nginx-1 wget -qO- http://localhost/health
echo WGET_EXIT=%ERRORLEVEL%
echo.
echo === CURL TEST ===
docker exec rcm-ai-platform-nginx-1 curl -sf http://localhost/health
echo CURL_EXIT=%ERRORLEVEL%
) > D:\rcm-ai-platform\logs\nginx-debug.txt 2>&1

echo Done. Results in D:\rcm-ai-platform\logs\nginx-debug.txt
echo.
pause
