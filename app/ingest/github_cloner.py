# sandbox/app/ingest/github_cloner.py
"""
Purpose: Ingest remote repository via HTTPS git clone with comprehensive security and retry logic.

V2 Enhancements:
- Cleanup on failure (no partial repos)
- Git credential leakage protection
- Malicious git hooks removal
- Retry logic with exponential backoff
- Clone progress logging
- Performance metrics
"""

from __future__ import annotations

import shutil
import subprocess
import time
import os
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
    include_submodules: bool = False,
) -> List[Path]:
    """
    Clone repo_remote into sandbox repos dir under project_id.
    
    Security:
    - Network policy validation
    - Credential leakage protection
    - Git hooks removal
    - Cleanup on failure
    
    Reliability:
    - Retry logic with exponential backoff (3 attempts)
    - Progress logging
    - Performance metrics
    
    Args:
        repo_remote: Git remote URL (HTTPS or git@)
        project_id: Project identifier
        branch: Optional branch to clone
        include_submodules: Clone with submodules (default: False)
    
    Returns:
        List of file paths (excluding .git contents)
    
    Raises:
        GitCloneError: If clone fails or limits exceeded
    """
    settings = get_settings()
    logger = get_logger("ingest.github")
    limits = SandboxLimitsEnforcer()

    # Validate remote against network policy
    try:
        safe_remote = validate_git_remote(repo_remote)
    except NetworkPolicyError as exc:
        raise GitCloneError(str(exc)) from exc

    dest_root = settings.repos_dir / project_id
    
    # Clean up existing directory
    if dest_root.exists():
        shutil.rmtree(dest_root)
    dest_root.mkdir(parents=True, exist_ok=True)

    job_start = time.time()
    files: List[Path] = []

    try:
        # Build git clone command
        depth = getattr(settings, 'git_clone_depth', 1)
        cmd: list[str] = [
            "git",
            "clone",
            "--no-tags",
            "--depth",
            str(depth),
            safe_remote,
            str(dest_root),
        ]
        
        if branch:
            cmd[2:2] = ["--branch", branch]
        
        if include_submodules:
            cmd.extend(["--recurse-submodules", "--shallow-submodules"])
        
        # Security: Use explicit env allowlist (prevents leaking sensitive vars)
        # Include Windows-specific vars required for DNS/network operations
        safe_env_keys = {
            "PATH", "HOME", "USER", "LANG", "LC_ALL", "TZ", "TMPDIR", "TEMP", "TMP",
            # Windows-specific (required for network/DNS)
            "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC",
            "USERPROFILE", "APPDATA", "LOCALAPPDATA",
        }
        env = {k: v for k, v in os.environ.items() if k in safe_env_keys}
        env["GIT_TERMINAL_PROMPT"] = "0"  # Prevent password prompts
        env["GIT_ASKPASS"] = "echo"        # Prevent credential popups
        
        # Retry logic with exponential backoff
        max_retries = 3
        last_error = None
        
        for attempt in range(max_retries):
            try:
                limits.check_project_time()
                
                logger.info(f"Cloning repository (attempt {attempt + 1}/{max_retries})", extra={
                    "project_id": project_id,
                    "remote": safe_remote,
                    "branch": branch or "default",
                    "depth": depth
                })
                
                # Execute clone with timeout
                result = subprocess.run(
                    cmd,
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=settings.git_clone_timeout_seconds,
                    env=env
                )
                
                # Log successful clone
                if result.stderr:
                    for line in result.stderr.strip().split('\n'):
                        if line:
                            logger.debug(f"Git: {line}")
                
                limits.check_job_time(job_start)
                break  # Success - exit retry loop
                
            except subprocess.TimeoutExpired as exc:
                last_error = exc
                logger.warning(f"Git clone timeout on attempt {attempt + 1}")
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)  # Exponential backoff: 1s, 2s, 4s
                    continue
                raise GitCloneError("git clone timeout after retries") from exc
                
            except subprocess.CalledProcessError as exc:
                last_error = exc
                stderr = (exc.stderr or "").strip()
                logger.warning(f"Git clone failed on attempt {attempt + 1}: {stderr}")
                
                if attempt < max_retries - 1:
                    # Retry on network errors, not auth errors
                    if any(err in stderr.lower() for err in ['network', 'connection', 'timeout', 'temporary']):
                        time.sleep(2 ** attempt)
                        continue
                
                raise GitCloneError(f"git clone failed: {stderr or 'UNKNOWN'}") from exc
                
            except SandboxLimitError as exc:
                raise GitCloneError(str(exc)) from exc
        
        # Security: Remove git hooks (prevent malicious hook execution)
        git_hooks_dir = dest_root / ".git" / "hooks"
        if git_hooks_dir.exists():
            shutil.rmtree(git_hooks_dir)
            logger.info("Removed git hooks for security", extra={
                "project_id": project_id,
                "hooks_path": str(git_hooks_dir)
            })
        
        # Enumerate files (exclude .git)
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

        # Repo bounds check
        try:
            limits.check_repo_bounds(files=files, repo_root=dest_root)
        except SandboxLimitError as exc:
            raise GitCloneError(str(exc)) from exc

        # Performance metrics
        clone_duration = time.time() - job_start
        total_size_bytes = sum(f.stat().st_size for f in files)
        total_size_mb = total_size_bytes / (1024 * 1024)
        
        logger.info("Clone complete", extra={
            "project_id": project_id,
            "remote": safe_remote,
            "branch": branch or "default",
            "files_cloned": len(files),
            "clone_duration_seconds": round(clone_duration, 2),
            "total_size_mb": round(total_size_mb, 2),
            "avg_file_size_kb": round(total_size_bytes / len(files) / 1024, 2) if files else 0
        })
        
        return files
    
    except Exception as e:
        # Cleanup on failure (no partial repos)
        logger.error(f"Clone failed, cleaning up: {e}", extra={
            "project_id": project_id,
            "remote": safe_remote
        })
        
        if dest_root.exists():
            try:
                shutil.rmtree(dest_root)
                logger.info(f"Cleaned up failed clone: {dest_root}")
            except Exception as cleanup_error:
                logger.warning(f"Failed to cleanup {dest_root}: {cleanup_error}")
        
        raise