# sandbox/app/ingest/github_cloner.py
"""
Purpose: Ingest a remote repository via HTTPS git clone into the sandbox.
Enforces outbound allowlist and sandbox limits.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import List, Optional

from app.config.settings import get_settings
from app.logging.logger import get_logger
from app.security.network_policy import NetworkPolicyError, validate_git_remote
from app.security.sandbox_limits import SandboxLimitError, SandboxLimitsEnforcer


class GitCloneError(Exception):
    pass


def clone_github_repo(
    repo_remote: str,
    project_id: str,
    *,
    branch: Optional[str] = None,
) -> List[Path]:
    """
    Clone repo_remote into sandbox repos dir under project_id.

    Returns a list of file paths (excluding .git contents).
    """
    settings = get_settings()
    logger = get_logger("ingest.github")
    limits = SandboxLimitsEnforcer()

    try:
        safe_remote = validate_git_remote(repo_remote)
    except NetworkPolicyError as exc:
        raise GitCloneError(str(exc)) from exc

    dest_root = settings.repos_dir / project_id
    if dest_root.exists():
        # On Windows, git files can be locked - use onerror to force delete
        def handle_remove_readonly(func, path, exc_info):
            import stat
            os.chmod(path, stat.S_IWRITE)
            func(path)
        shutil.rmtree(dest_root, onexc=handle_remove_readonly)
    dest_root.mkdir(parents=True, exist_ok=True)

    job_start = time.time()

    cmd: list[str] = [
        "git",
        "clone",
        "--no-tags",
        "--depth",
        "1",
        safe_remote,
        str(dest_root),
    ]
    if branch:
        cmd[2:2] = ["--branch", branch]

    try:
        limits.check_project_time()
        subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True,
            timeout=settings.git_clone_timeout_seconds,
        )
        limits.check_job_time(job_start)
    except subprocess.TimeoutExpired as exc:
        raise GitCloneError("git clone timeout") from exc
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        raise GitCloneError(f"git clone failed: {stderr or 'UNKNOWN'}") from exc
    except SandboxLimitError as exc:
        raise GitCloneError(str(exc)) from exc

    files: List[Path] = []
    for path in dest_root.rglob("*"):
        if path.is_dir():
            continue
        if ".git" in path.parts:
            continue

        try:
            limits.check_project_time()
            limits.check_file_size(path)
            files.append(path)
        except SandboxLimitError as exc:
            logger.warning(f"Removing file due to limit: {path} ({exc})")
            try:
                path.unlink(missing_ok=True)
            except Exception:
                pass

    try:
        limits.check_repo_bounds(files=files, repo_root=dest_root)
    except SandboxLimitError as exc:
        raise GitCloneError(str(exc)) from exc

    logger.info(f"Cloned {safe_remote} into {dest_root} with {len(files)} files")
    return files