"""
Base parser interface for swim meet result files.

All format-specific parsers (HY-TEK, Omega, etc.) implement this interface.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from .hytek import ConfidenceReport, ParsedMeet


class ResultParser(ABC):
    """Abstract base class for swim meet result parsers."""

    @property
    @abstractmethod
    def format_name(self) -> str:
        """Short identifier for this parser format (e.g., 'hytek', 'omega')."""
        ...

    @abstractmethod
    def can_parse(self, file_path: Path) -> bool:
        """
        Sniff the file to determine if this parser can handle it.
        Should be fast — read first page only.
        """
        ...

    @abstractmethod
    def parse(self, file_path: Path) -> tuple[ParsedMeet, ConfidenceReport]:
        """
        Parse the file and return structured data with confidence score.
        """
        ...


class HyTekParser(ResultParser):
    """HY-TEK Meet Manager 8.0 PDF parser."""

    @property
    def format_name(self) -> str:
        return "hytek"

    def can_parse(self, file_path: Path) -> bool:
        if not str(file_path).lower().endswith(".pdf"):
            return False
        try:
            import pdfplumber
            with pdfplumber.open(file_path) as pdf:
                if not pdf.pages:
                    return False
                text = pdf.pages[0].extract_text() or ""
                return "HY-TEK" in text or "MEET MANAGER" in text
        except Exception:
            return False

    def parse(self, file_path: Path) -> tuple[ParsedMeet, ConfidenceReport]:
        from .hytek import parse_hytek_pdf
        return parse_hytek_pdf(file_path)


# Registry of available parsers (order matters — first match wins)
PARSERS: list[ResultParser] = [
    HyTekParser(),
]


def detect_and_parse(file_path: Path) -> tuple[ParsedMeet, ConfidenceReport, str]:
    """
    Auto-detect format and parse.

    Returns:
        Tuple of (ParsedMeet, ConfidenceReport, parser_format_name).

    Raises:
        ValueError if no parser can handle the file.
    """
    for parser in PARSERS:
        if parser.can_parse(file_path):
            meet, confidence = parser.parse(file_path)
            return meet, confidence, parser.format_name
    raise ValueError(f"No parser found for file: {file_path.name}")
