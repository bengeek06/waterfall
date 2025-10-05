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

# Define test sections to run in order
test_sections=(
    "init"
    "login"
)

# Run each test section and track results
overall_result=0
declare -A section_results

for section in "${test_sections[@]}"; do
    echo ""
    echo "🧪 Running $section tests..."
    
    if python -m pytest -v --tb=short -k "$section"; then
        echo "✅ $section tests passed!"
        section_results[$section]=0
    else
        echo "❌ $section tests failed"
        section_results[$section]=1
        overall_result=1
        # Continue running other tests even if one section fails
    fi
done

# Summary using stored results
echo ""
echo "📋 Test Summary:"
for section in "${test_sections[@]}"; do
    if [ "${section_results[$section]}" -eq 0 ]; then
        echo "  ✅ $section"
    else
        echo "  ❌ $section"
    fi
done

if [ $overall_result -eq 0 ]; then
    echo "🎉 All test sections passed!"
else
    echo "💥 Some test sections failed"
fi

# Return to original directory
cd ..

# Stop services
echo "Stopping services..."
docker-compose down

# Exit with test result
exit $overall_result