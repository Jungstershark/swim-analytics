"""
Base parser interface for swim meet result files.

All format-specific parsers (HY-TEK, Omega, etc.) implement this interface.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from .hytek import ConfidenceReport, ParsedMeet


@dataclass(frozen=True)
class DetectionResult:
    """One parser's read-only opinion about a file format.

    Format detection is intentionally separate from parsing. This lets us add
    future parser/model families without weakening the current HY-TEK parser:
    every candidate can sniff the document, explain why it matches, and report a
    confidence score before the registry chooses the best parser.
    """

    parser: "ResultParser"
    format_name: str
    parser_version: str
    confidence: int
    reason: str
    can_parse: bool = True


class ResultParser(ABC):
    """Abstract base class for swim meet result parsers."""

    @property
    @abstractmethod
    def format_name(self) -> str:
        """Short identifier for this parser format (e.g., 'hytek', 'omega')."""
        ...

    @property
    def parser_version(self) -> str:
        """Version identifier stored in ParseJob/Result provenance."""
        return f"{self.format_name}-v1"

    def sniff(self, file_path: Path) -> DetectionResult:
        """Return this parser's read-only format-detection opinion.

        Existing parsers may only implement `can_parse`; this default keeps that
        behavior working while enabling future parsers to return richer scores
        and reasons.
        """
        can_parse = self.can_parse(file_path)
        return DetectionResult(
            parser=self,
            format_name=self.format_name,
            parser_version=self.parser_version,
            confidence=100 if can_parse else 0,
            reason="legacy can_parse match" if can_parse else "legacy can_parse did not match",
            can_parse=can_parse,
        )

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


def detect_parser(file_path: Path, parsers: list[ResultParser] | None = None) -> DetectionResult:
    """Choose the best parser for a file using explicit format detection.

    This is the extension seam for supporting multiple document formats. Future
    parsers should override `sniff()` with cheap first-page/content checks and a
    confidence score. The registry picks the highest-confidence parseable
    candidate instead of assuming one parser can safely handle every document.
    """
    candidates = parsers or PARSERS
    detections = [parser.sniff(file_path) for parser in candidates]
    parseable = [detection for detection in detections if detection.can_parse and detection.confidence > 0]
    if not parseable:
        names = ", ".join(detection.format_name for detection in detections) or "none"
        raise ValueError(f"No parser found for file: {file_path.name}; checked: {names}")
    return max(parseable, key=lambda detection: detection.confidence)


def detect_and_parse(file_path: Path) -> tuple[ParsedMeet, ConfidenceReport, str]:
    """
    Auto-detect format and parse.

    Returns:
        Tuple of (ParsedMeet, ConfidenceReport, parser_format_name).

    Raises:
        ValueError if no parser can handle the file.
    """
    detection = detect_parser(file_path)
    meet, confidence = detection.parser.parse(file_path)
    return meet, confidence, detection.format_name
