# Run this from D:\rcm-ai-platform in PowerShell
# Applies migrations, creates admin user, restarts nginx + api

$compose = "docker compose -f docker-compose.prod.yml"

Write-Host "`n=== Running database migrations ===" -ForegroundColor Cyan
& docker compose -f docker-compose.prod.yml exec -e PYTHONPATH=/app api alembic upgrade head

Write-Host "`n=== Creating/updating admin user ===" -ForegroundColor Cyan
& docker compose -f docker-compose.prod.yml exec -e PYTHONPATH=/app api python scripts/create_admin.py

Write-Host "`n=== Restarting nginx (picks up new frontend dist) ===" -ForegroundColor Cyan
& docker compose -f docker-compose.prod.yml restart nginx

Write-Host "`n=== Restarting API (picks up model changes) ===" -ForegroundColor Cyan
& docker compose -f docker-compose.prod.yml restart api

Write-Host "`n=== Waiting for health checks ===" -ForegroundColor Cyan
Start-Sleep -Seconds 10
& docker compose -f docker-compose.prod.yml ps

Write-Host "`nDone! Visit https://rcm.aetherahealthcare.com" -ForegroundColor Green
