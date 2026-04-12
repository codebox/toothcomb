#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

# Create virtual environment if it doesn't exist
if [ ! -d .venv ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
fi

# Activate virtual environment
source .venv/bin/activate

# Install dependencies
echo "Installing dependencies..."
python -m pip install -q --no-build-isolation -r requirements.txt

# Start the application
echo "Starting Toothcomb..."
PYTHONPATH=src python src/main.py