# Dashboard Usage Guide

## Overview

Simple metrics dashboard for V1 testing and visualization. Shows real-time snapshot and project statistics.

## Setup

### 1. Install Dependencies
```bash
pip install -r requirements.txt
# Now includes Flask>=3.0.0
```

### 2. Ensure Database Running
```bash
# Docker
docker-compose up -d postgres

# Or local PostgreSQL
# Make sure SANDBOX_POSTGRES_DSN is set
```

### 3. Run Dashboard
```bash
python -m sandbox.app.dashboard

# Dashboard available at:
# http://localhost:5000
```

## Dashboard Features

### Metrics Displayed

**Summary Cards:**
- Total Snapshots - All snapshots in DB
- Total Projects - Unique project count
- Recent (24h) - Snapshots created in last 24 hours

**Snapshots by Type:**
- Code snapshots count
- Text snapshots count

**Projects Table:**
- Project ID
- Code snapshots per project
- Text snapshots per project
- Total per project

### Auto-Refresh

- Auto-refreshes every 30 seconds
- Manual refresh button available

## API Endpoints

### `GET /`
Returns HTML dashboard

### `GET /api/metrics`
Returns JSON metrics

**Example Response:**
```json
{
  "snapshot_metrics": {
    "total": 45,
    "by_type": {
      "code": 30,
      "text": 15
    },
    "recent_24h": 12
  },
  "project_metrics": {
    "total": 3,
    "projects": {
      "proj-123": {"code": 10, "text": 5},
      "proj-456": {"code": 20, "text": 10}
    }
  },
  "timestamp": "2026-01-14T12:00:00Z"
}
```

## Integration with Main Tool

### Process Project and View Metrics

```python
from sandbox.app.main import startup, process_project, get_metrics

# Initialize
startup()

# Process project
process_project(
    project_id="demo-project",
    vendor_id="anthropic",
    local_path=Path("/files"),
    snapshot_type="code"
)

# Get metrics programmatically
metrics = get_metrics()
print(f"Total snapshots: {metrics['snapshot_metrics']['total']}")
```

### Concurrent Dashboard

Run dashboard in separate terminal while processing:

```bash
# Terminal 1: Dashboard
python -m sandbox.app.dashboard

# Terminal 2: Process projects
python
>>> from sandbox.app.main import startup, process_project
>>> startup()
>>> process_project("proj-1", "anthropic", local_path=...)

# View metrics in browser at http://localhost:5000
```

## Docker Deployment

### Update docker-compose.yml

```yaml
services:
  dashboard:
    build:
      context: .
      dockerfile: docker/Dockerfile
    ports:
      - "5000:5000"
    depends_on:
      - postgres
    environment:
      SANDBOX_POSTGRES_DSN: postgresql+psycopg://sandbox:sandbox@postgres:5432/sandbox
    command: python -m sandbox.app.dashboard
```

### Run
```bash
docker-compose up -d
# Dashboard at http://localhost:5000
```

## Production Considerations (V2)

For production deployment, consider:

1. **Authentication** - Add login/auth layer
2. **WSGI Server** - Use Gunicorn instead of Flask dev server
3. **Caching** - Cache metrics for N seconds
4. **Advanced Metrics:**
   - Vendor usage breakdown
   - Field coverage percentages
   - Duplicate attempt rates
   - Processing time averages

## Troubleshooting

### Dashboard won't start
```bash
# Check dependencies
pip install Flask

# Check database connection
python -c "from sandbox.app.storage.db import get_engine; get_engine()"
```

### No metrics showing
```bash
# Verify snapshots exist in DB
psql -U sandbox -d sandbox -c "SELECT COUNT(*) FROM snapshot_notebooks;"

# Check logs
python -m sandbox.app.dashboard
# Look for "Metrics retrieved" log messages
```

### Port 5000 already in use
```python
# Change port in dashboard.py
app.run(host='0.0.0.0', port=8080, debug=True)
```

## Example Usage Flow

```bash
# 1. Start database
docker-compose up -d postgres

# 2. Start dashboard
python -m sandbox.app.dashboard
# Opens on http://localhost:5000

# 3. In another terminal, process projects
python << EOF
from pathlib import Path
from sandbox.app.main import startup, process_project

startup()

process_project("test-proj", "anthropic", local_path=Path("/test/files"), snapshot_type="code")
EOF

# 4. View metrics in browser
# Refresh to see new snapshots
```

## Next Steps for V2

- Add vendor usage tracking
- Export metrics to JSON/CSV
- Historical trending
- Real-time WebSocket updates
- Field coverage visualization
