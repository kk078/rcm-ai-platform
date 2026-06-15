@echo off
echo ============================================================
echo  Rebuilding nginx container with DNS resolver fix
echo ============================================================
echo.

echo [1/4] Stopping nginx container...
docker compose -f D:\rcm-ai-platform\docker-compose.prod.yml stop nginx
echo.

echo [2/4] Rebuilding nginx image (picks up new nginx.conf)...
docker compose -f D:\rcm-ai-platform\docker-compose.prod.yml build --no-cache nginx
echo.

echo [3/4] Starting nginx (and cloudflared which depends on it)...
docker compose -f D:\rcm-ai-platform\docker-compose.prod.yml up -d nginx cloudflared
echo.

echo [4/4] Waiting 15 seconds then checking status...
timeout /t 15 /nobreak
echo.

docker compose -f D:\rcm-ai-platform\docker-compose.prod.yml ps > D:\rcm-ai-platform\logs\post-nginx-fix.txt 2>&1
docker compose -f D:\rcm-ai-platform\docker-compose.prod.yml logs nginx --tail=30 >> D:\rcm-ai-platform\logs\post-nginx-fix.txt 2>&1
docker compose -f D:\rcm-ai-platform\docker-compose.prod.yml logs cloudflared --tail=20 >> D:\rcm-ai-platform\logs\post-nginx-fix.txt 2>&1

echo.
echo Results saved to D:\rcm-ai-platform\logs\post-nginx-fix.txt
echo.
echo Stack status:
docker compose -f D:\rcm-ai-platform\docker-compose.prod.yml ps
echo.
pause
