@echo off
setlocal
cd /d "%~dp0"

echo ============================================================
echo  SMOKE TEST: AI Dispatch Pipeline
echo ============================================================
echo.

echo [1/3] Existing practices (should see at least one row)...
docker compose exec postgres psql -U aethera -d aethera_db -c "SELECT id, practice_name, status FROM practices LIMIT 3;"
echo.

echo [2/3] Inserting pending work queue item...
docker compose exec postgres psql -U aethera -d aethera_db -c "INSERT INTO work_queue_items (id, practice_id, queue_type, item_type, item_id, status, priority, sla_breached, created_at, updated_at) SELECT gen_random_uuid(), (SELECT id FROM practices LIMIT 1), 'coding', 'charge_entry', gen_random_uuid(), 'pending', 50, false, NOW(), NOW() RETURNING id, queue_type, item_type, status;"
echo.

echo [3/3] Tailing celery-worker logs (Ctrl+C to stop)...
echo       Watch for: ai_dispatch: item ^<uuid^> -^> completed / escalated
echo.
docker compose logs celery-worker --tail=20 --follow

endlocal
