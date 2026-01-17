# sandbox/app/extraction/field_mapper.py
"""
Purpose: Map parsed content into notebook field_id targets.

Rules enforced:
- Only collect content that matches known field_id definitions
- Stop-on-fill: once a field_id has a canonical value, do not overwrite it
- Repeats are indexed, not duplicated
- Unknown fields are skipped
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any

from app.logging.logger import get_logger


class FieldMappingError(Exception):
    pass


@dataclass
class FieldIndex:
    """Tracks repeat references without duplicating content."""
    references: List[str] = field(default_factory=list)


@dataclass
class FieldValue:
    """Canonical field value with optional index of repeats."""
    value: Any
    index: Optional[FieldIndex] = None


@dataclass
class FieldMapResult:
    """Resulting field map keyed by field_id."""
    fields: Dict[str, FieldValue]


class FieldMapper:
    def __init__(self, *, allowed_field_ids: List[str]) -> None:
        self.allowed_field_ids = set(allowed_field_ids)
        self.logger = get_logger("extraction.field_mapper")

    def map_fields(
        self,
        parsed_records: List[Dict[str, Any]],
        *,
        source_id: str,
    ) -> FieldMapResult:
        """
        parsed_records:
          Each record must include:
            - field_id
            - value

        source_id:
          Identifier of the source record (file path, page id, etc.)
        """
        field_map: Dict[str, FieldValue] = {}

        for record in parsed_records:
            field_id = record.get("field_id")
            value = record.get("value")

            if field_id not in self.allowed_field_ids:
                self.logger.debug(f"Skipping unknown field_id: {field_id}")
                continue

            if field_id not in field_map:
                # First fill wins
                field_map[field_id] = FieldValue(value=value)
                self.logger.debug(f"Filled field_id={field_id} from {source_id}")
                continue

            # Already filled: index repeat
            fv = field_map[field_id]
            if fv.index is None:
                fv.index = FieldIndex()

            fv.index.references.append(source_id)
            self.logger.debug(
                f"Indexed repeat for field_id={field_id} from {source_id}"
            )

        return FieldMapResult(fields=field_map)