"""Test the sandbox app with local files"""
from pathlib import Path

# Test 1: Verify settings load correctly
print("=" * 50)
print("TEST 1: Settings")
print("=" * 50)
from app.config.settings import get_settings

settings = get_settings()
print(f"Environment: {settings.environment}")
print(f"Postgres DSN: {settings.postgres_dsn}")
print(f"Schema path: {settings.notebook_schema_path}")
print(f"Schema exists: {settings.notebook_schema_path.exists()}")

# Test 2: Check test files exist
print("\n" + "=" * 50)
print("TEST 2: Test Files")
print("=" * 50)
local_path = Path("c:/Users/yxyel/sandbox/data/test_upload")
print(f"Test directory: {local_path}")
print(f"Directory exists: {local_path.exists()}")
if local_path.exists():
    files = list(local_path.iterdir())
    print(f"Files found: {[f.name for f in files]}")

# Test 3: Initialize app (requires DB)
print("\n" + "=" * 50)
print("TEST 3: App Startup (requires PostgreSQL)")
print("=" * 50)
try:
    from app.main import startup, process_project
    print("Starting up...")
    startup()
    print("Startup complete!")

    # Test 4: Process the local directory
    print("\n" + "=" * 50)
    print("TEST 4: Process Local Directory")
    print("=" * 50)
    manifest = process_project(
        project_id="test-local-001",
        vendor_id="local-test",
        local_path=local_path,
        snapshot_type="code",
    )
    print("Success! Manifest:")
    import json
    print(json.dumps(manifest, indent=2))

except Exception as e:
    print(f"Error: {e}")
    print("\nMake sure PostgreSQL is running: docker-compose up -d postgres")
