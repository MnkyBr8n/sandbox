# sandbox/app/main.py
"""
Purpose: Main orchestration for sandbox snapshot notebook tool.
Loads master schema at startup, orchestrates ingest → parse → snapshot creation.
Saves lightweight manifest pointer to DB snapshots.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime
import yaml
import json

from app.config.settings import get_settings
from app.logging.logger import get_logger
from app.ingest.local_loader import ingest_local_directory
from app.ingest.github_cloner import clone_github_repo
from app.ingest.file_router import route_file
from app.parsers.pdf_parser import parse_pdf
from app.parsers.text_parser import parse_text_like
from app.parsers.csv_parser import parse_csv
from app.parsers.code_parser import parse_code
from app.extraction.field_mapper import FieldMapper
from app.extraction.snapshot_builder import SnapshotBuilder
from app.storage.snapshot_repo import SnapshotRepository
from app.storage.db import get_engine
from sqlalchemy import text


class SandboxToolError(Exception):
    pass


# Global state (loaded once at startup)
_master_schema: Optional[Dict[str, Any]] = None
_snapshot_builder: Optional[SnapshotBuilder] = None
_logger = get_logger("main")


def startup() -> None:
    """
    Initialize sandbox tool: load master schema, ensure DB tables.
    Call once when tool starts.
    """
    global _master_schema, _snapshot_builder
    
    if _master_schema is not None:
        _logger.info("Startup already completed")
        return
    
    _logger.info("Starting sandbox tool initialization")
    
    # Load master notebook schema
    settings = get_settings()
    schema_path = settings.notebook_schema_path
    
    if not schema_path.exists():
        raise SandboxToolError(f"Master schema not found: {schema_path}")
    
    with open(schema_path) as f:
        _master_schema = yaml.safe_load(f)
    
    _logger.info(f"Loaded master schema from {schema_path}")
    
    # Initialize SnapshotBuilder with master schema
    _snapshot_builder = SnapshotBuilder(_master_schema)
    
    # Ensure DB tables exist
    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))  # Test connection
    
    _logger.info("Sandbox tool initialization complete")


def process_project(
    project_id: str,
    vendor_id: str,
    repo_url: Optional[str] = None,
    local_path: Optional[Path] = None,
    snapshot_type: str = "code",
) -> Dict[str, Any]:
    """
    Process project: ingest files, parse, create snapshots, save manifest.
    
    Args:
        project_id: unique project identifier
        vendor_id: LLM vendor identifier ("anthropic", "openai", etc.)
        repo_url: GitHub repo URL to clone (can be combined with local_path)
        local_path: local directory to ingest (can be combined with repo_url)
        snapshot_type: "code" or "text"
    
    Returns:
        Lightweight project manifest (pointer to DB snapshots)
    """
    if _snapshot_builder is None:
        raise SandboxToolError("Tool not initialized. Call startup() first.")
    
    if not repo_url and not local_path:
        raise SandboxToolError("Must provide either repo_url or local_path")
    
    # Log vendor call
    _logger.info("Vendor call", extra={
        "vendor_id": vendor_id,
        "project_id": project_id,
        "action": "process_project",
        "snapshot_type": snapshot_type,
        "sources": {
            "repo_url": repo_url is not None,
            "local_path": local_path is not None
        }
    })
    
    _logger.info(f"Processing project project_id={project_id} type={snapshot_type}")
    
    # Step 0: Create project folder structure
    settings = get_settings()
    project_dir = settings.data_dir / "projects" / project_id
    uploads_dir = project_dir / "uploads"
    repos_dir = project_dir / "repos"
    
    project_dir.mkdir(parents=True, exist_ok=True)
    uploads_dir.mkdir(exist_ok=True)
    repos_dir.mkdir(exist_ok=True)
    
    _logger.info(f"Project directory: {project_dir}")
    
    # Step 1: Ingest files (support both sources)
    files = []
    
    if repo_url:
        _logger.info(f"Cloning repo: {repo_url}")
        cloned_files = clone_github_repo(repo_remote=repo_url, project_id=project_id)
        files.extend(cloned_files)
    
    if local_path:
        _logger.info(f"Ingesting local directory: {local_path}")
        local_files = ingest_local_directory(source_dir=local_path, project_id=project_id)
        files.extend(local_files)
    
    if not files:
        raise SandboxToolError("No files ingested from provided sources")
    
    _logger.info(f"Ingested {len(files)} files")
    
    # Step 2: Get field registry for snapshot_type
    field_registry = _master_schema.get("field_id_registry", {}).get(snapshot_type, [])
    allowed_field_ids = [f["field_id"] for f in field_registry]
    
    field_mapper = FieldMapper(allowed_field_ids=allowed_field_ids)
    
    # Step 3: Parse each file and create snapshots
    snapshots_created = 0
    processing_start = datetime.utcnow()
    
    for file_path in files:
        try:
            # Route file to appropriate parser
            file_type = route_file(file_path)
            
            if file_type == "skip":
                _logger.debug(f"Skipping file: {file_path}")
                continue
            
            # Parse file
            parsed_records = _parse_file(file_path, file_type)
            
            if not parsed_records:
                _logger.debug(f"No records extracted from {file_path}")
                continue
            
            # Map to field_ids
            field_map_result = field_mapper.map_fields(
                parsed_records=parsed_records,
                source_id=str(file_path)
            )
            
            # Create snapshot
            _snapshot_builder.create_snapshot(
                project_id=project_id,
                snapshot_type=snapshot_type,
                source_file=str(file_path),
                field_map_result=field_map_result,
            )
            
            snapshots_created += 1
            
        except Exception as exc:
            _logger.error(f"Failed to process file {file_path}: {exc}")
            continue
    
    _logger.info(f"Created {snapshots_created} snapshots for project {project_id}")
    
    # Step 4: Get coverage stats from assembled notebook
    notebook = _snapshot_builder.assemble_project_notebook(
        project_id=project_id,
        snapshot_type=snapshot_type,
    )
    
    coverage = notebook.get("coverage", {})
    filled_count = len(coverage.get("filled_field_ids", []))
    missing_count = len(coverage.get("missing_field_ids", []))
    
    # Step 5: Create lightweight manifest
    manifest = {
        "project_id": project_id,
        "snapshot_type": snapshot_type,
        "created_at": processing_start.isoformat() + "Z",
        "last_updated": datetime.utcnow().isoformat() + "Z",
        "stats": {
            "snapshot_count": snapshots_created,
            "files_processed": len(files),
            "filled_fields": filled_count,
            "missing_fields": missing_count
        },
        "db_location": {
            "table": "snapshot_notebooks",
            "project_id": project_id
        },
        "access": {
            "get_notebook": f"get_project_notebook(project_id='{project_id}', snapshot_type='{snapshot_type}')",
            "query_snapshots": f"SELECT * FROM snapshot_notebooks WHERE project_id='{project_id}' ORDER BY created_at ASC"
        }
    }
    
    # Step 6: Save manifest to project directory
    manifest_path = project_dir / "project_manifest.json"
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)
    
    _logger.info(f"Saved project manifest to {manifest_path}")
    _logger.info(f"Project processing complete: {filled_count} filled, {missing_count} missing")
    
    return manifest


def _parse_file(file_path: Path, file_type: str) -> List[Dict[str, Any]]:
    """
    Parse file using appropriate parser.

    Args:
        file_path: Path to file
        file_type: File extension without dot (e.g., "py", "pdf", "json")

    Returns:
        List of records with field_id and value
    """
    # Map extensions to parser categories
    code_extensions = {"py", "js", "ts", "go", "rs", "java", "c", "cpp", "rb", "cs"}
    text_extensions = {"txt", "md", "html", "htm", "json", "yaml", "yml"}

    if file_type == "pdf":
        result = parse_pdf(file_path)
        return [{"field_id": "doc.title", "value": file_path.stem}]

    elif file_type in text_extensions:
        result = parse_text_like(file_path)
        return [{"field_id": "doc.title", "value": file_path.stem}]

    elif file_type == "csv":
        result = parse_csv(file_path)
        return []

    elif file_type in code_extensions:
        result = parse_code(file_path)
        return [
            {"field_id": "repo.primary_language", "value": result.language},
            {"field_id": "repo.modules", "value": file_path.stem}
        ]

    else:
        return []


def delete_project(project_id: str) -> None:
    """
    Delete all snapshots for project from DB and remove project directory.
    
    Args:
        project_id: unique project identifier
    """
    if _snapshot_builder is None:
        raise SandboxToolError("Tool not initialized. Call startup() first.")
    
    _logger.info(f"Deleting project project_id={project_id}")
    
    # Get all snapshots
    repo = SnapshotRepository()
    snapshots = repo.get_by_project(project_id)
    
    # Delete from DB
    from app.storage.db import db_session
    from sqlalchemy import text
    
    with db_session() as session:
        session.execute(
            text("DELETE FROM snapshot_notebooks WHERE project_id = :pid"),
            {"pid": project_id}
        )
    
    # Delete project directory
    settings = get_settings()
    project_dir = settings.data_dir / "projects" / project_id
    
    if project_dir.exists():
        import shutil
        shutil.rmtree(project_dir)
        _logger.info(f"Removed project directory: {project_dir}")
    
    _logger.info(f"Deleted {len(snapshots)} snapshots for project {project_id}")


def get_project_notebook(project_id: str, vendor_id: str, snapshot_type: str = "code") -> Dict[str, Any]:
    """
    Retrieve assembled project notebook (on-demand from DB snapshots).
    
    Args:
        project_id: unique project identifier
        vendor_id: LLM vendor identifier ("anthropic", "openai", etc.)
        snapshot_type: "code" or "text"
    
    Returns:
        Assembled project notebook (RAG-ready)
    """
    if _snapshot_builder is None:
        raise SandboxToolError("Tool not initialized. Call startup() first.")
    
    # Log vendor retrieval
    _logger.info("Vendor call", extra={
        "vendor_id": vendor_id,
        "project_id": project_id,
        "action": "get_project_notebook",
        "snapshot_type": snapshot_type
    })
    
    return _snapshot_builder.assemble_project_notebook(
        project_id=project_id,
        snapshot_type=snapshot_type,
    )


def get_project_manifest(project_id: str) -> Dict[str, Any]:
    """
    Retrieve lightweight project manifest from file.
    
    Args:
        project_id: unique project identifier
    
    Returns:
        Project manifest with stats and access pointers
    """
    settings = get_settings()
    manifest_path = settings.data_dir / "projects" / project_id / "project_manifest.json"
    
    if not manifest_path.exists():
        raise SandboxToolError(f"Project manifest not found for project_id={project_id}")
    
    with open(manifest_path) as f:
        return json.load(f)


def get_metrics() -> Dict[str, Any]:
    """
    Get current tool metrics for dashboard visualization.
    
    Returns:
        Dict with snapshot counts, project stats, field coverage
    """
    from app.storage.db import db_session
    from sqlalchemy import text
    
    with db_session() as session:
        # Total snapshots
        result = session.execute(text("SELECT COUNT(*) FROM snapshot_notebooks"))
        total_snapshots = result.scalar()
        
        # Snapshots by type
        result = session.execute(text("""
            SELECT snapshot_type, COUNT(*) as count
            FROM snapshot_notebooks
            GROUP BY snapshot_type
        """))
        snapshots_by_type = {row[0]: row[1] for row in result.fetchall()}
        
        # Total projects
        result = session.execute(text("""
            SELECT COUNT(DISTINCT project_id) FROM snapshot_notebooks
        """))
        total_projects = result.scalar()
        
        # Recent snapshots (last 24 hours)
        result = session.execute(text("""
            SELECT COUNT(*) FROM snapshot_notebooks
            WHERE created_at > NOW() - INTERVAL '24 hours'
        """))
        recent_snapshots = result.scalar()
        
        # Projects list with snapshot counts
        result = session.execute(text("""
            SELECT project_id, snapshot_type, COUNT(*) as count
            FROM snapshot_notebooks
            GROUP BY project_id, snapshot_type
            ORDER BY project_id
        """))
        projects = {}
        for row in result.fetchall():
            project_id = row[0]
            if project_id not in projects:
                projects[project_id] = {"code": 0, "text": 0}
            projects[project_id][row[1]] = row[2]
        
    metrics = {
        "snapshot_metrics": {
            "total": total_snapshots,
            "by_type": snapshots_by_type,
            "recent_24h": recent_snapshots
        },
        "project_metrics": {
            "total": total_projects,
            "projects": projects
        },
        "timestamp": datetime.utcnow().isoformat() + "Z"
    }
    
    _logger.info("Metrics retrieved", extra={"total_snapshots": total_snapshots, "total_projects": total_projects})
    
    return metrics
