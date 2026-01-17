# sandbox/app/parsers/csv_parser.py
"""
Purpose: Parse CSV files into normalized records.
Does not infer schema beyond header and row values.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import List, Dict

from app.logging.logger import get_logger
from app.security.sandbox_limits import SandboxLimitsEnforcer, SandboxLimitError


class CsvParseError(Exception):
    pass


@dataclass(frozen=True)
class CsvParseResult:
    path: str
    headers: List[str]
    rows: List[Dict[str, str]]
    row_count: int


def parse_csv(path: Path) -> CsvParseResult:
    logger = get_logger("parser.csv")
    limits = SandboxLimitsEnforcer()

    if not path.exists() or not path.is_file():
        raise CsvParseError("CSV path does not exist or is not a file")

    try:
        limits.check_file_size(path)
    except SandboxLimitError as exc:
        raise CsvParseError(str(exc)) from exc

    rows: List[Dict[str, str]] = []

    try:
        with path.open("r", encoding="utf-8", errors="replace", newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                raise CsvParseError("CSV has no headers")

            headers = [h.strip() for h in reader.fieldnames]

            for idx, row in enumerate(reader):
                if idx >= limits.limits.max_csv_rows_per_file:
                    break

                normalized = {
                    k.strip(): (v.strip() if isinstance(v, str) else "")
                    for k, v in row.items()
                    if k is not None
                }
                rows.append(normalized)

    except CsvParseError:
        raise
    except Exception as exc:
        raise CsvParseError("Failed to parse CSV") from exc

    logger.info(
        f"Parsed CSV {path} rows={len(rows)} columns={len(headers)}"
    )

    return CsvParseResult(
        path=str(path),
        headers=headers,
        rows=rows,
        row_count=len(rows),
    )