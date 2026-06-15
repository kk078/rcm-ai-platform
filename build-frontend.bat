@echo off
setlocal

echo.
echo =====================================================
echo  Aethera Staff Portal - Docker Frontend Build
echo =====================================================
echo.

REM Check Docker is running
docker info >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo ERROR: Docker Desktop is not running or not accessible.
    echo Please start Docker Desktop and try again.
    pause
    exit /b 1
)

echo [1/3] Ensuring node:20-alpine image is available...
docker pull node:20-alpine
echo.

echo [2/3] Running Vite build inside Docker container...
echo       Source : D:\rcm-ai-platform\ui\staff-portal
echo       Output : D:\rcm-ai-platform\ui\staff-portal\dist
echo.

REM Key design decisions:
REM   - Named volume "staff_portal_nm" shadows /app/node_modules so npm install
REM     stays on Docker's Linux filesystem (fast, avoids NTFS tiny-file churn).
REM   - The dist/ output lands on the Windows NTFS path via Docker Desktop's
REM     volume driver, which handles large file writes correctly (no truncation).
REM   - --emptyOutDir overrides vite.config.ts so stale hashed assets are removed.

docker run --rm ^
  -v "D:\rcm-ai-platform\ui\staff-portal:/app" ^
  -v "staff_portal_nm:/app/node_modules" ^
  -w /app ^
  node:20-alpine ^
  sh -c "npm ci && npx vite build --emptyOutDir && echo '' && echo 'dist/assets contents:' && ls -lh dist/assets/"

set BUILD_EXIT=%ERRORLEVEL%
echo.

if %BUILD_EXIT% equ 0 (
    echo [3/3] Build SUCCEEDED.
    echo.
    echo dist\assets contents on Windows:
    dir "D:\rcm-ai-platform\ui\staff-portal\dist\assets" /b
    echo.
    echo All files in dist:
    dir "D:\rcm-ai-platform\ui\staff-portal\dist" /s /b
) else (
    echo [3/3] Build FAILED with exit code %BUILD_EXIT%.
)

echo.
pause
endlocal
