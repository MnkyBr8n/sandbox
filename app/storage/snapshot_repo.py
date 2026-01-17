# sandbox/app/storage/snapshot_repo.py
"""
Purpose: Persist snapshot notebooks keyed by snapshot_id with idempotency protection.
Stores field values in notebook schema format: {value, sources, repeats_index}.
Handles multi vs single value fields based on master schema.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Any
from datetime import datetime
from pathlib import Path
from uuid import uuid4
import json
import yaml

from sqlalchemy import text

from app.logging.logger import get_logger
from app.storage.db import db_session, get_engine
from app.extraction.field_mapper import FieldMapResult
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
    snapshot_type: str
    source_file: str
    field_values: Dict[str, Dict[str, Any]]  # field_id -> {value, sources, repeats_index}
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
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS snapshot_notebooks (
                    snapshot_id UUID PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    snapshot_type TEXT NOT NULL,
                    source_file TEXT NOT NULL,
                    field_values JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    UNIQUE(project_id, source_file)
                )
            """))
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_snapshot_project 
                ON snapshot_notebooks(project_id, created_at)
            """))
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_snapshot_type
                ON snapshot_notebooks(snapshot_type)
            """))
            conn.commit()

    def upsert(
        self,
        project_id: str,
        snapshot_type: str,
        source_file: str,
        field_map_result: FieldMapResult,
    ) -> SnapshotRecord:
        """
        Create or update snapshot for (project_id, source_file).
        Idempotency: same source_file will not create duplicate snapshots.
        
        Args:
            project_id: unique project identifier
            snapshot_type: "code" or "text"
            source_file: source file path (used for idempotency)
            field_map_result: output from FieldMapper
        
        Returns:
            SnapshotRecord with final state
        """
        with db_session() as session:
            # Check for existing snapshot (idempotency)
            result = session.execute(
                text("""
                    SELECT snapshot_id, field_values, created_at 
                    FROM snapshot_notebooks 
                    WHERE project_id = :pid AND source_file = :sf
                """),
                {"pid": project_id, "sf": source_file}
            )
            row = result.fetchone()

            if row:
                # Existing snapshot: merge fields
                snapshot_id = row[0]
                existing = row[1]
                
                # Security logging: duplicate snapshot attempt
                self.logger.warning("Duplicate snapshot attempt", extra={
                    "project_id": project_id,
                    "source_file": source_file,
                    "existing_snapshot_id": snapshot_id,
                    "security_event": "idempotency_skip",
                    "action": "merge_fields"
                })
                
                merged = self._merge(existing, field_map_result, source_file)

                session.execute(
                    text("""
                        UPDATE snapshot_notebooks
                        SET field_values = CAST(:fv AS jsonb)
                        WHERE snapshot_id = :sid
                    """),
                    {"fv": json.dumps(merged), "sid": snapshot_id}
                )
                
                self.logger.info(f"Updated snapshot snapshot_id={snapshot_id} source={source_file}")
                created_at = row[2]
            else:
                # New snapshot: create with UUID
                snapshot_id = str(uuid4())
                field_values = self._convert_to_schema_format(field_map_result, source_file)

                session.execute(
                    text("""
                        INSERT INTO snapshot_notebooks
                        (snapshot_id, project_id, snapshot_type, source_file, field_values)
                        VALUES (:sid, :pid, :stype, :sf, CAST(:fv AS jsonb))
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

    def _convert_to_schema_format(
        self,
        field_map_result: FieldMapResult,
        source_file: str,
    ) -> Dict[str, Dict[str, Any]]:
        """
        Convert FieldMapResult to notebook schema format:
        {field_id: {value, sources, repeats_index}}
        """
        formatted: Dict[str, Dict[str, Any]] = {}

        for field_id, field_value in field_map_result.fields.items():
            config = self.field_configs.get(field_id)
            
            if config and config.multi:
                # Multi-value field: value is array
                value = [field_value.value] if not isinstance(field_value.value, list) else field_value.value
            else:
                # Single-value field: value is scalar
                value = field_value.value

            formatted[field_id] = {
                "value": value,
                "sources": [source_file],
                "repeats_index": {"references": []}
            }

        return formatted

    def _merge(
        self,
        existing: Dict[str, Dict[str, Any]],
        field_map_result: FieldMapResult,
        source_file: str,
    ) -> Dict[str, Dict[str, Any]]:
        """
        Merge incoming field_map_result into existing snapshot.
        Handles stop-on-fill for single-value fields.
        Appends to multi-value fields.
        """
        merged = {k: dict(v) for k, v in existing.items()}

        for field_id, field_value in field_map_result.fields.items():
            config = self.field_configs.get(field_id)

            if field_id not in merged:
                # New field
                if config and config.multi:
                    value = [field_value.value] if not isinstance(field_value.value, list) else field_value.value
                else:
                    value = field_value.value

                merged[field_id] = {
                    "value": value,
                    "sources": [source_file],
                    "repeats_index": {"references": []}
                }
            else:
                # Existing field
                if config and config.multi:
                    # Multi: append unique values
                    existing_values = merged[field_id]["value"]
                    new_val = field_value.value
                    
                    if new_val not in existing_values:
                        existing_values.append(new_val)
                        merged[field_id]["sources"].append(source_file)
                    else:
                        # Repeat: add to repeats_index
                        if source_file not in merged[field_id]["repeats_index"]["references"]:
                            merged[field_id]["repeats_index"]["references"].append(source_file)
                else:
                    # Single: stop-on-fill, add to repeats_index
                    if source_file not in merged[field_id]["repeats_index"]["references"]:
                        merged[field_id]["repeats_index"]["references"].append(source_file)

        return merged

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
