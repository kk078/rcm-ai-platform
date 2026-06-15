@echo off
echo === Docker PS (all containers) === > D:\rcm-ai-platform\container_status.txt
docker ps -a >> D:\rcm-ai-platform\container_status.txt 2>&1
echo. >> D:\rcm-ai-platform\container_status.txt
echo === Docker Compose PS === >> D:\rcm-ai-platform\container_status.txt
cd /d D:\rcm-ai-platform
docker compose ps >> D:\rcm-ai-platform\container_status.txt 2>&1
echo. >> D:\rcm-ai-platform\container_status.txt
echo === Container Names Only === >> D:\rcm-ai-platform\container_status.txt
docker ps --format "{{.Names}}" >> D:\rcm-ai-platform\container_status.txt 2>&1
echo Done. >> D:\rcm-ai-platform\container_status.txt
