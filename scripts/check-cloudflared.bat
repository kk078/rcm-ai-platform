@echo off
echo Checking docker stack status...
docker compose -f D:\rcm-ai-platform\docker-compose.prod.yml ps > D:\rcm-ai-platform\logs\status-check.txt 2>&1
echo Getting cloudflared logs...
docker compose -f D:\rcm-ai-platform\docker-compose.prod.yml logs cloudflared --tail=80 >> D:\rcm-ai-platform\logs\status-check.txt 2>&1
echo Done. Output saved to D:\rcm-ai-platform\logs\status-check.txt
pause
