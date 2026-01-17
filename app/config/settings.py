# sandbox/app/config/settings.py
"""
Purpose: Centralized, validated configuration for the sandbox service (limits, paths, DB, network allowlist).
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Project root: go up from app/config to project root
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class SandboxLimits(BaseModel):
    # Ingest limits
    max_repo_bytes: int = Field(default=500 * 1024 * 1024, ge=1)  # 500 MB
    max_repo_files: int = Field(default=50_000, ge=1)
    max_repo_depth: int = Field(default=12, ge=1)

    # File limits
    max_pdf_bytes: int = Field(default=50 * 1024 * 1024, ge=1)  # 50 MB
    max_text_bytes: int = Field(default=10 * 1024 * 1024, ge=1)  # 10 MB (txt/json/yaml/csv)
    max_code_file_bytes: int = Field(default=1 * 1024 * 1024, ge=1)  # 1 MB

    # PDF limits
    max_pdf_pages_per_file: int = Field(default=300, ge=1)
    max_pdf_pages_per_job: int = Field(default=1000, ge=1)

    # Runtime limits
    max_job_seconds: int = Field(default=15 * 60, ge=1)  # 15 minutes
    max_project_run_seconds: int = Field(default=60 * 60, ge=1)  # 60 minutes
    idle_timeout_seconds: int = Field(default=24 * 60 * 60, ge=1)  # 24 hours

    # Snapshot notebook limits
    snapshot_notebook_cap_bytes: int = Field(default=100 * 1024 * 1024, ge=1)  # 100 MB


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
    model_config = SettingsConfigDict(
        env_prefix="SANDBOX_",
        case_sensitive=False,
        env_file=_PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Environment
    environment: str = Field(default="dev")
    service_name: str = Field(default="sandbox")
    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8080, ge=1, le=65535)

    # Storage paths
    data_dir: Path = Field(default=Path("data"))
    uploads_dir: Path = Field(default=Path("data/uploads"))
    repos_dir: Path = Field(default=Path("data/repos"))
    schemas_dir: Path = Field(default=Path("schemas"))

    # Schema reference
    notebook_schema_path: Path = Field(default=Path("schemas/master_notebook.yaml"))

    @model_validator(mode="after")
    def _resolve_paths(self) -> "Settings":
        """Resolve all relative paths against project root."""
        self.data_dir = _PROJECT_ROOT / self.data_dir
        self.uploads_dir = _PROJECT_ROOT / self.uploads_dir
        self.repos_dir = _PROJECT_ROOT / self.repos_dir
        self.schemas_dir = _PROJECT_ROOT / self.schemas_dir
        self.notebook_schema_path = _PROJECT_ROOT / self.notebook_schema_path
        return self

    # Database
    postgres_dsn: str = Field(
        default="postgresql+psycopg://sandbox:sandbox@postgres:5432/sandbox",
        description="SQLAlchemy-compatible DSN",
    )

    # GitHub ingest (HTTPS clone)
    git_clone_timeout_seconds: int = Field(default=300, ge=1)
    git_max_concurrent_clones: int = Field(default=2, ge=1)

    # Policies
    limits: SandboxLimits = Field(default_factory=SandboxLimits)
    network: NetworkPolicy = Field(default_factory=NetworkPolicy)

    # Logging config (implementation in logging/logger.py)
    log_level: str = Field(default="INFO")
    log_json: bool = Field(default=True)

    # Project separation (Option B)
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