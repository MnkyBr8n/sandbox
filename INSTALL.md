# Installation Guide

Complete setup instructions for the Sandbox Snapshot Notebook Memory System.

---

## Prerequisites

| Requirement | Version | Notes |
|-------------|---------|-------|
| Python | 3.11+ | Required |
| PostgreSQL | 14+ | Required |
| Git | Latest | Required |
| Docker | Latest | Optional (recommended) |

---

## Installation Methods

### Method 1: Automated Setup (Recommended)

```bash
# Clone the repository
git clone https://github.com/yxyel/sandbox.git
cd sandbox

# Run setup script
chmod +x setup.sh
./setup.sh

# Configure environment
cp .env.template .env
# Edit .env with your database credentials

# Start PostgreSQL
docker-compose up -d postgres

# Initialize and run
python -c "from app.main import startup; startup()"
python -m app.dashboard
```

### Method 2: Docker (Full Stack)

```bash
# Clone the repository
git clone https://github.com/yxyel/sandbox.git
cd sandbox

# Configure environment
cp .env.template .env

# Start all services
docker-compose up -d
```

> Dashboard available at `http://localhost:5000`

### Method 3: Manual Setup

```bash
# Clone the repository
git clone https://github.com/yxyel/sandbox.git
cd sandbox

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Linux/Mac
# or: venv\Scripts\activate  # Windows

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.template .env
# Edit .env with your settings

# Create PostgreSQL database
createdb sandbox

# Initialize the service
python -c "from app.main import startup; startup()"

# Start dashboard
python -m app.dashboard
```

---

## Environment Configuration

Create a `.env` file from the template:

```bash
cp .env.template .env
```

### Required Variables

```bash
SANDBOX_POSTGRES_DSN=postgresql+psycopg://user:password@localhost:5432/sandbox
SANDBOX_LOG_LEVEL=INFO
SANDBOX_LOG_JSON=false
SANDBOX_ENVIRONMENT=dev
```

### Optional Variables

```bash
SANDBOX_DATA_DIR=/path/to/data
SANDBOX_SCHEMAS_DIR=/path/to/schemas
SANDBOX_GIT_CLONE_TIMEOUT_SECONDS=120
```

---

## Database Setup

### Option 1: Docker (Recommended)

```bash
docker-compose up -d postgres
```

### Option 2: Local PostgreSQL

```bash
# Create database
createdb sandbox

# Or using psql
psql -U postgres -c "CREATE DATABASE sandbox;"
```

### Option 3: Remote Database

Update `.env` with your remote connection string:

```bash
SANDBOX_POSTGRES_DSN=postgresql+psycopg://user:password@remote-host:5432/sandbox
```

---

## Verification

Test your installation:

```python
from app.main import startup, get_metrics

# Initialize
startup()

# Check metrics
metrics = get_metrics()
print(f"Total snapshots: {metrics['snapshot_metrics']['total']}")
print(f"Total projects: {metrics['project_metrics']['total']}")
```

---

## Troubleshooting

### Database Connection Failed

```
Error: could not connect to server
```

**Solution:** Verify PostgreSQL is running and credentials are correct in `.env`.

### Schema Not Found

```
Error: Master schema not found
```

**Solution:** Ensure `schemas/master_notebook.yaml` exists.

### Module Not Found

```
ModuleNotFoundError: No module named 'app'
```

**Solution:** Run from the project root directory, or install the package:

```bash
pip install -e .
```

---

## Next Steps

1. Review [DASHBOARD_GUIDE.md](DASHBOARD_GUIDE.md) for metrics visualization
2. Review [LOGGING_UPDATES.md](LOGGING_UPDATES.md) for vendor tracking
3. See [README.md](README.md) for API usage examples
