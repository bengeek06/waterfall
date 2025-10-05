#!/bin/bash
set -e

echo "🚀 Starting integration test suite..."

# Clean up any existing containers to ensure fresh start
echo "Cleaning up any existing containers..."
docker-compose down -v --remove-orphans 2>/dev/null || true

# Start services with build
echo "Starting services with fresh build..."
docker-compose up -d --build

# Wait for services to be ready
echo "Waiting for all services to be ready..."
if ! ./scripts/wait-for-services.sh; then
    echo "❌ Failed to start services properly"
    echo "Showing service logs for debugging:"
    docker-compose logs
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

# Run the tests
if python -m pytest -v --tb=short; then
    echo "✅ All tests passed!"
    test_result=0
else
    echo "❌ Some tests failed"
    test_result=1
fi

# Return to original directory
cd ..

# Stop services
echo "Stopping services..."
docker-compose down

# Exit with test result
exit $test_result