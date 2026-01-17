#!/bin/bash
# setup.sh - Quick setup script for sandbox tool

set -e

echo "=== Sandbox Snapshot Notebook Tool - Setup ==="
echo ""

# Check Python version
echo "Checking Python version..."
python_version=$(python3 --version 2>&1 | awk '{print $2}')
echo "Found Python $python_version"

# Create virtual environment
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

# Activate virtual environment
echo "Activating virtual environment..."
source venv/bin/activate

# Install dependencies
echo "Installing dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

# Create .env file if not exists
if [ ! -f ".env" ]; then
    echo "Creating .env file from template..."
    cp .env.template .env
    echo "✓ Created .env file - please update database credentials"
else
    echo "✓ .env file already exists"
fi

# Create data directories
echo "Creating data directories..."
mkdir -p data/uploads
mkdir -p data/repos
mkdir -p data/projects

# Check for Docker
if command -v docker &> /dev/null; then
    echo ""
    echo "Docker detected. You can run:"
    echo "  docker-compose up -d"
    echo ""
fi

echo ""
echo "=== Setup Complete ==="
echo ""
echo "Next steps:"
echo "1. Update .env with your database credentials"
echo "2. Start PostgreSQL (docker-compose up -d postgres)"
echo "3. Run: python -m app.dashboard"
echo ""
echo "For testing, run:"
echo "  source venv/bin/activate"
echo "  python"
echo "  >>> from app.main import startup"
echo "  >>> startup()"
echo ""
