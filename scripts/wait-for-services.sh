#!/bin/bash
set -e

echo "Waiting for services to be ready..."

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
        sleep 2
        attempt=$((attempt + 1))
    done
    
    echo "✗ $service_name failed to start after $max_attempts attempts"
    return 1
}

# Check database
echo "Checking database connection..."
max_db_attempts=30
db_attempt=1

while [ $db_attempt -le $max_db_attempts ]; do
    if docker-compose exec -T db_service pg_isready -U staging > /dev/null 2>&1; then
        echo "✓ Database is ready"
        break
    fi
    
    echo "Attempt $db_attempt/$max_db_attempts: Database not ready yet..."
    sleep 2
    db_attempt=$((db_attempt + 1))
done

if [ $db_attempt -gt $max_db_attempts ]; then
    echo "✗ Database failed to start"
    exit 1
fi

# Check all services
check_service "http://localhost:5001/health" "Auth Service" || exit 1
check_service "http://localhost:5002/health" "Identity Service" || exit 1
check_service "http://localhost:5003/health" "Guardian Service" || exit 1

echo "All services are ready! 🚀"