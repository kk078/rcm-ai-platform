@echo off
echo Checking Alembic migration status...
docker exec rcm-api alembic current > D:\rcm-ai-platform\migration_status.txt 2>&1
echo Exit code: %ERRORLEVEL% >> D:\rcm-ai-platform\migration_status.txt

echo.
echo Checking if patch columns exist in DB...
docker exec rcm-api python -c "import asyncio, asyncpg, os; async def check(): conn = await asyncpg.connect(os.environ['DATABASE_URL']); rows = await conn.fetch(\"SELECT column_name FROM information_schema.columns WHERE table_name='error_logs' ORDER BY ordinal_position\"); [print(r['column_name']) for r in rows]; await conn.close(); asyncio.run(check())" >> D:\rcm-ai-platform\migration_status.txt 2>&1

echo.
echo Running migration if needed...
docker exec rcm-api alembic upgrade head >> D:\rcm-ai-platform\migration_status.txt 2>&1
echo Upgrade exit code: %ERRORLEVEL% >> D:\rcm-ai-platform\migration_status.txt

echo Done. Results in D:\rcm-ai-platform\migration_status.txt
pause
