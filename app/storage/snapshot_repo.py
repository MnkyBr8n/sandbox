# snap/app/storage/snapshot_repo.py
"""
Purpose: Persist snapshot notebooks keyed by snapshot_id with idempotency protection.

Architecture:
- snapshot_type is one of 12 categories (file_metadata, imports, exports, etc.)
- UNIQUE constraint on (project_id, source_file, snapshot_type)
- One file creates multiple snapshots (one per category)
- Query methods by snapshot_type for RAG queries
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Any, Optional
from datetime import datetime
from uuid import uuid4
import yaml
import json

from sqlalchemy import text

from app.logging.logger import get_logger
from app.storage.db import db_session, get_engine
from app.config.settings import get_settings


class SnapshotRepoError(Exception):
    pass


@dataclass(frozen=True)
class FieldConfig:
    field_id: str
    value_type: str
    multi: bool
    required: bool


@dataclass(frozen=True)
class SnapshotRecord:
    snapshot_id: str
    project_id: str
    snapshot_type: str  # One of 12 categories
    source_file: str
    field_values: Dict[str, Any]  # Direct field_id -> value mapping
    created_at: datetime


class SnapshotRepository:
    def __init__(self) -> None:
        self.logger = get_logger("storage.snapshot_repo")
        self._ensure_table()
        self._load_field_configs()

    def _load_field_configs(self) -> None:
        """Load field configurations from master_notebook.yaml"""
        settings = get_settings()
        schema_path = settings.notebook_schema_path
        
        if not schema_path.exists():
            raise SnapshotRepoError(f"Master schema not found: {schema_path}")
        
        with open(schema_path) as f:
            schema = yaml.safe_load(f)
        
        self.field_configs: Dict[str, FieldConfig] = {}
        
        for snapshot_type, fields in schema.get("field_id_registry", {}).items():
            for field_def in fields:
                fid = field_def["field_id"]
                self.field_configs[fid] = FieldConfig(
                    field_id=fid,
                    value_type=field_def["value_type"],
                    multi=field_def["multi"],
                    required=field_def["required"]
                )

    def _ensure_table(self) -> None:
        """Create snapshot_notebooks table"""
        engine = get_engine()
        with engine.connect() as conn:
            # Drop old UNIQUE constraint if exists
            conn.execute(text("""
                DROP INDEX IF EXISTS snapshot_notebooks_project_id_source_file_key
            """))
            
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS snapshot_notebooks (
                    snapshot_id UUID PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    snapshot_type TEXT NOT NULL,
                    source_file TEXT NOT NULL,
                    field_values JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    UNIQUE(project_id, source_file, snapshot_type)
                )
            """))
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_snapshot_project 
                ON snapshot_notebooks(project_id, created_at)
            """))
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_snapshot_type
                ON snapshot_notebooks(project_id, snapshot_type)
            """))
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_snapshot_file
                ON snapshot_notebooks(project_id, source_file)
            """))
            conn.commit()

    def upsert(
        self,
        project_id: str,
        snapshot_type: str,
        source_file: str,
        field_values: Dict[str, Any],
        snapshot_id: Optional[str] = None,
    ) -> SnapshotRecord:
        """
        Create or update snapshot for (project_id, source_file, snapshot_type).
        
        Each file can have multiple snapshots (one per category).
        Idempotency: same (project_id, source_file, snapshot_type) will not create duplicates.
        
        Args:
            project_id: unique project identifier
            snapshot_type: One of 12 categories (file_metadata, imports, etc.)
            source_file: source file path
            field_values: Dict with field_id -> value mappings (direct, not wrapped)
            snapshot_id: Optional pre-generated UUID (for logging correlation)
        
        Returns:
            SnapshotRecord with final state
        """
        with db_session() as session:
            # Check for existing snapshot (idempotency)
            result = session.execute(
                text("""
                    SELECT snapshot_id, field_values, created_at 
                    FROM snapshot_notebooks 
                    WHERE project_id = :pid AND source_file = :sf AND snapshot_type = :stype
                """),
                {"pid": project_id, "sf": source_file, "stype": snapshot_type}
            )
            row = result.fetchone()

            if row:
                # Existing snapshot: update fields
                snapshot_id = row[0]
                
                self.logger.warning("Duplicate snapshot attempt", extra={
                    "project_id": project_id,
                    "source_file": source_file,
                    "snapshot_type": snapshot_type,
                    "existing_snapshot_id": snapshot_id,
                    "security_event": "idempotency_skip",
                    "action": "update_fields"
                })
                
                session.execute(
                    text("""
                        UPDATE snapshot_notebooks
                        SET field_values = :fv
                        WHERE snapshot_id = :sid
                    """),
                    {"fv": json.dumps(field_values), "sid": snapshot_id}
                )
                
                self.logger.info(f"Updated snapshot snapshot_id={snapshot_id} type={snapshot_type} source={source_file}")
                created_at = row[2]
            else:
                # New snapshot: create with provided or generated UUID
                if snapshot_id is None:
                    snapshot_id = str(uuid4())
                
                session.execute(
                    text("""
                        INSERT INTO snapshot_notebooks
                        (snapshot_id, project_id, snapshot_type, source_file, field_values)
                        VALUES (:sid, :pid, :stype, :sf, :fv)
                    """),
                    {
                        "sid": snapshot_id,
                        "pid": project_id,
                        "stype": snapshot_type,
                        "sf": source_file,
                        "fv": json.dumps(field_values)
                    }
                )
                
                self.logger.info(f"Created snapshot snapshot_id={snapshot_id} type={snapshot_type} source={source_file}")
                created_at = datetime.utcnow()

            # Fetch final state
            result = session.execute(
                text("SELECT field_values FROM snapshot_notebooks WHERE snapshot_id = :sid"),
                {"sid": snapshot_id}
            )
            final_row = result.fetchone()

            return SnapshotRecord(
                snapshot_id=snapshot_id,
                project_id=project_id,
                snapshot_type=snapshot_type,
                source_file=source_file,
                field_values=final_row[0],
                created_at=created_at
            )

    def get_by_snapshot_id(self, snapshot_id: str) -> SnapshotRecord | None:
        """Retrieve snapshot by snapshot_id."""
        with db_session() as session:
            result = session.execute(
                text("""
                    SELECT project_id, snapshot_type, source_file, field_values, created_at 
                    FROM snapshot_notebooks 
                    WHERE snapshot_id = :sid
                """),
                {"sid": snapshot_id}
            )
            row = result.fetchone()

            if not row:
                return None

            return SnapshotRecord(
                snapshot_id=snapshot_id,
                project_id=row[0],
                snapshot_type=row[1],
                source_file=row[2],
                field_values=row[3],
                created_at=row[4]
            )

    def get_by_project(self, project_id: str) -> List[SnapshotRecord]:
        """Retrieve all snapshots for project_id in chronological order."""
        with db_session() as session:
            result = session.execute(
                text("""
                    SELECT snapshot_id, snapshot_type, source_file, field_values, created_at 
                    FROM snapshot_notebooks 
                    WHERE project_id = :pid
                    ORDER BY created_at ASC
                """),
                {"pid": project_id}
            )
            rows = result.fetchall()

            return [
                SnapshotRecord(
                    snapshot_id=row[0],
                    project_id=project_id,
                    snapshot_type=row[1],
                    source_file=row[2],
                    field_values=row[3],
                    created_at=row[4]
                )
                for row in rows
            ]

    def get_by_file(self, project_id: str, source_file: str) -> List[SnapshotRecord]:
        """
        Retrieve all snapshots for a specific file.
        
        Returns multiple snapshots (one per category).
        
        Args:
            project_id: Project identifier
            source_file: Source file path
        
        Returns:
            List of SnapshotRecords for this file
        """
        with db_session() as session:
            result = session.execute(
                text("""
                    SELECT snapshot_id, snapshot_type, field_values, created_at 
                    FROM snapshot_notebooks 
                    WHERE project_id = :pid AND source_file = :sf
                    ORDER BY snapshot_type ASC
                """),
                {"pid": project_id, "sf": source_file}
            )
            rows = result.fetchall()

            return [
                SnapshotRecord(
                    snapshot_id=row[0],
                    project_id=project_id,
                    snapshot_type=row[1],
                    source_file=source_file,
                    field_values=row[2],
                    created_at=row[3]
                )
                for row in rows
            ]

    def get_by_type(self, project_id: str, snapshot_type: str) -> List[SnapshotRecord]:
        """
        Retrieve all snapshots of a specific type across project.
        
        RAG query method: "Show all imports", "Find all security issues"
        
        Args:
            project_id: Project identifier
            snapshot_type: One of 12 categories
        
        Returns:
            List of SnapshotRecords matching type
        """
        with db_session() as session:
            result = session.execute(
                text("""
                    SELECT snapshot_id, source_file, field_values, created_at 
                    FROM snapshot_notebooks 
                    WHERE project_id = :pid AND snapshot_type = :stype
                    ORDER BY source_file ASC
                """),
                {"pid": project_id, "stype": snapshot_type}
            )
            rows = result.fetchall()

            return [
                SnapshotRecord(
                    snapshot_id=row[0],
                    project_id=project_id,
                    snapshot_type=snapshot_type,
                    source_file=row[1],
                    field_values=row[2],
                    created_at=row[3]
                )
                for row in rows
            ]

    def delete_by_file(self, project_id: str, source_file: str) -> int:
        """
        Delete all snapshots for a file.
        
        Deletes all snapshots for this file (all categories).
        
        Args:
            project_id: Project identifier
            source_file: Source file path
        
        Returns:
            Number of snapshots deleted
        """
        with db_session() as session:
            result = session.execute(
                text("""
                    DELETE FROM snapshot_notebooks 
                    WHERE project_id = :pid AND source_file = :sf
                    RETURNING snapshot_id
                """),
                {"pid": project_id, "sf": source_file}
            )
            deleted_count = len(result.fetchall())
            
            self.logger.info("Deleted file snapshots", extra={
                "project_id": project_id,
                "source_file": source_file,
                "deleted_count": deleted_count
            })
            
            return deleted_count

    def delete_by_project(self, project_id: str) -> int:
        """
        Delete all snapshots for a project.
        
        Args:
            project_id: Project identifier
        
        Returns:
            Number of snapshots deleted
        """
        with db_session() as session:
            result = session.execute(
                text("""
                    DELETE FROM snapshot_notebooks 
                    WHERE project_id = :pid
                    RETURNING snapshot_id
                """),
                {"pid": project_id}
            )
            deleted_count = len(result.fetchall())
            
            self.logger.info("Deleted project snapshots", extra={
                "project_id": project_id,
                "deleted_count": deleted_count
            })
            
            return deleted_count
