@echo off
echo ============================================================
echo  Full Stack Status Check
echo ============================================================
echo.

echo [1] All containers (ps -a):
docker compose -f D:\rcm-ai-platform\docker-compose.prod.yml ps -a

echo.
echo [2] nginx logs (last 50 lines):
docker compose -f D:\rcm-ai-platform\docker-compose.prod.yml logs nginx --tail=50

echo.
echo [3] cloudflared logs (last 20 lines):
docker compose -f D:\rcm-ai-platform\docker-compose.prod.yml logs cloudflared --tail=20

echo.
echo Saving to log file...
docker compose -f D:\rcm-ai-platform\docker-compose.prod.yml ps -a > D:\rcm-ai-platform\logs\full-status.txt 2>&1
docker compose -f D:\rcm-ai-platform\docker-compose.prod.yml logs nginx --tail=50 >> D:\rcm-ai-platform\logs\full-status.txt 2>&1
docker compose -f D:\rcm-ai-platform\docker-compose.prod.yml logs cloudflared --tail=20 >> D:\rcm-ai-platform\logs\full-status.txt 2>&1
echo Done. Results in D:\rcm-ai-platform\logs\full-status.txt
echo.
pause
