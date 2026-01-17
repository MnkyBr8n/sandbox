# sandbox/app/parsers/text_parser.py
"""
Purpose: Parse txt/json/yaml files into normalized text records.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from app.logging.logger import get_logger
from app.security.sandbox_limits import SandboxLimitsEnforcer, SandboxLimitError

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover
    yaml = None  # type: ignore


class TextParseError(Exception):
    pass


@dataclass(frozen=True)
class TextParseResult:
    path: str
    kind: str  # "txt" | "json" | "yaml"
    text: str


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        raise TextParseError("Failed to read text file") from exc


def _normalize_json(raw: str) -> str:
    try:
        obj = json.loads(raw)
    except Exception as exc:
        raise TextParseError("Invalid JSON") from exc
    return json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False)


def _normalize_yaml(raw: str) -> str:
    if yaml is None:
        raise TextParseError("pyyaml is not available")

    try:
        obj = yaml.safe_load(raw)
    except Exception as exc:
        raise TextParseError("Invalid YAML") from exc

    # Normalize to YAML with stable formatting
    try:
        return yaml.safe_dump(obj, sort_keys=True, allow_unicode=True)
    except Exception as exc:
        raise TextParseError("Failed to normalize YAML") from exc


def parse_text_like(path: Path) -> TextParseResult:
    logger = get_logger("parser.text")
    limits = SandboxLimitsEnforcer()

    if not path.exists() or not path.is_file():
        raise TextParseError("Path does not exist or is not a file")

    try:
        limits.check_file_size(path)
    except SandboxLimitError as exc:
        raise TextParseError(str(exc)) from exc

    suffix = path.suffix.lower()
    raw = _read_text(path)

    if suffix == ".txt":
        kind = "txt"
        text = raw.strip()

    elif suffix == ".md":
        kind = "markdown"
        text = raw.strip()

    elif suffix in {".html", ".htm"}:
        kind = "html"
        text = raw.strip()

    elif suffix == ".json":
        kind = "json"
        text = _normalize_json(raw).strip()

    elif suffix in {".yaml", ".yml"}:
        kind = "yaml"
        text = _normalize_yaml(raw).strip()

    else:
        raise TextParseError("Unsupported text-like file type")

    logger.info(f"Parsed {kind} {path} text_chars={len(text)}")
    return TextParseResult(path=str(path), kind=kind, text=text)