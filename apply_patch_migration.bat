@echo off
echo === Apply Patch Migration g8b04d925f33 === > D:\rcm-ai-platform\patch_migration_result.txt
echo. >> D:\rcm-ai-platform\patch_migration_result.txt

echo [1/4] Copying migration file into container... >> D:\rcm-ai-platform\patch_migration_result.txt
docker cp "D:\rcm-ai-platform\data\migrations\versions\g8b04d925f33_add_patch_columns_to_error_logs.py" rcm-ai-platform-api-1:/app/data/migrations/versions/ >> D:\rcm-ai-platform\patch_migration_result.txt 2>&1
echo. >> D:\rcm-ai-platform\patch_migration_result.txt

echo [2/4] Verify file copied successfully... >> D:\rcm-ai-platform\patch_migration_result.txt
docker exec rcm-ai-platform-api-1 bash -c "ls -la /app/data/migrations/versions/" >> D:\rcm-ai-platform\patch_migration_result.txt 2>&1
echo. >> D:\rcm-ai-platform\patch_migration_result.txt

echo [3/4] Running alembic upgrade head... >> D:\rcm-ai-platform\patch_migration_result.txt
docker exec -e PYTHONPATH=/app rcm-ai-platform-api-1 bash -c "cd /app && alembic -c /app/alembic.ini upgrade head" >> D:\rcm-ai-platform\patch_migration_result.txt 2>&1
echo. >> D:\rcm-ai-platform\patch_migration_result.txt

echo [4/4] Verify current head after upgrade... >> D:\rcm-ai-platform\patch_migration_result.txt
docker exec -e PYTHONPATH=/app rcm-ai-platform-api-1 bash -c "cd /app && alembic -c /app/alembic.ini current" >> D:\rcm-ai-platform\patch_migration_result.txt 2>&1
echo. >> D:\rcm-ai-platform\patch_migration_result.txt

echo Done. >> D:\rcm-ai-platform\patch_migration_result.txt
