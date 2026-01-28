# sandbox/app/config/settings.py
"""
Purpose: Centralized, validated configuration for the sandbox service (limits, paths, DB, network allowlist).
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class SandboxLimits(BaseModel):
    # Ingest limits
    max_repo_bytes: int = Field(default=2 * 1024 * 1024 * 1024, ge=1)  # 2 GB (increased for large repos)
    max_repo_files: int = Field(default=100_000, ge=1)  # Increased for large repos
    max_repo_depth: int = Field(default=12, ge=1)

    # File limits
    max_pdf_bytes: int = Field(default=50 * 1024 * 1024, ge=1)  # 50 MB
    max_text_bytes: int = Field(default=10 * 1024 * 1024, ge=1)  # 10 MB
    max_code_file_bytes: int = Field(default=5 * 1024 * 1024, ge=1)  # 5 MB (increased for large files)

    # PDF limits
    max_pdf_pages_per_file: int = Field(default=300, ge=1)
    max_pdf_pages_per_job: int = Field(default=1000, ge=1)

    # Runtime limits
    max_job_seconds: int = Field(default=15 * 60, ge=1)  # 15 minutes
    max_project_run_seconds: int = Field(default=60 * 60, ge=1)  # 60 minutes
    idle_timeout_seconds: int = Field(default=24 * 60 * 60, ge=1)  # 24 hours

    # Snapshot notebook limits
    snapshot_notebook_cap_bytes: int = Field(default=500 * 1024 * 1024, ge=1)  # 500 MB (increased for multiple snapshots per file)


class ParserLimits(BaseModel):
    """Limits and thresholds for file parsers."""
    
    # File size thresholds (LOC)
    soft_cap_loc: int = Field(default=1500, ge=1)  # Warn, refactor recommended
    large_file_loc: int = Field(default=3999, ge=1)  # Large file warning
    potential_god_loc: int = Field(default=4000, ge=1)  # Potential god file (for future)
    hard_cap_loc: int = Field(default=5000, ge=1)  # Reject files >= 5000 LOC
    
    # Tree-sitter timeouts (milliseconds)
    tree_sitter_timeout_interactive: int = Field(default=500, ge=1)
    tree_sitter_timeout_initial: int = Field(default=2000, ge=1)
    
    # Semgrep settings
    semgrep_timeout_per_file: int = Field(default=30, ge=1)  # seconds
    semgrep_code_context_lines: int = Field(default=3, ge=0)
    
    # CSV limits
    csv_hard_cap_file_size_mb: int = Field(default=50, ge=1)
    csv_hard_cap_rows: int = Field(default=500_000, ge=1)
    csv_hard_cap_cell_chars: int = Field(default=5_000, ge=1)
    csv_soft_cap_file_size_mb: int = Field(default=5, ge=1)
    csv_soft_cap_rows: int = Field(default=50_000, ge=1)


class NetworkPolicy(BaseModel):
    outbound_enabled: bool = True
    domain_allowlist: List[str] = Field(default_factory=lambda: ["github.com", "raw.githubusercontent.com"])

    @field_validator("domain_allowlist")
    @classmethod
    def _dedupe_and_strip(cls, v: List[str]) -> List[str]:
        cleaned: List[str] = []
        for item in v:
            item = (item or "").strip().lower()
            if item and item not in cleaned:
                cleaned.append(item)
        return cleaned


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SANDBOX_", case_sensitive=False, env_file=".env")

    # Environment
    environment: str = Field(default="dev")
    service_name: str = Field(default="sandbox")
    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8080, ge=1, le=65535)

    # Storage paths (inside container)
    data_dir: Path = Field(default=Path("data"))
    uploads_dir: Path = Field(default=Path("data/uploads"))
    repos_dir: Path = Field(default=Path("data/repos"))
    schemas_dir: Path = Field(default=Path("app/schemas"))

    # Schema reference
    notebook_schema_path: Path = Field(default=Path("app/schemas/master_notebook.yaml"))

    # Database (no default - must be set via SANDBOX_POSTGRES_DSN env var)
    postgres_dsn: str = Field(
        description="SQLAlchemy-compatible DSN (required, set via SANDBOX_POSTGRES_DSN)",
    )

    # GitHub ingest (HTTPS clone)
    git_clone_timeout_seconds: int = Field(default=600, ge=1)  # 10 minutes (increased for large repos)
    git_max_concurrent_clones: int = Field(default=2, ge=1)
    
    # HTTP request timeout
    http_request_timeout_seconds: int = Field(default=30, ge=1)  # 30 seconds for outbound HTTP requests

    # Policies
    limits: SandboxLimits = Field(default_factory=SandboxLimits)
    parser_limits: ParserLimits = Field(default_factory=ParserLimits)
    network: NetworkPolicy = Field(default_factory=NetworkPolicy)

    # Logging config
    log_level: str = Field(default="INFO")
    log_json: bool = Field(default=True)

    # Project separation
    db_partition_key: str = Field(default="project_id")

    @field_validator("environment")
    @classmethod
    def _env_normalize(cls, v: str) -> str:
        v = (v or "").strip().lower()
        return v or "dev"

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        self.repos_dir.mkdir(parents=True, exist_ok=True)
        self.schemas_dir.mkdir(parents=True, exist_ok=True)


_settings: Optional[Settings] = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        s = Settings()
        s.ensure_dirs()
        _settings = s
    return _settings
