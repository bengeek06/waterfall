#!/bin/bash

set -e

COMPOSE_FILE="compose/docker-compose.backend.yml"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_ROOT"

# Clean up any existing containers to ensure fresh start
echo "Cleaning up any existing containers..."
$DOCKER_COMPOSE down --remove-orphans 2>/dev/null || true

echo "🚀 Starting backend services with development tools..."
docker compose -f "$COMPOSE_FILE" up --build

echo "✅ Backend services started successfully!"
echo "📊 PgAdmin: http://localhost:5050"
echo "📚 Swagger UI: http://localhost:8081"
echo "🔐 Auth Service: http://localhost:5001"
echo "👤 Identity Service: http://localhost:5002"
echo "🛡️ Guardian Service: http://localhost:5003"
echo "� Project Service: http://localhost:5006"
echo "�📝 Basic IO Service: http://localhost:5004"
echo "💾 Storage Service: http://localhost:5005"
echo "🗄️ MinIO Console: http://localhost:9001"
