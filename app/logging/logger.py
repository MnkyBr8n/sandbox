# sandbox/app/logging/logger.py
"""
Purpose: Centralized structured logging for sandbox services.

Enhanced logging for multi-snapshot architecture:
- File categorization tags (normal, large, potential_god, rejected)
- Snapshot counts per file and per repo
- Snapshot type (one of 12 categories)  
- Parser tracking (tree_sitter, semgrep, text_extractor, csv_parser)
"""

from __future__ import annotations

import logging
import sys
import json
from typing import Optional, Dict, Any

from app.config.settings import get_settings


class StructuredFormatter(logging.Formatter):
    """Custom formatter that handles structured logging with extra fields."""
    
    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "ts": self.formatTime(record),
            "level": record.levelname,
            "name": record.name,
            "msg": record.getMessage()
        }
        
        if hasattr(record, 'extra_fields'):
            log_data.update(record.extra_fields)
        
        return json.dumps(log_data)


class StructuredLoggerAdapter(logging.LoggerAdapter):
    """Logger adapter that adds structured fields to log records."""
    
    def process(self, msg, kwargs):
        extra = kwargs.get('extra', {})
        
        if 'extra' not in kwargs:
            kwargs['extra'] = {}
        
        kwargs['extra']['extra_fields'] = extra
        
        return msg, kwargs


def _build_handler(json_logs: bool) -> logging.Handler:
    handler = logging.StreamHandler(sys.stdout)

    if json_logs:
        handler.setFormatter(StructuredFormatter())
    else:
        formatter = logging.Formatter(
            fmt="%(asctime)s %(levelname)s %(name)s %(message)s"
        )
        handler.setFormatter(formatter)

    return handler


def get_logger(name: str = "snap") -> StructuredLoggerAdapter:
    """
    Get or create logger with given name.
    
    Returns logger adapter with structured logging support.
    """
    settings = get_settings()
    
    base_logger = logging.getLogger(name)
    base_logger.setLevel(settings.log_level.upper())
    base_logger.propagate = False
    
    if not base_logger.handlers:
        base_logger.addHandler(_build_handler(settings.log_json))
    
    return StructuredLoggerAdapter(base_logger, {})


def log_file_parsed(
    logger: StructuredLoggerAdapter,
    path: str,
    tag: str,
    size: int,
    language: str,
    project_id: str,
    parse_duration_ms: float,
    snapshots_created: int,
    snapshot_types: list,
    snapshot_ids: list,
    parsers: list
) -> None:
    """Standard log format for file parsing events."""
    logger.info("File parsed", extra={
        "path": path,
        "file": path.split('/')[-1],
        "tag": tag,
        "size": size,
        "language": language,
        "project_id": project_id,
        "parse_duration_ms": parse_duration_ms,
        "snapshots_created": snapshots_created,
        "snapshot_types": snapshot_types,
        "snapshot_ids": snapshot_ids,
        "parsers": parsers
    })


def log_snapshot_created(
    logger: StructuredLoggerAdapter,
    snapshot_id: str,
    project_id: str,
    file_path: str,
    snapshot_type: str,
    parser: str,
    fields_count: int
) -> None:
    """Standard log format for snapshot creation events."""
    logger.info("Snapshot created", extra={
        "snapshot_id": snapshot_id,
        "project_id": project_id,
        "file_path": file_path,
        "snapshot_type": snapshot_type,
        "parser": parser,
        "fields_count": fields_count
    })


def log_repo_complete(
    logger: StructuredLoggerAdapter,
    project_id: str,
    files_processed: int,
    files_attempted: int,
    snapshots_created: int,
    snapshots_attempted: int,
    snapshots_failed: int,
    snapshots_rejected: int,
    snapshot_types_summary: Dict[str, int],
    parsers_summary: Dict[str, int],
    total_duration_ms: float
) -> None:
    """Standard log format for repo processing completion."""
    logger.info("Repo processing complete", extra={
        "project_id": project_id,
        "files_attempted": files_attempted,
        "files_processed": files_processed,
        "files_failed": files_attempted - files_processed,
        "snapshots_attempted": snapshots_attempted,
        "snapshots_created": snapshots_created,
        "snapshots_failed": snapshots_failed,
        "snapshots_rejected": snapshots_rejected,
        "snapshot_types_summary": snapshot_types_summary,
        "parsers_summary": parsers_summary,
        "total_duration_ms": total_duration_ms
    })


def log_file_categorization(
    logger: StructuredLoggerAdapter,
    path: str,
    size: int,
    tag: str,
    reason: Optional[str] = None
) -> None:
    """Log file size categorization."""
    level = logging.INFO
    if tag == "large":
        level = logging.WARNING
    elif tag == "potential_god":
        level = logging.WARNING
    elif tag == "rejected":
        level = logging.ERROR
    
    logger.log(level, f"File categorized: {tag}", extra={
        "path": path,
        "size": size,
        "tag": tag,
        "reason": reason
    })
