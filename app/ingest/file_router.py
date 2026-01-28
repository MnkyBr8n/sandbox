# sandbox/app/ingest/file_router.py
"""
Purpose: Route ingested files to appropriate parsers based on file type.

Routing strategy:
- Code files (.py, .ts, .js, etc.) → tree_sitter + semgrep
- Text files (.pdf, .md, .txt, etc.) → text_extractor
- CSV files (.csv) → csv_parser
- Unknown files → skipped

Returns mapping of file → list of parsers to run.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Set
from dataclasses import dataclass

from app.logging.logger import get_logger

logger = get_logger("ingest.router")


class FileRoutingError(Exception):
    pass


@dataclass
class FileRoute:
    """Route decision for a single file."""
    path: Path
    parsers: List[str]  # Parser names: tree_sitter, semgrep, text_extractor, csv_parser
    snapshot_type: str  # "code" or "text"
    language: str       # File extension without dot


# Supported file types by category
CODE_EXTENSIONS = {
    ".py", ".ts", ".tsx", ".js", ".jsx", 
    ".java", ".go", ".rs", ".cpp", ".c", 
    ".cs", ".rb", ".php", ".swift", ".kt", ".scala"
}

TEXT_EXTENSIONS = {
    ".pdf", ".txt", ".md", ".docx", ".html", ".rtf"
}

CSV_EXTENSIONS = {
    ".csv", ".tsv"
}


def route_file(path: Path) -> FileRoute | None:
    """
    Determine parsers for a single file.
    
    Args:
        path: File path
    
    Returns:
        FileRoute with parsers to run, or None if file type not supported
    """
    suffix = path.suffix.lower()
    
    if suffix in CODE_EXTENSIONS:
        # Code files: tree_sitter + semgrep
        return FileRoute(
            path=path,
            parsers=["tree_sitter", "semgrep"],
            snapshot_type="code",
            language=suffix.lstrip('.')
        )
    
    elif suffix in TEXT_EXTENSIONS:
        # Text files: text_extractor only
        return FileRoute(
            path=path,
            parsers=["text_extractor"],
            snapshot_type="text",
            language=suffix.lstrip('.')
        )
    
    elif suffix in CSV_EXTENSIONS:
        # CSV files: csv_parser only
        return FileRoute(
            path=path,
            parsers=["csv_parser"],
            snapshot_type="code",  # CSV treated as structured code data
            language=suffix.lstrip('.')
        )
    
    else:
        # Unknown file type
        logger.debug(f"No parser for file type: {path}")
        return None


def route_files(files: List[Path]) -> List[FileRoute]:
    """
    Route multiple files to their parsers.
    
    Args:
        files: List of file paths
    
    Returns:
        List of FileRoute objects (excludes unsupported files)
    """
    routes = []
    skipped = 0
    
    for path in files:
        route = route_file(path)
        if route:
            routes.append(route)
        else:
            skipped += 1
    
    # Log routing summary
    parser_counts = {}
    for route in routes:
        for parser in route.parsers:
            parser_counts[parser] = parser_counts.get(parser, 0) + 1
    
    logger.info("File routing complete", extra={
        "total_files": len(files),
        "routed_files": len(routes),
        "skipped_files": skipped,
        "parser_assignments": parser_counts
    })
    
    return routes


def get_supported_extensions() -> Dict[str, Set[str]]:
    """
    Get all supported file extensions by category.
    
    Returns:
        Dict mapping category to set of extensions
    """
    return {
        "code": CODE_EXTENSIONS,
        "text": TEXT_EXTENSIONS,
        "csv": CSV_EXTENSIONS
    }


def is_supported_file(path: Path) -> bool:
    """
    Check if file type is supported.
    
    Args:
        path: File path
    
    Returns:
        True if file type supported, False otherwise
    """
    suffix = path.suffix.lower()
    return suffix in CODE_EXTENSIONS or suffix in TEXT_EXTENSIONS or suffix in CSV_EXTENSIONS
