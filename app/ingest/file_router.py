# sandbox/app/ingest/file_router.py
"""
Purpose: Route ingested files to the appropriate parser based on file type.
Only routes files that are allowed and within sandbox limits.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Type

from app.logging.logger import get_logger


class FileRoutingError(Exception):
    pass


class BaseParser:
    """Interface contract for all parsers."""

    supported_suffixes: set[str] = set()

    def parse(self, path: Path) -> None:
        raise NotImplementedError


def route_file(file_path: Path) -> str:
    """
    Determine file type by extension.

    Returns the file extension (suffix) or "skip" if unknown.
    """
    supported_suffixes = {
        # Text/docs
        ".pdf", ".txt", ".md", ".html", ".htm",
        # Data
        ".csv", ".json", ".yaml", ".yml",
        # Code
        ".py", ".js", ".ts", ".go", ".rs", ".java", ".c", ".cpp", ".rb", ".cs",
    }
    suffix = file_path.suffix.lower()

    if suffix in supported_suffixes:
        return suffix.lstrip(".")

    return "skip"


def route_files(
    files: List[Path],
    parsers: List[BaseParser],
) -> Dict[str, List[Path]]:
    """
    Route files to parsers by file suffix.

    Returns a mapping of parser name -> list of files.
    """
    logger = get_logger("ingest.router")

    routing: Dict[str, List[Path]] = {}
    parser_map: Dict[str, BaseParser] = {}

    for parser in parsers:
        for suffix in parser.supported_suffixes:
            parser_map[suffix.lower()] = parser

    for path in files:
        suffix = path.suffix.lower()
        parser = parser_map.get(suffix)

        if parser is None:
            logger.debug(f"No parser for file type: {path}")
            continue

        key = parser.__class__.__name__
        routing.setdefault(key, []).append(path)

    logger.info(
        f"Routed {sum(len(v) for v in routing.values())} files "
        f"to {len(routing)} parsers"
    )

    return routing