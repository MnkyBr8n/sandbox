# sandbox/app/security/sandbox_limits.py
"""
Purpose: Enforce sandbox size, file, and runtime limits defined in config settings.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Iterable

from app.config.settings import get_settings


class SandboxLimitError(Exception):
    pass


class SandboxLimitsEnforcer:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.limits = self.settings.limits
        self._project_start_ts = time.time()

    # ---------- Runtime enforcement ----------

    def check_job_time(self, job_start_ts: float) -> None:
        elapsed = time.time() - job_start_ts
        if elapsed > self.limits.max_job_seconds:
            raise SandboxLimitError(
                f"Job runtime exceeded {self.limits.max_job_seconds} seconds"
            )

    def check_project_time(self) -> None:
        elapsed = time.time() - self._project_start_ts
        if elapsed > self.limits.max_project_run_seconds:
            raise SandboxLimitError(
                f"Project runtime exceeded {self.limits.max_project_run_seconds} seconds"
            )

    # ---------- File and repo enforcement ----------

    def check_file_size(self, path: Path) -> None:
        size = path.stat().st_size

        suffix = path.suffix.lower()
        if suffix == ".pdf" and size > self.limits.max_pdf_bytes:
            raise SandboxLimitError("PDF file exceeds size limit")

        if suffix in {".txt", ".json", ".yaml", ".yml", ".csv"} and size > self.limits.max_text_bytes:
            raise SandboxLimitError("Text file exceeds size limit")

        if size > self.limits.max_code_file_bytes:
            raise SandboxLimitError("Code file exceeds size limit")

    def check_repo_bounds(self, files: Iterable[Path], repo_root: Path) -> None:
        total_bytes = 0
        file_count = 0

        for path in files:
            file_count += 1
            total_bytes += path.stat().st_size

            depth = len(path.relative_to(repo_root).parts)
            if depth > self.limits.max_repo_depth:
                raise SandboxLimitError("Repository directory depth exceeded")

            if file_count > self.limits.max_repo_files:
                raise SandboxLimitError("Repository file count exceeded")

            if total_bytes > self.limits.max_repo_bytes:
                raise SandboxLimitError("Repository total size exceeded")

    # ---------- Snapshot enforcement ----------

    def check_snapshot_size(self, snapshot_bytes: int) -> None:
        if snapshot_bytes > self.limits.snapshot_notebook_cap_bytes:
            raise SandboxLimitError("Snapshot notebook size cap exceeded")