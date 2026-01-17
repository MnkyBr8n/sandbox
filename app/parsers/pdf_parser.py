# sandbox/app/parsers/pdf_parser.py
"""
Purpose: Parse PDF files into normalized text records.
Images are only recorded as: has_images (bool) and image_count (int). No image details stored.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from app.logging.logger import get_logger
from app.security.sandbox_limits import SandboxLimitsEnforcer, SandboxLimitError

try:
    from pypdf import PdfReader  # type: ignore
except Exception:  # pragma: no cover
    PdfReader = None  # type: ignore


class PdfParseError(Exception):
    pass


@dataclass(frozen=True)
class PdfParseResult:
    path: str
    page_count: int
    has_images: bool
    image_count: int
    text: str


def _count_images_in_page(page) -> int:
    """
    Best effort count of image XObjects on a page.
    Does not extract or store images.
    """
    try:
        resources = page.get("/Resources") or {}
        xobj = resources.get("/XObject") or {}
        count = 0
        for _, obj in xobj.items():
            try:
                o = obj.get_object()
                if o.get("/Subtype") == "/Image":
                    count += 1
            except Exception:
                continue
        return count
    except Exception:
        return 0


def parse_pdf(path: Path) -> PdfParseResult:
    logger = get_logger("parser.pdf")
    limits = SandboxLimitsEnforcer()

    if PdfReader is None:
        raise PdfParseError("pypdf is not available")

    if not path.exists() or not path.is_file():
        raise PdfParseError("PDF path does not exist or is not a file")

    try:
        limits.check_file_size(path)
    except SandboxLimitError as exc:
        raise PdfParseError(str(exc)) from exc

    try:
        reader = PdfReader(str(path))
    except Exception as exc:
        raise PdfParseError("Failed to open PDF") from exc

    page_count = len(reader.pages)
    if page_count > limits.limits.max_pdf_pages_per_file:
        raise PdfParseError("PDF exceeds max page limit")

    text_parts: List[str] = []
    total_images = 0

    for i, page in enumerate(reader.pages):
        if i + 1 > limits.limits.max_pdf_pages_per_job:
            break

        try:
            page_text = page.extract_text() or ""
        except Exception:
            page_text = ""

        if page_text.strip():
            text_parts.append(page_text)

        total_images += _count_images_in_page(page)

    has_images = total_images > 0

    logger.info(
        f"Parsed PDF {path} pages={page_count} images={total_images} text_chars={sum(len(t) for t in text_parts)}"
    )

    return PdfParseResult(
        path=str(path),
        page_count=page_count,
        has_images=has_images,
        image_count=total_images,
        text="\n".join(text_parts).strip(),
    )