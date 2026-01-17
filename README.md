#SNAP
###Sandbox Notebook Abide Persistence Tool

> Persistent memory backend service for LLM applications. Scans code repositories and files, extracts structured data into snapshot notebooks for RAG and multi-model access.

---

## Overview

This backend service ingests files and repositories, parses content, creates field-based snapshots, and assembles project notebooks. Designed for external LLM applications requiring persistent memory across sessions and vendors.

---

## Features

| Feature | Description |
|---------|-------------|
| **Multi-Source Ingestion** | Local files and GitHub repositories |
| **Persistent Memory** | Project notebooks stored in PostgreSQL |
| **Multi-LLM Compatible** | Vendor-agnostic snapshot format |
| **Idempotent Processing** | Retry-safe file parsing |
| **Lightweight Pointers** | Manifest files for efficient multi-model access |
| **Swappable Parsers** | Modular parser architecture |
| **Metrics Dashboard** | Real-time visualization of snapshots and projects |
| **Vendor Tracking** | Logs which LLM vendor accesses each project |
| **Security Logging** | Tracks duplicate attempts and idempotency events |

---

## Quick Start

### Option 1: Automated Setup (Recommended)

```bash
# Run setup script
chmod +x setup.sh && ./setup.sh

# Configure environment
cp .env.template .env
vim .env

# Start database and dashboard
docker-compose up -d postgres
python -m app.dashboard
```

> Access the dashboard at `http://localhost:5000`

### Option 2: Docker (Full Stack)

```bash
docker-compose up -d
```

> Access the dashboard at `http://localhost:5000`

### Option 3: Manual Setup

```bash
# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.template .env
# Edit .env with your settings

# Initialize database
createdb sandbox
python -c "from app.main import startup; startup()"

# Start dashboard
python -m app.dashboard
```

---

## Integration Example

```python
from pathlib import Path
from app.main import startup, process_project, get_project_notebook

# Initialize service
startup()

# Process a project
manifest = process_project(
    project_id="internal-knowledge-base",
    vendor_id="anthropic",
    local_path=Path("/path/to/files"),
    snapshot_type="code"
)

# Retrieve assembled notebook
notebook = get_project_notebook(
    project_id="internal-knowledge-base",
    vendor_id="anthropic",
    snapshot_type="code"
)
```

---

## Metrics Dashboard

View real-time metrics and project statistics:

```bash
python -m app.dashboard
```

> Access at `http://localhost:5000`

**Dashboard Metrics:**

- Total snapshots created
- Active projects
- Snapshots by type (code/text)
- Per-project breakdown
- Recent activity (24h)

See [`DASHBOARD_GUIDE.md`](DASHBOARD_GUIDE.md) for details.

---

## Project Structure

```
sandbox/
├── app/
│   ├── main.py                    # Orchestration layer
│   ├── dashboard.py               # Metrics visualization
│   ├── config/settings.py         # Configuration
│   ├── ingest/                    # File/repo ingestion
│   ├── parsers/                   # PDF, text, CSV, code parsers
│   ├── extraction/                # Field mapping, snapshot building
│   ├── storage/                   # Database persistence
│   ├── security/                  # Network policy, limits
│   └── logging/                   # Structured logging
├── schemas/
│   ├── master_notebook.yaml       # Master template
│   ├── code_notebook_schema.json  # Code snapshot template
│   └── text_notebook_snapshot.json # Text snapshot template
├── data/
│   └── projects/{project_id}/     # Per-project data
│       ├── uploads/               # User uploaded files
│       ├── repos/                 # Cloned repositories
│       └── project_manifest.json  # Lightweight pointer
├── .env.template                  # Environment config template
├── .env.example                   # Example configurations
├── setup.sh                       # Quick setup script
└── docker-compose.yml             # Docker orchestration
```

---

## Architecture

### Pipeline Flow

```
Files → Ingest → Parse → Field Map → Snapshot → DB
                                                 ↓
                                 Project Notebook (assembled on-demand)
```

### Key Components

| Component | Purpose |
|-----------|---------|
| **Parsers** | Extract content from files |
| **Field Mapper** | Maps content to field_ids |
| **Snapshot Builder** | Creates and assembles notebooks |
| **Snapshot Repo** | PostgreSQL persistence |

---

## Configuration

Create a `.env` file from the template:

```bash
cp .env.template .env
```

### Required Variables

| Variable | Description |
|----------|-------------|
| `SANDBOX_POSTGRES_DSN` | PostgreSQL connection string |
| `SANDBOX_LOG_LEVEL` | Logging level (INFO, DEBUG, etc.) |
| `SANDBOX_LOG_JSON` | Enable JSON log format (true/false) |
| `SANDBOX_ENVIRONMENT` | Runtime environment (dev, prod) |

### Optional Variables

| Variable | Description |
|----------|-------------|
| `SANDBOX_DATA_DIR` | Custom data directory path |
| `SANDBOX_SCHEMAS_DIR` | Custom schemas directory path |
| `SANDBOX_GIT_CLONE_TIMEOUT_SECONDS` | Git clone timeout |

See [`.env.template`](.env.template) for all options.

> **Docker:** Environment variables are configured in `docker-compose.yml`.

---

## API Reference

| Function | Description |
|----------|-------------|
| `startup()` | Initializes service, loads schemas, ensures database tables exist |
| `process_project(...)` | Scans files, creates snapshots, returns lightweight manifest |
| `get_project_notebook(...)` | Retrieves assembled project notebook for RAG pipelines |
| `get_project_manifest(project_id)` | Returns lightweight project manifest from disk |
| `get_metrics()` | Returns snapshot and project metrics |
| `delete_project(project_id)` | Deletes all snapshots and project data |

### Function Signatures

```python
startup() -> None

process_project(
    project_id: str,
    vendor_id: str,
    repo_url: str | None = None,
    local_path: Path | None = None,
    snapshot_type: str = "code"
) -> Manifest

get_project_notebook(
    project_id: str,
    vendor_id: str,
    snapshot_type: str
) -> Notebook
```

---

## Multi-LLM Access

```
1. Process project  →  Generate manifest
2. Embed notebook   →  Vector database
3. Query vectors    →  Multiple LLM vendors
4. No reassembly or reprocessing required
```

---

## Development

### Testing

```bash
pytest
```

### Adding Parsers

1. Create `parsers/new_parser.py`
2. Implement `parse_new(path) -> ParseResult`
3. Update routing in `main.py`

> No other changes required.

---

## Requirements

| Dependency | Version |
|------------|---------|
| Python | 3.11+ |
| PostgreSQL | 14+ |
| Git | Latest |
| Flask | 3.0+ (dashboard only) |

See [`INSTALL.md`](INSTALL.md) for detailed setup instructions.

---

## Documentation

| Document | Description |
|----------|-------------|
| [`INSTALL.md`](INSTALL.md) | Installation and setup |
| [`DASHBOARD_GUIDE.md`](DASHBOARD_GUIDE.md) | Metrics dashboard usage |
| [`LOGGING_UPDATES.md`](LOGGING_UPDATES.md) | Logging and vendor tracking |
| [`file_tree.txt`](file_tree.txt) | Complete project structure |
| [`.env.template`](.env.template) | Environment configuration reference |

---

## License

Open Source — Enterprise licensing available
