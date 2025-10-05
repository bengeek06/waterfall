#!/bin/bash
set -e

echo "Waiting for services to be ready..."

# Function to cleanup and exit on failure
cleanup_and_exit() {
    echo "🚨 Service startup failed. Cleaning up..."
    docker-compose down
    echo "Showing logs for failed services:"
    docker-compose logs
    exit 1
}

# Wait for database with health check
echo "Waiting for PostgreSQL to be healthy..."
max_attempts=60
attempt=1

while [ $attempt -le $max_attempts ]; do
    if docker-compose exec -T db_service pg_isready -U staging -d staging > /dev/null 2>&1; then
        echo "✓ Database is ready"
        break
    fi
    
    echo "Attempt $attempt/$max_attempts: Database not ready yet..."
    sleep 2
    attempt=$((attempt + 1))
done

if [ $attempt -gt $max_attempts ]; then
    echo "✗ Database failed to start"
    cleanup_and_exit
fi

# Function to check if a service is responding
check_service() {
    local url=$1
    local service_name=$2
    local max_attempts=30
    local attempt=1

    echo "Checking $service_name..."
    
    while [ $attempt -le $max_attempts ]; do
        if curl -f -s "$url" > /dev/null 2>&1; then
            echo "✓ $service_name is ready"
            return 0
        fi
        
        echo "Attempt $attempt/$max_attempts: $service_name not ready yet..."
        sleep 3
        attempt=$((attempt + 1))
    done
    
    echo "✗ $service_name failed to start after $max_attempts attempts"
    return 1
}

# Check all services
echo "Checking application services..."
check_service "http://localhost:5001/health" "Auth Service" || cleanup_and_exit
check_service "http://localhost:5002/health" "Identity Service" || cleanup_and_exit
check_service "http://localhost:5003/health" "Guardian Service" || cleanup_and_exit

echo "All services are ready! 🚀"