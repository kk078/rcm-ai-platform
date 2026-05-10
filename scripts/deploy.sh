#!/bin/bash
set -e

echo "=== Starting deployment $(date) ==="
cd /opt/apps/rcm-ai-platform

git pull origin main

echo "Building staff portal..."
cd ui/staff-portal && npm install --production && npm run build && cd ../..

echo "Building provider portal..."
cd ui/provider-portal && npm install --production && npm run build && cd ../..

echo "Rebuilding Docker images..."
docker compose -f docker-compose.prod.yml build

echo "Restarting services..."
docker compose -f docker-compose.prod.yml up -d

sleep 15

echo "Running migrations..."
docker compose -f docker-compose.prod.yml exec -T api alembic upgrade head

HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://localhost/health)
if [ "$HTTP_CODE" = "200" ]; then
    echo "=== Deployment successful! ==="
else
    echo "=== WARNING: Health check returned $HTTP_CODE ==="
    exit 1
fi
