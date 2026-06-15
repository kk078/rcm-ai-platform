@echo off
setlocal
cd /d "%~dp0"

echo ============================================================
echo  START CLOUDFLARE TUNNEL — rcm.aetherahealthcare.com
echo ============================================================
echo.

echo [1/3] Checking current cloudflared container status...
docker compose -f docker-compose.prod.yml ps cloudflared
echo.

echo [2/3] Starting cloudflared...
echo       Trying --no-deps first (safe if rest of stack already running)...
docker compose -f docker-compose.prod.yml up -d --no-deps cloudflared
if %ERRORLEVEL% neq 0 (
    echo       --no-deps failed; starting full dependency chain...
    docker compose -f docker-compose.prod.yml up -d cloudflared
)
echo.

echo [3/3] Tailing cloudflared logs (Ctrl+C to stop)...
echo       Watch for: "Registered tunnel connection" — that means the tunnel is live.
echo.
docker compose -f docker-compose.prod.yml logs cloudflared --tail=30 --follow

endlocal
