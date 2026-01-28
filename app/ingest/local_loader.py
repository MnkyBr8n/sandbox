# sandbox/app/ingest/local_loader.py
"""
Purpose: Ingest from per-project staging area (used by both human users and code agents).

Architecture:
- Each project has isolated staging folder: staging/{project_id}/
- Agent/User uploads to staging/{project_id}/
- local_loader ingests from staging/{project_id}/ → repos/{project_id}/
- Snapshots filtered by project_id (no global notebook)
- Delete project = delete staging + repos + snapshots

Security:
- Enforces per-project staging path restrictions
- Ignores dangerous files (secrets, dependencies, .git)
- Symlink protection
- Path traversal protection
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import List, Set
import fnmatch

from app.config.settings import get_settings
from app.security.sandbox_limits import SandboxLimitsEnforcer, SandboxLimitError
from app.logging.logger import get_logger


class LocalIngestError(Exception):
    pass


# Security: Patterns to ignore during ingestion
IGNORE_PATTERNS = [
    # Version control
    ".git", ".git/*", ".svn", ".hg",
    
    # Dependencies (too large, not needed)
    "node_modules", "node_modules/*",
    "__pycache__", "__pycache__/*",
    ".venv", "venv", "env",
    "vendor", "target", "build", "dist",
    ".pytest_cache", ".tox",
    
    # Secrets & credentials (CRITICAL - never ingest)
    ".env", ".env.*",
    "*.pem", "*.key", "*.pfx", "*.p12",
    ".aws", ".aws/*",
    ".ssh", ".ssh/*",
    ".gnupg", ".gnupg/*",
    "credentials", "credentials.*",
    "secrets", "secrets.*",
    "*_rsa", "*_rsa.*",
    "id_rsa", "id_ecdsa", "id_ed25519",
    
    # IDE/Editor files
    ".vscode", ".vscode/*",
    ".idea", ".idea/*",
    ".vs", ".vs/*",
    "*.swp", "*.swo", "*~",
    ".project", ".settings",
    
    # OS files
    ".DS_Store", "Thumbs.db", "desktop.ini",
    
    # Build artifacts
    "*.pyc", "*.pyo", "*.class", "*.o", "*.obj",
    "*.so", "*.dll", "*.dylib",
    
    # Logs
    "*.log", "logs", "logs/*",
    
    # Database files (potentially sensitive)
    "*.db", "*.sqlite", "*.sqlite3",
    
    # Backup files
    "*.bak", "*.backup", "*.tmp",
    
    # Large media (optional - uncomment if needed)
    # "*.mp4", "*.avi", "*.mov", "*.mkv",
]


def _should_ignore(path: Path, relative_path: Path) -> bool:
    """
    Check if path should be ignored based on patterns.
    
    Args:
        path: Absolute path
        relative_path: Path relative to source root
    
    Returns:
        True if should be ignored
    """
    path_str = str(relative_path)
    
    for pattern in IGNORE_PATTERNS:
        # Check each part of the path
        for part in relative_path.parts:
            if fnmatch.fnmatch(part, pattern):
                return True
        
        # Check full relative path
        if fnmatch.fnmatch(path_str, pattern):
            return True
        
        # Check filename
        if fnmatch.fnmatch(path.name, pattern):
            return True
    
    return False


def _validate_staging_path(source_dir: Path, project_id: str) -> None:
    """
    Validate source_dir is the correct per-project staging area.
    
    Expected: staging/{project_id}/
    
    Args:
        source_dir: Directory to validate
        project_id: Project identifier
    
    Raises:
        LocalIngestError: If path is not the correct project staging area
    """
    settings = get_settings()
    
    # Per-project staging: staging/{project_id}/
    expected_staging = settings.data_dir / "staging" / project_id
    expected_staging.mkdir(parents=True, exist_ok=True)
    
    # Resolve to absolute paths
    source_resolved = source_dir.resolve()
    expected_resolved = expected_staging.resolve()
    
    if source_resolved != expected_resolved:
        raise LocalIngestError(
            f"Source must be project staging area: {expected_staging}. "
            f"Got: {source_dir}"
        )


def _validate_destination_path(dest: Path, dest_root: Path) -> None:
    """
    Validate destination path doesn't escape project root.
    
    Args:
        dest: Destination path
        dest_root: Project root
    
    Raises:
        LocalIngestError: If path traversal detected
    """
    try:
        dest.resolve().relative_to(dest_root.resolve())
    except ValueError:
        raise LocalIngestError(
            f"Path traversal detected: {dest} escapes {dest_root}"
        )


def ingest_local_directory(
    source_dir: Path,
    project_id: str,
) -> List[Path]:
    """
    Ingest from per-project staging area into project namespace.
    
    Expected source: staging/{project_id}/
    Destination: repos/{project_id}/
    
    Used by both human users and code agents uploading to project-specific staging.
    Each project has completely isolated pipeline (staging → repos → snapshots).
    
    Args:
        source_dir: Must be staging/{project_id}/
        project_id: Unique project identifier
    
    Returns:
        List of ingested file paths
    
    Raises:
        LocalIngestError: If validation fails or limits exceeded
    
    Security:
    - Enforces per-project staging path
    - Ignores dangerous files (secrets, .git, dependencies)
    - Symlink protection
    - Path traversal protection
    """
    settings = get_settings()
    logger = get_logger("ingest.local")
    limits = SandboxLimitsEnforcer()

    # Validate source is correct project staging area
    _validate_staging_path(source_dir, project_id)

    if not source_dir.exists() or not source_dir.is_dir():
        raise LocalIngestError(
            f"Source directory does not exist or is not a directory: {source_dir}"
        )

    # Create project repos area
    dest_root = settings.repos_dir / project_id
    dest_root.mkdir(parents=True, exist_ok=True)

    files: List[Path] = []
    skipped_files: Set[str] = set()
    skipped_count = 0

    logger.info("Starting local ingestion", extra={
        "source_dir": str(source_dir),
        "project_id": project_id,
        "dest_root": str(dest_root)
    })

    for path in source_dir.rglob("*"):
        if path.is_dir():
            continue
        
        # Security: Skip symlinks (could escape sandbox)
        if path.is_symlink():
            logger.warning(f"Skipping symlink: {path}")
            skipped_count += 1
            skipped_files.add("symlink")
            continue
        
        # Get relative path for ignore checking
        try:
            rel = path.relative_to(source_dir)
        except ValueError:
            logger.error(f"Path not relative to source: {path}")
            continue
        
        # Security: Check ignore patterns
        if _should_ignore(path, rel):
            logger.debug(f"Ignoring file: {path}")
            skipped_count += 1
            skipped_files.add("ignored_pattern")
            continue

        # Check limits
        try:
            limits.check_project_time()
            limits.check_file_size(path)
        except SandboxLimitError as exc:
            logger.warning(f"Skipping file due to limit: {path} ({exc})")
            skipped_count += 1
            skipped_files.add("limit_exceeded")
            continue

        # Copy to project repos area
        dest = dest_root / rel
        
        # Security: Validate destination doesn't escape project root
        _validate_destination_path(dest, dest_root)
        
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest)
        files.append(dest)

    # Repo level bounds check
    try:
        limits.check_repo_bounds(files=files, repo_root=dest_root)
    except SandboxLimitError as exc:
        raise LocalIngestError(str(exc)) from exc

    # Calculate stats
    total_size_bytes = sum(f.stat().st_size for f in files)
    total_size_mb = total_size_bytes / (1024 * 1024)

    logger.info("Local ingestion complete", extra={
        "project_id": project_id,
        "source_dir": str(source_dir),
        "files_ingested": len(files),
        "files_skipped": skipped_count,
        "skip_reasons": list(skipped_files),
        "total_size_mb": round(total_size_mb, 2)
    })
    
    return files


def get_project_staging_path(project_id: str) -> Path:
    """
    Get the staging path for a specific project.
    
    Helper function for agents/users to know where to upload files.
    
    Args:
        project_id: Project identifier
    
    Returns:
        Path to project staging directory (staging/{project_id}/)
    """
    settings = get_settings()
    staging_path = settings.data_dir / "staging" / project_id
    staging_path.mkdir(parents=True, exist_ok=True)
    return staging_path


def delete_project_staging(project_id: str) -> None:
    """
    Delete project staging area.
    
    Called during project deletion to clean up staging files.
    
    Args:
        project_id: Project identifier
    """
    import shutil
    
    settings = get_settings()
    logger = get_logger("ingest.local")
    
    staging_path = settings.data_dir / "staging" / project_id
    
    if staging_path.exists():
        shutil.rmtree(staging_path)
        logger.info(f"Deleted project staging: {staging_path}")
    else:
        logger.debug(f"Project staging does not exist: {staging_path}")


def cleanup_project_staging_files(project_id: str, max_age_hours: int = 36) -> int:
    """
    Clean up old files from project staging area.
    
    Call this after project processing or periodically per project.
    
    Args:
        project_id: Project identifier
        max_age_hours: Delete files older than this (default 24 hours)
    
    Returns:
        Number of files deleted
    """
    import time
    
    settings = get_settings()
    logger = get_logger("ingest.local")
    
    staging_path = settings.data_dir / "staging" / project_id
    if not staging_path.exists():
        return 0
    
    cutoff_time = time.time() - (max_age_hours * 4800)
    deleted_count = 0
    
    for path in staging_path.rglob("*"):
        if path.is_dir():
            continue
        
        if path.stat().st_mtime < cutoff_time:
            try:
                path.unlink()
                deleted_count += 1
                logger.debug(f"Deleted old staging file: {path}")
            except Exception as e:
                logger.warning(f"Failed to delete {path}: {e}")
    
    if deleted_count > 0:
        logger.info(f"Cleaned up {deleted_count} old staging files for project {project_id}")
    
    return deleted_count


def cleanup_all_staging_areas(max_age_hours: int = 36) -> int:
    """
    Clean up old files from all project staging areas.
    
    Call this periodically (e.g., daily cron job) to prevent disk bloat.
    
    Args:
        max_age_hours: Delete files older than this (default 24 hours)
    
    Returns:
        Total number of files deleted across all projects
    """
    settings = get_settings()
    logger = get_logger("ingest.local")
    
    staging_root = settings.data_dir / "staging"
    if not staging_root.exists():
        return 0
    
    total_deleted = 0
    
    # Iterate through all project staging directories
    for project_dir in staging_root.iterdir():
        if not project_dir.is_dir():
            continue
        
        project_id = project_dir.name
        deleted = cleanup_project_staging_files(project_id, max_age_hours)
        total_deleted += deleted
    
    logger.info(f"Cleaned up {total_deleted} old staging files across all projects")
    return total_deleted
