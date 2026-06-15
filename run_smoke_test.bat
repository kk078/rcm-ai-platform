@echo off
setlocal
cd /d "D:\rcm-ai-platform"

echo ============================================================ > smoke_test_output.txt
echo  SMOKE TEST: AI Dispatch Pipeline >> smoke_test_output.txt
echo  Started: %DATE% %TIME% >> smoke_test_output.txt
echo ============================================================ >> smoke_test_output.txt
echo. >> smoke_test_output.txt

echo [1/4] Checking Docker stack status... >> smoke_test_output.txt
docker compose ps >> smoke_test_output.txt 2>&1
echo. >> smoke_test_output.txt

echo [2/4] Existing practices (seed data check)... >> smoke_test_output.txt
docker compose exec -T postgres psql -U aethera -d aethera_db -c "SELECT id, practice_name, status FROM practices LIMIT 3;" >> smoke_test_output.txt 2>&1
echo. >> smoke_test_output.txt

echo [3/4] Inserting pending work queue item... >> smoke_test_output.txt
docker compose exec -T postgres psql -U aethera -d aethera_db -c "INSERT INTO work_queue_items (id, practice_id, queue_type, item_type, item_id, status, priority, sla_breached, created_at, updated_at) SELECT gen_random_uuid(), (SELECT id FROM practices LIMIT 1), 'coding', 'charge_entry', gen_random_uuid(), 'pending', 50, false, NOW(), NOW() RETURNING id, queue_type, item_type, status;" >> smoke_test_output.txt 2>&1
echo. >> smoke_test_output.txt

echo [4/4] Celery worker last 30 lines (checking for dispatch)... >> smoke_test_output.txt
docker compose logs celery-worker --tail=30 >> smoke_test_output.txt 2>&1
echo. >> smoke_test_output.txt

echo [5/4] Queue status after insert (last 5 items)... >> smoke_test_output.txt
docker compose exec -T postgres psql -U aethera -d aethera_db -c "SELECT id, queue_type, item_type, status, priority, created_at FROM work_queue_items ORDER BY created_at DESC LIMIT 5;" >> smoke_test_output.txt 2>&1
echo. >> smoke_test_output.txt

echo ============================================================ >> smoke_test_output.txt
echo  DONE: %DATE% %TIME% >> smoke_test_output.txt
echo ============================================================ >> smoke_test_output.txt

echo Smoke test complete. Output saved to smoke_test_output.txt
type smoke_test_output.txt
pause
