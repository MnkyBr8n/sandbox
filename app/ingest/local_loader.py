# sandbox/app/ingest/local_loader.py
"""
Purpose: Ingest a user provided local directory as a project source.
Validates limits, copies files into the sandbox repo area, and returns a file manifest.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import List

from app.config.settings import get_settings
from app.security.sandbox_limits import SandboxLimitsEnforcer, SandboxLimitError
from app.logging.logger import get_logger


class LocalIngestError(Exception):
    pass


def ingest_local_directory(
    source_dir: Path,
    project_id: str,
) -> List[Path]:
    """
    Copy a local directory into the sandbox repo area for the given project_id.
    Returns a list of ingested file paths.
    """
    settings = get_settings()
    logger = get_logger("ingest.local")
    limits = SandboxLimitsEnforcer()

    if not source_dir.exists() or not source_dir.is_dir():
        raise LocalIngestError("Source directory does not exist or is not a directory")

    dest_root = settings.repos_dir / project_id
    dest_root.mkdir(parents=True, exist_ok=True)

    files: List[Path] = []

    for path in source_dir.rglob("*"):
        if path.is_dir():
            continue

        try:
            limits.check_project_time()
            limits.check_file_size(path)
        except SandboxLimitError as exc:
            logger.warning(f"Skipping file due to limit: {path} ({exc})")
            continue

        rel = path.relative_to(source_dir)
        dest = dest_root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)

        shutil.copy2(path, dest)
        files.append(dest)

    # Repo level bounds check
    try:
        limits.check_repo_bounds(files=files, repo_root=dest_root)
    except SandboxLimitError as exc:
        raise LocalIngestError(str(exc)) from exc

    logger.info(f"Ingested {len(files)} files for project {project_id}")
    return files