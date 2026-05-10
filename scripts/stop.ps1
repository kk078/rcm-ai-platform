# MedClaim AI — Stop Production Services

Set-Location "D:\rcm-ai-platform"

Write-Host "Stopping MedClaim AI services..." -ForegroundColor Yellow

docker compose -f docker-compose.prod.yml down

if ($LASTEXITCODE -eq 0) {
    Write-Host "All services stopped." -ForegroundColor Green
    Write-Host "Your site is now offline." -ForegroundColor Gray
} else {
    Write-Host "Error stopping services. Check Docker status." -ForegroundColor Red
    exit 1
}