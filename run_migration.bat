@echo off
echo === Alembic Migration Check === > D:\rcm-ai-platform\migration_result.txt
echo. >> D:\rcm-ai-platform\migration_result.txt

echo [1/3] Current migration head... >> D:\rcm-ai-platform\migration_result.txt
docker exec -e PYTHONPATH=/app rcm-ai-platform-api-1 bash -c "cd /app && alembic -c /app/alembic.ini current" >> D:\rcm-ai-platform\migration_result.txt 2>&1
echo. >> D:\rcm-ai-platform\migration_result.txt

echo [2/3] Running alembic upgrade head... >> D:\rcm-ai-platform\migration_result.txt
docker exec -e PYTHONPATH=/app rcm-ai-platform-api-1 bash -c "cd /app && alembic -c /app/alembic.ini upgrade head" >> D:\rcm-ai-platform\migration_result.txt 2>&1
echo. >> D:\rcm-ai-platform\migration_result.txt

echo [3/3] Post-upgrade current... >> D:\rcm-ai-platform\migration_result.txt
docker exec -e PYTHONPATH=/app rcm-ai-platform-api-1 bash -c "cd /app && alembic -c /app/alembic.ini current" >> D:\rcm-ai-platform\migration_result.txt 2>&1
echo. >> D:\rcm-ai-platform\migration_result.txt

echo Done. >> D:\rcm-ai-platform\migration_result.txt
