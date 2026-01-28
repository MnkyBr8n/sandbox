# sandbox/app/main.py
"""
Main orchestration for sandbox snapshot notebook tool.

Multi-parser architecture:
- Routes code files to tree_sitter + semgrep  
- Routes text files to text_extractor
- Routes CSV files to csv_parser
- Creates 12 categorized snapshots per file
- Tracks accepted/failed/rejected snapshots
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime
import yaml
import json
import time
import threading

from app.config.settings import get_settings
from app.logging.logger import (
    get_logger,
    log_file_parsed,
    log_repo_complete,
    log_file_categorization
)
from app.ingest.local_loader import ingest_local_directory
from app.ingest.github_cloner import clone_github_repo
from app.ingest.file_router import route_files, FileRoute
from app.parsers.tree_sitter_parser import parse_code_tree_sitter
from app.parsers.semgrep_parser import parse_code_semgrep
from app.parsers.text_extractor import extract_text
from app.parsers.csv_parser import parse_csv_file
from app.extraction.field_mapper import FieldMapper
from app.extraction.snapshot_builder import SnapshotBuilder
from app.storage.snapshot_repo import SnapshotRepository
from app.storage.db import get_engine


class SandboxToolError(Exception):
    pass


_master_schema: Optional[Dict[str, Any]] = None
_field_mapper: Optional[FieldMapper] = None
_snapshot_builder: Optional[SnapshotBuilder] = None
_startup_lock = threading.Lock()
_logger = get_logger("main")


def startup() -> None:
    """Initialize sandbox tool: load schema, validate parsers, ensure DB tables."""
    global _master_schema, _field_mapper, _snapshot_builder

    # Fast path - already initialized (no lock needed for read)
    if _master_schema is not None:
        return

    # Thread-safe initialization
    with _startup_lock:
        # Double-check after acquiring lock
        if _master_schema is not None:
            _logger.info("Startup already completed")
            return

        _logger.info("Starting sandbox tool initialization")

        settings = get_settings()
        schema_path = settings.notebook_schema_path

        if not schema_path.exists():
            raise SandboxToolError(f"Master schema not found: {schema_path}")

        with open(schema_path) as f:
            _master_schema = yaml.safe_load(f)

        _logger.info(f"Loaded master schema from {schema_path}")

        _field_mapper = FieldMapper(master_schema=_master_schema)
        _snapshot_builder = SnapshotBuilder(_master_schema)

        from app.parsers.semgrep_parser import validate_semgrep_installation
        semgrep_status = validate_semgrep_installation()
        if not semgrep_status["installed"]:
            _logger.warning("Semgrep CLI not installed - security scanning disabled")

        from sqlalchemy import text
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))

        _logger.info("Sandbox tool initialization complete")


def process_project(
    project_id: str,
    vendor_id: str,
    repo_url: Optional[str] = None,
    local_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Process project: ingest, parse, create snapshots."""
    if _snapshot_builder is None or _field_mapper is None:
        raise SandboxToolError("Tool not initialized. Call startup() first.")
    
    if not repo_url and not local_path:
        raise SandboxToolError("Must provide either repo_url or local_path")
    
    start_time = time.time()
    
    _logger.info("Vendor call", extra={
        "vendor_id": vendor_id,
        "project_id": project_id,
        "action": "process_project"
    })
    
    _logger.info(f"Processing project project_id={project_id}")
    
    settings = get_settings()
    project_dir = settings.data_dir / "projects" / project_id
    project_dir.mkdir(parents=True, exist_ok=True)
    
    files = []
    
    if repo_url:
        _logger.info(f"Cloning repo: {repo_url}")
        files.extend(clone_github_repo(repo_remote=repo_url, project_id=project_id))
    
    if local_path:
        _logger.info(f"Ingesting local: {local_path}")
        files.extend(ingest_local_directory(source_dir=local_path, project_id=project_id))
    
    if not files:
        raise SandboxToolError("No files ingested")
    
    _logger.info(f"Ingested {len(files)} files")
    
    routes = route_files(files)
    
    stats = {
        "files_attempted": len(routes),
        "files_processed": 0,
        "files_failed": 0,
        "snapshots_attempted": 0,
        "snapshots_created": 0,
        "snapshots_failed": 0,
        "snapshots_rejected": 0,
        "snapshot_types": {},
        "parsers_used": {},
        "file_categorization": {"normal": 0, "large": 0, "potential_god": 0, "rejected": 0}
    }
    
    for route in routes:
        try:
            file_start = time.time()
            
            file_size = _get_file_size(route.path, route.snapshot_type)
            file_tag = _categorize_file(route.path, file_size)
            
            stats["file_categorization"][file_tag] += 1

            if file_tag == "rejected":
                log_file_categorization(_logger, str(route.path), file_size, "rejected", "exceeds 5000 LOC hard cap")
                stats["files_failed"] += 1
                stats["snapshots_rejected"] += 1
                continue
            
            if file_tag in ("large", "potential_god"):
                reason = {
                    "large": "exceeds 1500 LOC soft cap",
                    "potential_god": "exceeds 4000 LOC"
                }[file_tag]
                log_file_categorization(_logger, str(route.path), file_size, file_tag, reason)
            
            categorized_fields = _parse_file_multi_parser(route)
            
            if not categorized_fields:
                stats["files_failed"] += 1
                continue
            
            snapshots = _snapshot_builder.create_snapshots(
                project_id=project_id,
                file_path=str(route.path),
                categorized_fields=categorized_fields,
                parsers_used=route.parsers
            )
            
            stats["snapshots_attempted"] += len(categorized_fields)
            stats["snapshots_created"] += len(snapshots)
            
            for snapshot in snapshots:
                stype = snapshot["snapshot_type"]
                stats["snapshot_types"][stype] = stats["snapshot_types"].get(stype, 0) + 1
            
            for parser in route.parsers:
                stats["parsers_used"][parser] = stats["parsers_used"].get(parser, 0) + 1
            
            file_duration = (time.time() - file_start) * 1000
            
            log_file_parsed(
                _logger,
                str(route.path),
                file_tag,
                file_size,
                route.language,
                project_id,
                file_duration,
                len(snapshots),
                [s["snapshot_type"] for s in snapshots],
                [s["snapshot_id"] for s in snapshots],
                route.parsers
            )
            
            stats["files_processed"] += 1
            
        except Exception as exc:
            _logger.error(f"Failed to process {route.path}: {exc}")
            stats["files_failed"] += 1
            stats["snapshots_failed"] += 1
    
    total_duration = (time.time() - start_time) * 1000
    
    log_repo_complete(
        _logger,
        project_id,
        stats["files_processed"],
        stats["files_attempted"],
        stats["snapshots_created"],
        stats["snapshots_attempted"],
        stats["snapshots_failed"],
        stats["snapshots_rejected"],
        stats["snapshot_types"],
        stats["parsers_used"],
        total_duration
    )
    
    manifest = {
        "project_id": project_id,
        "created_at": datetime.utcnow().isoformat() + "Z",
        "processing_time": {
            "start_time": datetime.utcfromtimestamp(start_time).isoformat() + "Z",
            "end_time": datetime.utcnow().isoformat() + "Z",
            "duration_seconds": round(time.time() - start_time, 2)
        },
        "stats": stats
    }
    
    manifest_path = project_dir / "project_manifest.json"
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)
    
    _logger.info(f"Project complete: {stats['snapshots_created']} snapshots")
    
    return manifest


def _get_file_size(path: Path, snapshot_type: str) -> int:
    """Get file size (LOC for code, bytes for others)."""
    if snapshot_type == "code":
        try:
            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                return sum(1 for line in f if line.strip())
        except (IOError, OSError, UnicodeDecodeError):
            return 0
    return path.stat().st_size


def _categorize_file(path: Path, size: int) -> str:
    """Categorize file by size."""
    settings = get_settings()
    limits = settings.parser_limits
    
    if size >= limits.hard_cap_loc:
        return "rejected"
    elif size >= limits.potential_god_loc:
        return "potential_god"
    elif size >= limits.soft_cap_loc:
        return "large"
    return "normal"


def _parse_file_multi_parser(route: FileRoute) -> Dict[str, Dict[str, Any]]:
    """Parse file with multiple parsers and merge."""
    categorized_results = []
    
    for parser in route.parsers:
        try:
            if parser == "tree_sitter":
                output = parse_code_tree_sitter(path=route.path, language=route.language)
                categorized = _field_mapper.categorize_parser_output(output, "tree_sitter", str(route.path))
                categorized_results.append(categorized)
            
            elif parser == "semgrep":
                output = parse_code_semgrep(path=route.path, language=route.language)
                categorized = _field_mapper.categorize_parser_output(output, "semgrep", str(route.path))
                categorized_results.append(categorized)
            
            elif parser == "text_extractor":
                output = extract_text(route.path)
                categorized = _field_mapper.categorize_parser_output(output, "text_extractor", str(route.path))
                categorized_results.append(categorized)
            
            elif parser == "csv_parser":
                output = parse_csv_file(route.path)
                categorized = _field_mapper.categorize_parser_output(output, "csv_parser", str(route.path))
                categorized_results.append(categorized)
        
        except Exception as e:
            _logger.error(f"Parser {parser} failed on {route.path}: {e}")
    
    if not categorized_results:
        return {}
    
    return _field_mapper.merge_categorized_fields(*categorized_results)


def delete_project(project_id: str) -> None:
    """Delete all snapshots for project."""
    repo = SnapshotRepository()
    deleted = repo.delete_by_project(project_id)
    
    settings = get_settings()
    project_dir = settings.data_dir / "projects" / project_id
    
    if project_dir.exists():
        import shutil
        shutil.rmtree(project_dir)
    
    _logger.info(f"Deleted project {project_id}: {deleted} snapshots")


def get_project_notebook(project_id: str, vendor_id: str) -> Dict[str, Any]:
    """Retrieve assembled project notebook."""
    if _snapshot_builder is None:
        raise SandboxToolError("Tool not initialized")
    
    _logger.info("Vendor call", extra={
        "vendor_id": vendor_id,
        "project_id": project_id,
        "action": "get_notebook"
    })
    
    return _snapshot_builder.assemble_project_notebook(project_id)


def get_project_manifest(project_id: str) -> Dict[str, Any]:
    """Retrieve project manifest."""
    settings = get_settings()
    path = settings.data_dir / "projects" / project_id / "project_manifest.json"

    if not path.exists():
        raise SandboxToolError(f"Manifest not found: {project_id}")

    with open(path) as f:
        return json.load(f)


def get_metrics() -> Dict[str, Any]:
    """Get aggregated metrics for dashboard."""
    settings = get_settings()
    projects_dir = settings.data_dir / "projects"

    metrics = {
        "projects": {"total": 0, "list": []},
        "files": {"processed": 0, "categorization": {"normal": 0, "large": 0, "potential_god": 0, "rejected": 0}},
        "snapshots": {"created": 0, "failed": 0, "by_type": {}},
        "parsers": {}
    }

    if not projects_dir.exists():
        return metrics

    # Find all manifest files recursively
    manifest_files = list(projects_dir.glob("**/project_manifest.json"))

    for manifest_path in manifest_files:

        try:
            with open(manifest_path) as f:
                manifest = json.load(f)
        except (IOError, json.JSONDecodeError):
            continue

        stats = manifest.get("stats", {})

        metrics["projects"]["total"] += 1
        metrics["projects"]["list"].append({
            "project_id": manifest.get("project_id", manifest_path.parent.name),
            "snapshots": stats.get("snapshots_created", 0),
            "files": stats.get("files_processed", 0)
        })

        metrics["files"]["processed"] += stats.get("files_processed", 0)
        metrics["snapshots"]["created"] += stats.get("snapshots_created", 0)
        metrics["snapshots"]["failed"] += stats.get("snapshots_failed", 0)

        # Aggregate file categorization
        file_cat = stats.get("file_categorization", {})
        if file_cat:
            for cat, count in file_cat.items():
                if cat in metrics["files"]["categorization"]:
                    metrics["files"]["categorization"][cat] += count
        else:
            # Backfill from legacy stats: rejected = snapshots_rejected, rest = normal
            rejected = stats.get("snapshots_rejected", 0)
            processed = stats.get("files_processed", 0)
            metrics["files"]["categorization"]["rejected"] += rejected
            metrics["files"]["categorization"]["normal"] += processed

        # Aggregate snapshot types
        for stype, count in stats.get("snapshot_types", {}).items():
            metrics["snapshots"]["by_type"][stype] = metrics["snapshots"]["by_type"].get(stype, 0) + count

        # Aggregate parser usage
        for parser, count in stats.get("parsers_used", {}).items():
            metrics["parsers"][parser] = metrics["parsers"].get(parser, 0) + count

    return metrics
