#!/bin/bash
set -e

echo "Starting services..."
docker-compose up -d --build

echo "Waiting for services to be ready..."
./scripts/wait-for-services.sh

echo "Running integration tests..."
cd tests
source venv/bin/activate
python -m pytest -v --tb=short

echo "Stopping services..."
docker-compose down
