# sandbox/app/extraction/snapshot_builder.py
"""
Purpose: Build individual snapshots per file and assemble project notebooks.
Master schema is injected via constructor (loaded at app startup).
"""

from __future__ import annotations

from typing import Dict, List, Any
from datetime import datetime
from uuid import uuid4

from app.logging.logger import get_logger
from app.storage.snapshot_repo import SnapshotRepository, SnapshotRecord
from app.extraction.field_mapper import FieldMapResult


class SnapshotBuilderError(Exception):
    pass


class SnapshotBuilder:
    def __init__(self, master_schema: Dict[str, Any]) -> None:
        """
        Args:
            master_schema: Loaded master_notebook.yaml schema
        """
        self.master_schema = master_schema
        self.logger = get_logger("extraction.snapshot_builder")
        self.snapshot_repo = SnapshotRepository()

    def create_snapshot(
        self,
        project_id: str,
        snapshot_type: str,
        source_file: str,
        field_map_result: FieldMapResult,
    ) -> SnapshotRecord:
        """
        Create individual snapshot for parsed file.
        
        Args:
            project_id: unique project identifier
            snapshot_type: "code" or "text"
            source_file: source file path
            field_map_result: extracted fields from FieldMapper
        
        Returns:
            SnapshotRecord from snapshot_repo
        """
        if snapshot_type not in ["code", "text"]:
            raise SnapshotBuilderError(f"Invalid snapshot_type: {snapshot_type}")

        self.logger.info(f"Creating snapshot type={snapshot_type} source={source_file}")

        # Persist via snapshot_repo (generates UUID, enforces idempotency)
        snapshot_record = self.snapshot_repo.upsert(
            project_id=project_id,
            snapshot_type=snapshot_type,
            source_file=source_file,
            field_map_result=field_map_result,
        )

        self.logger.info(f"Created snapshot snapshot_id={snapshot_record.snapshot_id}")
        return snapshot_record

    def assemble_project_notebook(
        self,
        project_id: str,
        snapshot_type: str,
    ) -> Dict[str, Any]:
        """
        Assemble consolidated project notebook from all snapshots.
        Combines all snapshots for project into single notebook structure.
        
        Args:
            project_id: unique project identifier
            snapshot_type: "code" or "text"
        
        Returns:
            Complete project notebook JSON matching master schema format
        """
        self.logger.info(f"Assembling project notebook project_id={project_id} type={snapshot_type}")

        # Retrieve all snapshots for project
        all_snapshots = self.snapshot_repo.get_by_project(project_id)
        
        # Filter by snapshot_type
        snapshots = [s for s in all_snapshots if s.snapshot_type == snapshot_type]

        if not snapshots:
            self.logger.warning(f"No snapshots found for project_id={project_id} type={snapshot_type}")

        # Get field registry for snapshot_type from master schema
        field_registry = self._get_field_registry(snapshot_type)

        # Initialize notebook structure
        notebook = self._init_notebook_structure(project_id, snapshot_type, field_registry)

        # Merge all snapshot field_values into notebook
        for snapshot in snapshots:
            self._merge_snapshot_into_notebook(notebook, snapshot, field_registry)

        # Calculate coverage
        self._calculate_coverage(notebook, field_registry)
        
        # Snapshot accounting
        all_project_snapshots = self.snapshot_repo.get_by_project(project_id)
        total_snapshots = len(all_project_snapshots)
        type_snapshots = len(snapshots)
        
        self.logger.info("Snapshot accounting", extra={
            "project_id": project_id,
            "snapshot_type": snapshot_type,
            "snapshots_assembled": type_snapshots,
            "snapshots_total_project": total_snapshots,
            "filled_fields": len(notebook['coverage']['filled_field_ids']),
            "missing_fields": len(notebook['coverage']['missing_field_ids'])
        })

        self.logger.info(
            f"Assembled project notebook project_id={project_id} "
            f"snapshots={len(snapshots)} "
            f"filled_fields={len(notebook['coverage']['filled_field_ids'])}"
        )

        return notebook

    def _get_field_registry(self, snapshot_type: str) -> List[Dict[str, Any]]:
        """Get field definitions for snapshot_type from master schema."""
        field_id_registry = self.master_schema.get("field_id_registry", {})
        return field_id_registry.get(snapshot_type, [])

    def _init_notebook_structure(
        self,
        project_id: str,
        snapshot_type: str,
        field_registry: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Initialize empty notebook structure matching master schema template."""
        notebook = {
            "meta": {
                "project_id": project_id,
                "snapshot_type": snapshot_type,
                "schema_id": self.master_schema.get("schema_id", "notebook_schema_v1"),
                "snapshot_id": str(uuid4()),
                "created_at": datetime.utcnow().isoformat() + "Z",
                "artifacts": {
                    "code_intel_enabled": False,
                    "text_intel_enabled": False,
                    "connections_enabled": False,
                }
            },
            "fields": {},
            "coverage": {
                "filled_field_ids": [],
                "missing_field_ids": []
            }
        }

        # Initialize all fields from registry
        for field_def in field_registry:
            field_id = field_def["field_id"]
            value_type = field_def["value_type"]
            multi = field_def["multi"]

            # Set default value based on type and multi flag
            if multi or value_type == "string_list":
                default_value = []
            else:
                default_value = None

            notebook["fields"][field_id] = {
                "value": default_value,
                "sources": [],
                "repeats_index": {"references": []}
            }

        # Add artifact sections based on snapshot_type
        if snapshot_type == "code":
            notebook["code_intel"] = {"parser_runs": []}
        elif snapshot_type == "text":
            notebook["text_intel"] = {"extractor_runs": []}

        return notebook

    def _merge_snapshot_into_notebook(
        self,
        notebook: Dict[str, Any],
        snapshot: SnapshotRecord,
        field_registry: List[Dict[str, Any]],
    ) -> None:
        """Merge snapshot field_values into notebook fields."""
        for field_id, field_data in snapshot.field_values.items():
            if field_id not in notebook["fields"]:
                # Unknown field_id (shouldn't happen if validation correct)
                self.logger.warning(f"Unknown field_id in snapshot: {field_id}")
                continue

            notebook_field = notebook["fields"][field_id]
            snapshot_value = field_data.get("value")
            snapshot_sources = field_data.get("sources", [])
            snapshot_repeats = field_data.get("repeats_index", {}).get("references", [])

            # Find field config
            field_config = next((f for f in field_registry if f["field_id"] == field_id), None)
            if not field_config:
                continue

            multi = field_config.get("multi", False)

            if multi:
                # Multi-value: merge arrays
                if isinstance(snapshot_value, list):
                    for val in snapshot_value:
                        if val not in notebook_field["value"]:
                            notebook_field["value"].append(val)
                
                # Merge sources
                for src in snapshot_sources:
                    if src not in notebook_field["sources"]:
                        notebook_field["sources"].append(src)
                
                # Merge repeats
                for ref in snapshot_repeats:
                    if ref not in notebook_field["repeats_index"]["references"]:
                        notebook_field["repeats_index"]["references"].append(ref)
            else:
                # Single-value: stop-on-fill
                if notebook_field["value"] is None and snapshot_value is not None:
                    # First fill
                    notebook_field["value"] = snapshot_value
                    notebook_field["sources"] = snapshot_sources.copy()
                else:
                    # Already filled: add to repeats
                    for ref in snapshot_repeats:
                        if ref not in notebook_field["repeats_index"]["references"]:
                            notebook_field["repeats_index"]["references"].append(ref)

    def _calculate_coverage(
        self,
        notebook: Dict[str, Any],
        field_registry: List[Dict[str, Any]],
    ) -> None:
        """Calculate filled vs missing field_ids."""
        filled = []
        missing = []

        for field_def in field_registry:
            field_id = field_def["field_id"]
            field_data = notebook["fields"].get(field_id, {})
            value = field_data.get("value")

            # Check if filled
            if value is not None:
                if isinstance(value, list):
                    # List: filled if non-empty
                    if len(value) > 0:
                        filled.append(field_id)
                    else:
                        missing.append(field_id)
                else:
                    # Scalar: filled if not None
                    filled.append(field_id)
            else:
                missing.append(field_id)

        notebook["coverage"]["filled_field_ids"] = filled
        notebook["coverage"]["missing_field_ids"] = missing
