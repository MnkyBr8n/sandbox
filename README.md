# SNAP
Sandbox Notebook Abide Persistence Tool

> Multi-snapshot RAG notebook system. Categorizes code/documents into 12 snapshot types for targeted retrieval.

---

## V2 Architecture

**12 Categorized Snapshots per File:**
- Code: file_metadata, imports, exports, functions, classes, connections, repo_metadata
- Security/Quality: security, quality
- Documents: doc_metadata, doc_content, doc_analysis

**Multi-Parser Pipeline:**
- Code → tree_sitter + semgrep
- Documents → text_extractor
- CSV → csv_parser

**Per-Project Isolation:**
- `staging/{project_id}/` → `repos/{project_id}/` → snapshots
- No global notebook
- Delete project = delete all

---

## Quick Start

```bash
# Install semgrep
pip install semgrep

# Setup
chmod +x setup.sh && ./setup.sh
cp .env.template .env

# Start
docker-compose up -d postgres
python -m app.dashboard
```

Dashboard: `http://localhost:5000`

---

## Integration

```python
from app.main import startup, process_project
from app.ingest.local_loader import get_project_staging_path

startup()

# Agent uploads to staging
staging = get_project_staging_path("project_a")
# → staging/project_a/

# Process with multi-parser pipeline
manifest = process_project(
    project_id="project_a",
    vendor_id="anthropic",
    local_path=staging
)

# Query specific snapshot types
from app.extraction.snapshot_builder import SnapshotBuilder
builder = SnapshotBuilder(master_schema)

imports = builder.get_project_snapshots_by_type("project_a", "imports")
security = builder.get_project_snapshots_by_type("project_a", "security")
```

---

## Dashboard

```bash
python -m app.dashboard
```

**Metrics:**
- Files: attempted/processed/failed
- Snapshots: attempted/created/failed/rejected
- File categories: normal/large/potential_god/rejected
- Parser usage
- Snapshot type distribution

**Log Export:** Click "Export Logs" → `snapshot_logs_{timestamp}.json`

---

## Pipeline Flow

```
staging/{project_id}/
    ↓
file_router (multi-parser)
    ↓
tree_sitter + semgrep (code)
text_extractor (docs)
    ↓
field_mapper (categorize 12 types)
    ↓
snapshot_builder (create with IDs)
    ↓
snapshot_repo (persist)
    ↓
Query: WHERE project_id={project_id}
```

---

## File Categorization

| Category | LOC | Action |
|----------|-----|--------|
| normal | < 1,500 | Process |
| large | 1,500-3,999 | Warn |
| potential_god | 4,000-4,999 | Log |
| rejected | ≥ 5,000 | Error |

---

## RAG Queries

```sql
-- All imports
SELECT * FROM snapshot_notebooks WHERE snapshot_type = 'imports';

-- Security issues
SELECT * FROM snapshot_notebooks WHERE snapshot_type = 'security';

-- File analysis
SELECT * FROM snapshot_notebooks WHERE source_file = '/repo/utils.py';
```

---

## Configuration

```bash
cp .env.template .env
```

| Variable | Default |
|----------|---------|
| SANDBOX_POSTGRES_DSN | localhost |
| SANDBOX_PARSER_LIMITS_SOFT_CAP_LOC | 1500 |
| SANDBOX_PARSER_LIMITS_HARD_CAP_LOC | 5000 |
| SANDBOX_GIT_CLONE_TIMEOUT_SECONDS | 600 |

---

## Requirements

| Dependency | Version |
|------------|---------|
| Python | 3.11+ |
| PostgreSQL | 14+ |
| tree-sitter | 0.20+ |
| semgrep | 1.50+ |
| PyPDF2 | 3.0+ |
| python-docx | 0.8+ |

---

## License

Open Source
