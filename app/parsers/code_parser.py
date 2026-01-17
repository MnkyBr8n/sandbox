# sandbox/app/parsers/code_parser.py
"""
Purpose: Parse code files into normalized text records with basic metadata.
Does not execute code or infer semantics beyond light metadata.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from app.logging.logger import get_logger
from app.security.sandbox_limits import SandboxLimitsEnforcer, SandboxLimitError


class CodeParseError(Exception):
    pass


@dataclass(frozen=True)
class CodeParseResult:
    path: str
    language: str
    text: str


_SUFFIX_TO_LANG: dict[str, str] = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".md": "markdown",
    ".sql": "sql",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".hpp": "cpp",
    ".cs": "csharp",
    ".php": "php",
    ".rb": "ruby",
    ".sh": "shell",
    ".ps1": "powershell",
    ".toml": "toml",
    ".ini": "ini",
    ".cfg": "ini",
    ".dockerfile": "dockerfile",
}


def _detect_language(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in _SUFFIX_TO_LANG:
        return _SUFFIX_TO_LANG[suffix]

    # Handle "Dockerfile" with no suffix
    if path.name.lower() == "dockerfile":
        return "dockerfile"

    return "UNKNOWN"


def parse_code(path: Path) -> CodeParseResult:
    logger = get_logger("parser.code")
    limits = SandboxLimitsEnforcer()

    if not path.exists() or not path.is_file():
        raise CodeParseError("Code path does not exist or is not a file")

    try:
        limits.check_file_size(path)
    except SandboxLimitError as exc:
        raise CodeParseError(str(exc)) from exc

    try:
        text = path.read_text(encoding="utf-8", errors="replace").strip()
    except Exception as exc:
        raise CodeParseError("Failed to read code file") from exc

    language = _detect_language(path)

    logger.info(f"Parsed code {path} lang={language} text_chars={len(text)}")

    return CodeParseResult(path=str(path), language=language, text=text)