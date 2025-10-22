#!/bin/bash
set -e

echo "🚀 Starting test environment..."

# Function to detect docker compose command
get_docker_compose_cmd() {
    if command -v docker-compose &> /dev/null; then
        echo "docker-compose"
    elif docker compose version &> /dev/null; then
        echo "docker compose"
    else
        echo "ERROR: Neither docker-compose nor docker compose found" >&2
        exit 1
    fi
}

DOCKER_COMPOSE=$(get_docker_compose_cmd)
echo "Using: $DOCKER_COMPOSE"

# Clean up any existing containers to ensure fresh start
echo "Cleaning up any existing containers..."
$DOCKER_COMPOSE down -v --remove-orphans 2>/dev/null || true

# Start services with build
echo "Starting services with fresh build..."
COMPOSE_FILE="docker-compose.test.yml"
$DOCKER_COMPOSE -f "$COMPOSE_FILE" up -d --build

# Wait for services to be ready
echo "Waiting for all services to be ready..."
if ! ./scripts/wait-for-services.sh; then
    echo "❌ Failed to start services properly"
    echo "Showing service logs for debugging:"
    $DOCKER_COMPOSE logs
    exit 1
fi

echo "✅ All services started successfully"

# Run tests
echo "Running integration tests..."
cd tests

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo "Creating Python virtual environment..."
    python3 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt
else
    source venv/bin/activate
fi

# Run pytest on specific directories
echo ""
echo "🧪 Running tests..."

# Define test directories to run
test_dirs=(
    "api"
    "ui/login"
)

# Run each test directory and track results
overall_result=0
declare -A dir_results

for test_dir in "${test_dirs[@]}"; do
    echo ""
    echo "🧪 Running tests in $test_dir..."
    
    if [ -d "$test_dir" ]; then
        if python -m pytest -v --tb=short "$test_dir/"; then
            echo "✅ $test_dir tests passed!"
            dir_results[$test_dir]=0
        else
            echo "❌ $test_dir tests failed"
            dir_results[$test_dir]=1
            overall_result=1
            # Continue running other tests even if one directory fails
        fi
    else
        echo "⚠️  Directory $test_dir does not exist, skipping..."
        dir_results[$test_dir]="skipped"
    fi
done

# Summary using stored results
echo ""
echo "📋 Test Summary:"
for test_dir in "${test_dirs[@]}"; do
    if [ "${dir_results[$test_dir]}" == "0" ]; then
        echo "  ✅ $test_dir"
    elif [ "${dir_results[$test_dir]}" == "skipped" ]; then
        echo "  ⚠️  $test_dir (skipped)"
    else
        echo "  ❌ $test_dir"
    fi
done

if [ $overall_result -eq 0 ]; then
    echo "🎉 All tests passed!"
else
    echo "💥 Some tests failed"
fi

# Return to original directory
cd ..

# Stop services
echo "Stopping services..."
$DOCKER_COMPOSE down

# Exit with test result
exit $overall_result