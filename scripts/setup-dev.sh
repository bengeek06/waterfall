#!/bin/bash
set -e

echo "Setting up development environment..."

# Setup tests environment
cd tests
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi
source venv/bin/activate
pip install -r requirements.txt
cd ..

echo "Development environment ready!"
