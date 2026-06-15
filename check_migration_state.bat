@echo off
echo === Migration Diagnostics === > D:\rcm-ai-platform\migration_diag.txt
echo. >> D:\rcm-ai-platform\migration_diag.txt

echo [1/4] Alembic history (all known revisions in container)... >> D:\rcm-ai-platform\migration_diag.txt
docker exec -e PYTHONPATH=/app rcm-ai-platform-api-1 bash -c "cd /app && alembic -c /app/alembic.ini history --verbose 2>&1 | tail -30" >> D:\rcm-ai-platform\migration_diag.txt 2>&1
echo. >> D:\rcm-ai-platform\migration_diag.txt

echo [2/4] Check if patch migration file exists in container... >> D:\rcm-ai-platform\migration_diag.txt
docker exec rcm-ai-platform-api-1 bash -c "find /app -name '*patch*' -o -name '*g8b04d925f33*' 2>/dev/null" >> D:\rcm-ai-platform\migration_diag.txt 2>&1
echo. >> D:\rcm-ai-platform\migration_diag.txt

echo [3/4] List all migration version files in container... >> D:\rcm-ai-platform\migration_diag.txt
docker exec rcm-ai-platform-api-1 bash -c "ls -la /app/data/migrations/versions/ 2>/dev/null || ls -la /app/migrations/versions/ 2>/dev/null || find /app -path '*/migrations/versions/*.py' 2>/dev/null" >> D:\rcm-ai-platform\migration_diag.txt 2>&1
echo. >> D:\rcm-ai-platform\migration_diag.txt

echo [4/4] Check if patch columns exist in error_logs table... >> D:\rcm-ai-platform\migration_diag.txt
docker exec rcm-ai-platform-api-1 bash -c "cd /app && python -c \"from src.config import get_settings; s=get_settings(); print(s.DATABASE_URL[:30])\"" >> D:\rcm-ai-platform\migration_diag.txt 2>&1
docker exec -e PYTHONPATH=/app rcm-ai-platform-api-1 bash -c "cd /app && python -c \"
from src.config import get_settings
from sqlalchemy import create_engine, inspect
s = get_settings()
engine = create_engine(s.DATABASE_URL)
inspector = inspect(engine)
cols = [c['name'] for c in inspector.get_columns('error_logs')]
patch_cols = [c for c in cols if 'patch' in c]
print('All error_logs columns:', cols)
print('Patch columns found:', patch_cols)
\"" >> D:\rcm-ai-platform\migration_diag.txt 2>&1
echo. >> D:\rcm-ai-platform\migration_diag.txt

echo Done. >> D:\rcm-ai-platform\migration_diag.txt
