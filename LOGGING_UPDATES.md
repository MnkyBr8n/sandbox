# Logging Updates Summary

## Files Updated

1. **logger.py** - Fixed caching bug
2. **main.py** - Added vendor call tracking
3. **snapshot_repo.py** - Added security logging for duplicates
4. **snapshot_builder.py** - Added snapshot accounting

---

## Changes Detail

### 1. logger.py
**Fix:** Removed global `_LOGGER` caching that caused all loggers to have same name.

**Before:**
```python
_LOGGER = None
if _LOGGER is not None:
    return _LOGGER  # Always returns first logger
```

**After:**
```python
# No global caching - each component gets correct named logger
logger = logging.getLogger(name)
```

**Result:** Logs now show correct component names (main, snapshot_repo, parsers.pdf, etc.)

---

### 2. main.py
**Added:** Vendor call tracking with vendor_id parameter.

**New Parameters:**
- `process_project(project_id, vendor_id, ...)`
- `get_project_notebook(project_id, vendor_id, ...)`

**Logs Generated:**
```json
{
  "level": "INFO",
  "name": "main",
  "msg": "Vendor call",
  "vendor_id": "anthropic",
  "project_id": "proj-123",
  "action": "process_project",
  "snapshot_type": "code"
}
```

**Tracks:**
- Which vendor called the tool
- What action was performed
- Project being accessed

---

### 3. snapshot_repo.py
**Added:** Security logging for duplicate snapshot attempts (idempotency hits).

**Logs Generated:**
```json
{
  "level": "WARNING",
  "name": "storage.snapshot_repo",
  "msg": "Duplicate snapshot attempt",
  "project_id": "proj-123",
  "source_file": "/repo/main.py",
  "existing_snapshot_id": "uuid-here",
  "security_event": "idempotency_skip",
  "action": "merge_fields"
}
```

**Tracks:**
- When same file is processed multiple times
- Which snapshot already exists
- Security event classification

---

### 4. snapshot_builder.py
**Added:** Snapshot accounting logs showing created vs. final counts.

**Logs Generated:**
```json
{
  "level": "INFO",
  "name": "extraction.snapshot_builder",
  "msg": "Snapshot accounting",
  "project_id": "proj-123",
  "snapshot_type": "code",
  "snapshots_assembled": 10,
  "snapshots_total_project": 10,
  "filled_fields": 5,
  "missing_fields": 2
}
```

**Tracks:**
- How many snapshots assembled for this type
- Total snapshots in project (all types)
- Field coverage (filled vs. missing)

---

## Usage Examples

### Single Vendor
```python
from sandbox.app.main import startup, process_project

startup()
manifest = process_project(
    project_id="proj-123",
    vendor_id="anthropic",
    local_path=Path("/files"),
    snapshot_type="code"
)

# Logs show:
# - "Vendor call" with vendor_id="anthropic"
# - "Created snapshot" for each file
# - "Snapshot accounting" with final counts
```

### Multiple Vendors (Same Project)
```python
# Vendor 1 (Anthropic) processes project
manifest = process_project("proj-123", "anthropic", local_path=...)
# Logs: vendor_id="anthropic", action="process_project"

# Vendor 2 (OpenAI) retrieves notebook
notebook = get_project_notebook("proj-123", "openai", "code")
# Logs: vendor_id="openai", action="get_project_notebook"
```

### Security Event (Duplicate File)
```python
# File processed twice (retry or error)
process_project("proj-123", "anthropic", local_path=...)  # First time
process_project("proj-123", "anthropic", local_path=...)  # Retry

# Logs show:
# - First: "Created snapshot"
# - Second: "Duplicate snapshot attempt" (WARNING level)
#   - existing_snapshot_id provided
#   - security_event="idempotency_skip"
```

---

## Log Output Format

**JSON mode** (SANDBOX_LOG_JSON=true):
```json
{"ts":"2026-01-14T12:00:00","level":"INFO","name":"main","msg":"Vendor call","vendor_id":"anthropic","project_id":"proj-123"}
```

**Human-readable mode** (SANDBOX_LOG_JSON=false):
```
2026-01-14 12:00:00 INFO main Vendor call
```

---

## What Gets Logged

✅ **Now Logged:**
- Vendor calls (who, what, when)
- Duplicate snapshot attempts (security)
- Snapshot creation with IDs
- Snapshot accounting (created vs. final)
- Component-specific names (correct logger names)

✅ **Previously Logged:**
- Startup events
- File processing counts
- Error conditions

❌ **Still Not Logged:**
- User/session IDs (not in scope)
- Database query performance
- Individual field extractions
- Parser-level details
