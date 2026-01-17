"""Test processing a GitHub repository"""
from app.main import startup, process_project

# Initialize
print("Starting up...")
startup()
print("Ready!\n")

# Your repo
repo_url = "https://github.com/MnkyBr8n/mom"

project_id = repo_url.split("/")[-1]  # Use repo name as project ID

print(f"\nProcessing: {repo_url}")
print(f"Project ID: {project_id}")

try:
    manifest = process_project(
        project_id=project_id,
        vendor_id="local-test",
        repo_url=repo_url,
        snapshot_type="text",  # Use text for HTML/MD files
    )

    print("\n" + "=" * 50)
    print("SUCCESS!")
    print("=" * 50)
    import json
    print(json.dumps(manifest, indent=2))

except Exception as e:
    print(f"\nError: {e}")
    import traceback
    traceback.print_exc()
