@echo off
echo ============================================================
echo  Force-recreate nginx with curl healthcheck + start cloudflared
echo ============================================================
echo.

echo [1] Force-recreating nginx...
docker compose -f D:\rcm-ai-platform\docker-compose.prod.yml up -d --force-recreate nginx 2>&1
echo.

echo [2] Waiting 45s for nginx to become healthy...
timeout /t 45 /nobreak
echo.

echo [3] Status check:
docker compose -f D:\rcm-ai-platform\docker-compose.prod.yml ps -a 2>&1
echo.

echo [4] Nginx health detail:
docker inspect rcm-ai-platform-nginx-1 --format "Status={{.State.Status}} Health={{.State.Health.Status}}" 2>&1
echo.

echo [5] Starting cloudflared...
docker compose -f D:\rcm-ai-platform\docker-compose.prod.yml up -d cloudflared 2>&1
echo.

echo [6] Waiting 20s for cloudflared...
timeout /t 20 /nobreak
echo.

echo [7] Final status:
docker compose -f D:\rcm-ai-platform\docker-compose.prod.yml ps -a 2>&1
echo.

echo [8] Cloudflared logs:
docker compose -f D:\rcm-ai-platform\docker-compose.prod.yml logs cloudflared --tail=30 2>&1
echo.

echo Saving to log...
(
echo === STATUS ===
docker compose -f D:\rcm-ai-platform\docker-compose.prod.yml ps -a
echo.
echo === NGINX INSPECT ===
docker inspect rcm-ai-platform-nginx-1 --format "Status={{.State.Status}} Health={{.State.Health.Status}}"
echo.
echo === NGINX HEALTH LOG ===
docker inspect rcm-ai-platform-nginx-1 --format "{{range .State.Health.Log}}Exit={{.ExitCode}} Out={{.Output}}---{{end}}"
echo.
echo === CLOUDFLARED LOGS ===
docker compose -f D:\rcm-ai-platform\docker-compose.prod.yml logs cloudflared --tail=40
) > D:\rcm-ai-platform\logs\nginx-fix-result.txt 2>&1

echo Done. See D:\rcm-ai-platform\logs\nginx-fix-result.txt
echo.
pause
