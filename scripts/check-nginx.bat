@echo off
echo Getting nginx logs...
docker compose -f D:\rcm-ai-platform\docker-compose.prod.yml logs nginx --tail=100 > D:\rcm-ai-platform\logs\nginx-check.txt 2>&1
echo Getting nginx inspect...
docker inspect rcm-ai-platform-nginx-1 >> D:\rcm-ai-platform\logs\nginx-check.txt 2>&1
echo Done. Output saved to D:\rcm-ai-platform\logs\nginx-check.txt
pause
