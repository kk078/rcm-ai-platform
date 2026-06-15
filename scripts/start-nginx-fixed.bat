@echo off
echo ============================================================
echo  Start nginx (port 8088) + cloudflared
echo ============================================================
echo.

echo [1/4] Force-recreate nginx with new port (8088:80)...
docker compose -f D:\rcm-ai-platform\docker-compose.prod.yml up -d --force-recreate nginx 2>&1
echo.

echo [2/4] Waiting 20 seconds for nginx to reach healthy state...
timeout /t 20 /nobreak
echo.

echo [3/4] Container status:
docker compose -f D:\rcm-ai-platform\docker-compose.prod.yml ps -a 2>&1
echo.

echo [4/4] Nginx logs:
docker compose -f D:\rcm-ai-platform\docker-compose.prod.yml logs nginx --tail=30 2>&1
echo.

echo Starting cloudflared (depends on nginx healthy)...
docker compose -f D:\rcm-ai-platform\docker-compose.prod.yml up -d cloudflared 2>&1
echo.

echo Waiting 15 seconds for cloudflared...
timeout /t 15 /nobreak
echo.

echo Final status:
docker compose -f D:\rcm-ai-platform\docker-compose.prod.yml ps -a 2>&1
echo.

echo Cloudflared logs:
docker compose -f D:\rcm-ai-platform\docker-compose.prod.yml logs cloudflared --tail=20 2>&1
echo.

echo Saving results...
(
docker compose -f D:\rcm-ai-platform\docker-compose.prod.yml ps -a
echo ===NGINX LOGS===
docker compose -f D:\rcm-ai-platform\docker-compose.prod.yml logs nginx --tail=50
echo ===CLOUDFLARED LOGS===
docker compose -f D:\rcm-ai-platform\docker-compose.prod.yml logs cloudflared --tail=30
) > D:\rcm-ai-platform\logs\nginx-start-result.txt 2>&1

echo Done. Results in D:\rcm-ai-platform\logs\nginx-start-result.txt
echo.
pause
