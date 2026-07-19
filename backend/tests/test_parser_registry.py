from pathlib import Path

import pytest

from app.parsers.base import DetectionResult, ResultParser, detect_parser


class FakeParser(ResultParser):
    def __init__(self, name: str, confidence: int, can_parse: bool = True):
        self._name = name
        self._confidence = confidence
        self._can_parse = can_parse

    @property
    def format_name(self) -> str:
        return self._name

    @property
    def parser_version(self) -> str:
        return f"{self._name}-v1"

    def sniff(self, file_path: Path) -> DetectionResult:
        return DetectionResult(
            parser=self,
            format_name=self.format_name,
            parser_version=self.parser_version,
            confidence=self._confidence if self._can_parse else 0,
            reason="test parser",
            can_parse=self._can_parse,
        )

    def can_parse(self, file_path: Path) -> bool:
        return self._can_parse

    def parse(self, file_path: Path):  # pragma: no cover - selection tests do not parse
        raise NotImplementedError


def test_detect_parser_selects_highest_confidence_candidate(tmp_path):
    pdf = tmp_path / "result.pdf"
    pdf.write_bytes(b"fake pdf")

    selected = detect_parser(
        pdf,
        parsers=[
            FakeParser("legacy-hytek", confidence=65),
            FakeParser("new-format", confidence=92),
            FakeParser("not-applicable", confidence=99, can_parse=False),
        ],
    )

    assert selected.format_name == "new-format"
    assert selected.parser_version == "new-format-v1"
    assert selected.confidence == 92
    assert selected.can_parse is True


def test_detect_parser_reports_all_failed_candidates(tmp_path):
    pdf = tmp_path / "unknown.pdf"
    pdf.write_bytes(b"unknown")

    with pytest.raises(ValueError) as excinfo:
        detect_parser(
            pdf,
            parsers=[
                FakeParser("hytek", confidence=0, can_parse=False),
                FakeParser("omega", confidence=0, can_parse=False),
            ],
        )

    message = str(excinfo.value)
    assert "No parser found" in message
    assert "hytek" in message
    assert "omega" in message
