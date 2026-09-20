"""
HY-TEK Meet Manager PDF Parser

Parses HY-TEK Meet Manager 8.0 result PDFs into structured data.
Handles: prelims, finals, splits, reaction times, DQ/NS/NT, tied placements,
guest swimmers, qualification markers (qMTS/MTS), and all age groups.
"""

from __future__ import annotations

import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime
from functools import wraps
from pathlib import Path
from typing import Optional, Sequence

import pdfplumber


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class Split:
    """A single split/lap within a result."""
    cumulative_time: str          # e.g. "1:05.33"
    split_time: Optional[str]     # e.g. "35.79" (the delta), None for first split
    distance: Optional[int] = None  # e.g. 50, 100, 150 ... (set post-parse)


@dataclass
class ParsedResult:
    """One swimmer's result in an event."""
    placement: Optional[int]       # None if DQ/NS/DNF/DNS
    is_tied: bool                  # True if placement was tied (e.g. *116)
    name: str                      # e.g. "WU, Dylan Jiaxu"
    is_guest: bool                 # True if name prefixed with * (foreign/guest)
    age: Optional[int]
    team: str
    seed_time: Optional[str]       # "2:19.50", "NT", None
    finals_time: Optional[str]     # "2:18.62", None if DQ/NS
    time_type: str                 # "Prelim Time" or "Finals Time"
    is_dq: bool
    dq_code: Optional[str]         # e.g. "SW 7.4c"
    dq_description: Optional[str]  # e.g. "Hands brought back beyond the hip line..."
    is_ns: bool                    # No Show
    qualifier: Optional[str]       # "qMTS", "MTS", or None
    reaction_time: Optional[str]   # e.g. "+0.66"
    is_exhibition: bool = False    # Valid times prefixed with X
    splits: list[Split] = field(default_factory=list)
    status: str = "unknown"        # finished, dq, ns, dns, dnf, scratched, unknown
    raw_outcome: Optional[str] = None  # exact HY-TEK time/status token


@dataclass
class ParsedEvent:
    """One event block (e.g. Boys 13-14 200 LC Meter IM)."""
    event_number: str              # e.g. "101"
    event_name: str                # e.g. "Boys 13-14 200 LC Meter IM"
    gender: Optional[str]          # "Boys", "Girls", "Men", "Women"
    age_group: Optional[str]       # "13-14", "15-17", "18 & Over", "11 Year Olds"
    distance: Optional[int]        # 50, 100, 200, 400, 800, 1500
    stroke: Optional[str]          # "IM", "Freestyle", "Backstroke", etc.
    course: str                    # "LC" or "SC"
    time_standard: Optional[str]   # e.g. "2:47.17"
    time_type: str                 # "Prelim Time" or "Finals Time"
    is_relay: bool = False
    results: list[ParsedResult] = field(default_factory=list)
    relay_results: list["ParsedRelayResult"] = field(default_factory=list)
    relay_count: Optional[int] = None
    leg_distance: Optional[int] = None


@dataclass
class ParsedRelayLeg:
    """One leg within a relay result."""
    leg_number: int                # 1-4
    name: str
    is_guest: bool
    age: Optional[int]
    gender: Optional[str] = None   # "M" or "W" (mixed relays: "W8", "M10")
    reaction_time: Optional[str] = None  # Exchange RT
    split_time: Optional[str] = None     # Computed total leg time
    splits: list[Split] = field(default_factory=list)  # Per-swimmer lap splits


@dataclass
class ParsedRelayResult:
    """One team's relay result."""
    team_name: str                 # e.g. "Olympians Swimming (Can)"
    relay_letter: Optional[str]    # "A", "B", "C", etc.
    placement: Optional[int]
    seed_time: Optional[str]
    finals_time: Optional[str]
    time_type: str                 # "Prelim Time" or "Finals Time"
    is_dq: bool
    dq_code: Optional[str] = None
    dq_description: Optional[str] = None
    is_exhibition: bool = False    # Times prefixed with X
    reaction_time: Optional[str] = None
    splits: list[Split] = field(default_factory=list)
    legs: list[ParsedRelayLeg] = field(default_factory=list)
    leg_parse_status: str = "complete"
    leg_parse_warning: Optional[str] = None
    status: str = "unknown"        # finished, dq, ns, dns, dnf, scratched, unknown
    is_judge_decision: bool = False  # Times prefixed with J
    raw_outcome: Optional[str] = None  # exact HY-TEK time/status token


@dataclass
class ParsedMeet:
    """Top-level parsed meet data."""
    meet_name: str                 # e.g. "56th SNAG Seniors"
    meet_dates: Optional[str]      # e.g. "17/3/2026 to 22/3/2026"
    session: Optional[str]         # e.g. "Day 1 Session 1"
    start_date: date | None = None
    end_date: date | None = None
    day_number: int | None = None
    session_number: int | None = None
    metadata_conflicts: list[str] = field(default_factory=list)
    events: list[ParsedEvent] = field(default_factory=list)

    @property
    def total_results(self) -> int:
        return sum(len(e.results) for e in self.events)

    @property
    def total_relay_results(self) -> int:
        return sum(len(e.relay_results) for e in self.events)

    @property
    def unique_swimmers(self) -> set[str]:
        swimmers = {r.name for e in self.events for r in e.results}
        for e in self.events:
            for rr in e.relay_results:
                for leg in rr.legs:
                    swimmers.add(leg.name)
        return swimmers


# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

# Page header examples:
#   "56th SNAG Seniors - 17/3/2026 to 22/3/2026"
#   "11th SNSC SCM 2025 - 07-Nov-25 to 09-Nov-25"
#   "47th SEA Age 2025 - 6/25/2025 to 6/27/2025"
#   "55th SNAG Juniors - 14 Mar 2025 to 16 Mar 2025"
_DATE_TOKEN = (
    r"(?:\d{1,2}/\d{1,2}/\d{4}"          # 17/3/2026 (day-first) or 6/25/2025
    r"|\d{1,2}-[A-Za-z]{3}-\d{2}"        # 07-Nov-25
    r"|\d{1,2}\s+[A-Za-z]{3}\s+\d{4})"   # 14 Mar 2025
)
RE_MEET_HEADER = re.compile(
    rf"^(.+?)\s*-\s*({_DATE_TOKEN}(?:\s+to\s+{_DATE_TOKEN})?)$",
    re.IGNORECASE,
)

# Session line: "Results - Day 1 Session 1". Bare "Results" is valid but
# intentionally carries no day/session evidence.
RE_SESSION = re.compile(
    r"^Results\s*-\s*Day\s+(\d+)\s+Session\s+(\d+)\s*$",
    re.IGNORECASE,
)
RE_BARE_RESULTS = re.compile(r"^Results\s*$", re.IGNORECASE)


def _parse_meet_date(raw_value: str) -> date | None:
    """Parse supported source formats, preferring day-first slash dates."""
    if re.fullmatch(r"\d{1,2}-[A-Za-z]{3}-\d{2}", raw_value):
        try:
            return datetime.strptime(raw_value, "%d-%b-%y").date()
        except ValueError:
            return None

    # Spell-out month form: "14 Mar 2025". Kept to exactly the three-letter
    # month the printer emits so the grammar cannot absorb surrounding prose,
    # and validated through the same calendar check as the other formats.
    if re.fullmatch(r"\d{1,2}\s+[A-Za-z]{3}\s+\d{4}", raw_value):
        try:
            return datetime.strptime(raw_value, "%d %b %Y").date()
        except ValueError:
            return None

    # Existing slash dates are day-first. Fall back to US month-first only when
    # day-first is impossible (for example 6/25/2025), making the choice
    # unambiguous rather than silently reinterpreting 5/6/2025.
    for date_format in ("%d/%m/%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(raw_value, date_format).date()
        except ValueError:
            pass
    return None


def parse_meet_date_range(raw_value: str) -> tuple[date | None, date | None]:
    """Parse a supported HY-TEK date or inclusive date range.

    Invalid calendar values remain unresolved instead of being replaced with a
    current timestamp.
    """
    parts = [part.strip() for part in raw_value.split(" to ")]
    if len(parts) not in {1, 2}:
        return None, None
    start = _parse_meet_date(parts[0])
    end = _parse_meet_date(parts[-1])
    if start is None or end is None or end < start:
        return None, None
    return start, end

# Event header: "Event 101F Men 13 & Over 100 LC Meter Breaststroke"
# Preserve the optional source suffix; it identifies separate finals events.
RE_EVENT_HEADER = re.compile(
    r"^Event\s+([0-9]+[A-Za-z]?)\s+(.+)$"
)

# Continuation header: "Preliminaries ... (Event 101 Boys 13-14 200 LC Meter IM)"
# or just "(Event 101F Men 13 & Over 100 LC Meter Breaststroke)"
RE_EVENT_CONTINUATION = re.compile(
    r"(?:Preliminaries\s*\.\.\.\s*)?\(Event\s+([0-9]+[A-Za-z]?)\s+(.+?)\)"
)

# Time standard lines have a real time and repeat the standard label. Requiring
# both prevents a placement-led first result ending in MTS from being consumed.
RE_TIME_STANDARD = re.compile(
    r"^((?:\d+:)?\d{2}\.\d{2})\s+"
    r"(?:(?:\d{1,2}-\d{1,2}|\d{1,2}\s*&\s*Over)\s+)?"
    r"MTS\s+(?:MTS|Minimum\s+TimeStandard)\s*$"
)

# Column header variants:
#   Prelim PDF:  "Name Age Team Seed Time Prelim Time"
#   Final PDF:   "Name Age Team Prelim Time Finals Time"
#   Timed Final: "Name Age Team Seed Time Finals Time"
RE_COLUMN_HEADER = re.compile(
    r"^\s*Name\s+Age\s+Team\s+"
    r"(?:"
    r"Seed\s+Time\s+(Prelim Time)"           # Prelim PDF
    r"|Prelim\s+Time\s+(Finals Time)"         # Final PDF (has both columns)
    r"|Seed\s+Time\s+(Finals Time)"           # Timed final / juniors
    r")\s*$"
)

# Section markers: "Preliminaries", "Finals", "A - Final", "B - Final", "C - Final"
RE_SECTION_MARKER = re.compile(
    r"^(Preliminaries|Finals|[A-Z]\s*-\s*Final)\s*$"
)

# Result line patterns
# Normal: "1 WU, Dylan Jiaxu 14 Pacific Swimming Club 2:19.50 2:18.62 qMTS"
# Tied:   "*116 Chan, Benedict 17 AquaTech Swimming 59.93 1:00.98 MTS"
# DQ:     "--- *Tao, Shoichi 14 D'Ace Seahawks (Phi) 2:28.04 DQ"
# NS:     "--- Hong, Cheng Hou 13 Swimfast Aquatic Club 3:00.90 NS"
RE_RESULT_LINE = re.compile(
    r"^(\*?\d+|---)\s+"       # placement (number, *number for tied, --- for DQ/NS)
    r"(?:\d{1,2}-(?:[1-9]\d?)?\s+)?"  # optional heat-lane column ("1-2", "10-")
    r"(.+?)\s+"               # name (greedy but will be trimmed)
    r"(\d{1,2})\s+"           # age
    r"(.+?)\s+"               # team
    r"([\d:]+\.[\d]+|NT)\s+"  # seed time or NT
    r"(X?[\d:]+\.[\d]+|XDQ|DQ|NS|DNF|DNS|SCR)" # finals time/status; X marks exhibition
    r"(?:\s+(qMTS|MTS))?"     # optional qualifier
)

# One immutable HY-TEK source has a confirmed unknown observation rendered with
# only one terminal NT token.  The same shape elsewhere can mean a missing
# outcome, so acceptance is intentionally bound to the corroborated meet/event
# and exact source row rather than widening the normal result grammar.
RE_LEADING_UNKNOWN_NT_RESULT = re.compile(
    r"^---\s+"
    r"(\*.+?)\s+"              # source-marked guest name
    r"(\d{1,2})\s+"            # age
    r"(.+?)\s+"                # team
    r"NT\s*$"
)
_EXPLICIT_UNKNOWN_NT_SOURCE_ROWS = {
    (
        "21st SNSC 2026",
        "108",
        "--- *Yu, Chengyou 17 Nexus International School NT",
    ),
}

# Split line: "r:+0.66 29.54 1:05.33 (35.79) 1:45.88 (40.55) 2:18.62 (32.74)"
# Or without reaction time: "30.63 1:12.33 (41.70) 1:53.80 (41.47) DQ (36.94)"
# Or just reaction time (50m events): "r:+0.62"
RE_REACTION_TIME = re.compile(r"r:\+?([\d.]+)")
RE_CUMULATIVE_TIME = re.compile(r"(\d+:[\d.]+|(?<!\()[\d]+\.[\d]+)")
RE_SPLIT_DELTA = re.compile(r"\(([\d.]+)\)")

# Relay column header: "Team Relay Seed Time Finals Time" or "Team Relay Seed Time Prelim Time"
RE_RELAY_COLUMN_HEADER = re.compile(
    r"^\s*Team\s+Relay\s+(?:Seed\s+Time|Prelim\s+Time)\s+(?:Prelim Time|Finals Time)\s*$"
)

# Relay result line: "1 Olympians Swimming (Can) A 3:55.01 3:53.48"
# Exhibition: "--- Olympians Swimming (Can) B 4:03.03 X4:02.19"
# DQ: "--- Serangoon Gardens Country Club D NT DQ"
RE_RELAY_RESULT = re.compile(
    r"^(\*?\d+|---)\s+"               # placement
    r"(?:\d{1,2}-(?:[1-9]\d?)?\s+)?"  # optional heat-lane column ("1-2", "10-")
    r"(.+?)\s+"                        # team name
    r"([A-Z])\s+"                      # relay letter
    r"([\d:]+\.[\d]+|NT)\s+"           # seed time
    r"((?:J|X)?[\d:]+\.[\d]+|DQ|NS|DNF|DNS|SCR)"  # J = judge decision; X = exhibition
)

# Relay leg line: "1) *Uhle, Ella 17 2) r:0.07 *Thai, Kayla 17 ..."
# Mixed relay: "1) *Chen, Yuejia W8 2) *Peng, Vincent M8 ..."
RE_RELAY_LEG = re.compile(
    r"(\d)\)\s+"                       # leg number
    r"(?:r:([\d.-]+)\s+)?"             # optional reaction time
    r"(\*?)([^,]+,\s*\S.*?)\s+"        # guest marker + name
    # Reject an age immediately fused to another ordinal marker (for example
    # ``41)5`` or ``146)`` from overlapping PDF columns). Otherwise the next
    # leg number can be consumed as part of a plausible but false age.
    r"(?:([MW])?(\d{1,2}))(?!\d?\))"   # optional gender marker + age
)

# Some immutable HY-TEK PDFs print adjacent relay-leg columns on top of each
# other, so the page itself superimposes glyphs that belong to different legs:
# ``W130)`` is the age token ``W10`` with the next leg's marker ``3)`` drawn over
# it, ``M94)`` is ``M9`` + ``4)``, ``146)`` is the age ``16`` with marker ``4)``
# drawn over it, ``W4)1`` interleaves ``W4)`` with a following digit, and
# ``3M)9`` interleaves marker ``3)`` with age ``M9``, and some rows superimpose a
# whole neighbouring row so digits land inside name tokens (``Elyon4) M``,
# ``1n8i``). The characters are verifiably present at overlapping x-coordinates
# on the same baseline in the source content stream (confirmed with pdfplumber
# character boxes and independently with pdfminer), so the affected legs cannot
# be recovered from the page without inventing which glyph is the age and which
# is the marker. They are therefore quarantined, never reconstructed, and the
# condition is reported on the relay.
RE_RELAY_LEG_COLUMN_OVERLAP = re.compile(
    r"(?:[MW]\d+\)"            # gender-marked age token fused with the next marker
    r"|\d{2,}\)"               # gender-less age token fused with the next marker
    r"|\d\)\d"                 # leg marker fused with a following digit
    r"|\d[MW]\)\d"             # leg marker interleaved with the next age token
    r"|[A-LN-VXYZn-vxyz]\d"    # letter fused with a digit (names carry none)
    r"|\d[a-ln-vxyz]"          # digit fused with a following name letter
    r"|\d\s\)\s*[MW]\b)"       # leg marker split apart by superimposed text
)

# A well-formed source row prints markers 1) to 4) once each. A missing marker
# means the page superimposed it on neighbouring text; a repeated marker means
# the source carries more leg fields than a single relay row can own. Neither
# can be resolved without guessing.
RE_RELAY_LEG_MARKER = re.compile(r"([1-4])\s?\)")


def _relay_row_shows_column_overlap(source_lines: Sequence[str]) -> bool:
    """True when an immutable source row shows superimposed leg columns."""
    return any(RE_RELAY_LEG_COLUMN_OVERLAP.search(line) for line in source_lines if line)


def _relay_leg_marker_counts(source_lines: Sequence[str]) -> Counter[int]:
    counts: Counter[int] = Counter()
    for line in source_lines:
        if line:
            counts.update(int(match) for match in RE_RELAY_LEG_MARKER.findall(line))
    return counts


def relay_leg_quarantine_source_reason(
    source_lines: Sequence[str] | None, *, is_no_show: bool = False
) -> str | None:
    """Describe, from the immutable source rows, why legs cannot be recovered.

    Returns ``None`` when the source rows themselves show no defect, in which
    case a quarantine reason is a parser limitation rather than a source
    condition.
    """
    rows = [line for line in (source_lines or []) if line]
    if _relay_row_shows_column_overlap(rows):
        return (
            "source columns overlap in the immutable PDF, so fused leg fields "
            "cannot be recovered without inventing data"
        )
    markers = _relay_leg_marker_counts(rows)
    if rows and set(markers) != {1, 2, 3, 4}:
        return (
            "source row does not print all four leg markers, so the leg cannot "
            "be recovered without inventing data"
        )
    if any(count > 1 for count in markers.values()):
        return (
            "source prints more leg fields than one relay row can own, so the "
            "surplus legs cannot be attributed without inventing data"
        )
    if not rows and is_no_show:
        return (
            "source prints no relay legs for a no-show relay, so nothing is "
            "invented to complete it"
        )
    return None


def _relay_leg_name_is_structurally_valid(name: str) -> bool:
    """Reject PDF overlap artifacts while allowing balanced name suffixes."""
    stripped = name.strip()
    if (
        not stripped
        or any(char.isdigit() for char in stripped)
        or "r:" in stripped.lower()
    ):
        return False

    parenthesis_depth = 0
    for char in stripped:
        if char == "(":
            parenthesis_depth += 1
        elif char == ")":
            parenthesis_depth -= 1
            if parenthesis_depth < 0:
                return False
    return parenthesis_depth == 0

# DQ code line: "SW 7.4c Hands brought back beyond..."
RE_DQ_CODE = re.compile(r"^(SW\s+[\d.]+[a-z]?)\s+(.+)$")

# Page header line (to skip)
RE_PAGE_HEADER = re.compile(r"HY-TEK.s MEET MANAGER")


# ---------------------------------------------------------------------------
# Helper: clean event name
# ---------------------------------------------------------------------------

# Strip final type suffixes from event names
RE_FINAL_TYPE_SUFFIX = re.compile(
    r"\s+(?:Super Final|A - Final|B - Final|C - Final)\s*$", re.IGNORECASE
)


def clean_event_name(event_name: str) -> str:
    """Remove final type suffixes like 'Super Final' from event names."""
    return RE_FINAL_TYPE_SUFFIX.sub("", event_name).strip()


# ---------------------------------------------------------------------------
# Helper: compute per-leg split times from relay cumulative splits
# ---------------------------------------------------------------------------

def compute_relay_leg_times(
    splits: list[Split], num_legs: int = 4
) -> list[Optional[str]]:
    """
    Given relay cumulative splits, compute each leg's total time.

    For a 4x100 relay with 8 splits (2 per leg):
      Leg 1 time = cumulative at split[1] (the 100m mark)
      Leg 2 time = delta at split[3] (the 200m mark)
      ...

    Returns list of 4 leg time strings, or None if not computable.
    """
    if not splits or num_legs < 1:
        return [None] * num_legs

    splits_per_leg = len(splits) // num_legs
    if splits_per_leg < 1:
        return [None] * num_legs

    leg_times: list[Optional[str]] = []
    for leg_idx in range(num_legs):
        last_split_in_leg = (leg_idx + 1) * splits_per_leg - 1
        if last_split_in_leg >= len(splits):
            leg_times.append(None)
            continue

        if leg_idx == 0:
            # First leg: cumulative time at the end of their distance
            leg_times.append(splits[last_split_in_leg].cumulative_time)
        else:
            # Subsequent legs: delta at the end of their distance
            leg_times.append(splits[last_split_in_leg].split_time)

    return leg_times


# ---------------------------------------------------------------------------
# Helper: parse event name into components
# ---------------------------------------------------------------------------

def parse_event_name(event_name: str) -> dict:
    """Extract gender, age group, distance, stroke, course from event name."""
    info: dict = {
        "gender": None, "age_group": None,
        "distance": None, "stroke": None, "course": "LC",
        "relay_count": None, "leg_distance": None,
    }

    # Gender
    for g in ("Boys", "Girls", "Men", "Women"):
        if g in event_name:
            info["gender"] = g
            break

    # Age group: "13-14", "15-17", "18 & Over", "11 Year Olds", "12 Year Olds"
    m = re.search(r"(\d{1,2}-\d{1,2}|\d{1,2}\s*&\s*Over|\d{1,2}\s+Year\s+Olds?)", event_name)
    if m:
        info["age_group"] = m.group(1)

    # Distance. HY-TEK may print relays as either "4x50" or their total
    # distance ("200 ... Relay"). Canonical distance is always the total.
    relay_distance = re.search(r"(\d+)\s*[xX]\s*(\d+)\s+[LS]C\s+Meter", event_name)
    if relay_distance:
        info["relay_count"] = int(relay_distance.group(1))
        info["leg_distance"] = int(relay_distance.group(2))
        info["distance"] = info["relay_count"] * info["leg_distance"]
    else:
        m = re.search(r"(\d+)\s+[LS]C\s+Meter", event_name)
        if m:
            info["distance"] = int(m.group(1))
            if "Relay" in event_name and info["distance"] % 4 == 0:
                info["relay_count"] = 4
                info["leg_distance"] = info["distance"] // 4

    # Course
    if "SC Meter" in event_name:
        info["course"] = "SC"

    # Stroke
    for stroke in ("IM", "Individual Medley", "Freestyle", "Backstroke",
                    "Breaststroke", "Butterfly"):
        if stroke in event_name:
            info["stroke"] = stroke
            break

    return info


# ---------------------------------------------------------------------------
# Helper: parse a time string into seconds
# ---------------------------------------------------------------------------

def time_to_seconds(time_str: str) -> Optional[float]:
    """Convert '2:22.15' or '58.42' to seconds. Returns None for non-time values."""
    if not time_str or time_str in ("DQ", "NS", "DNF", "DNS", "NT", "SCR"):
        return None
    try:
        if ":" in time_str:
            parts = time_str.split(":")
            return float(parts[0]) * 60 + float(parts[1])
        return float(time_str)
    except (ValueError, IndexError):
        return None


RESULT_STATUS_MAP = {
    "XDQ": "dq",
    "DQ": "dq",
    "NS": "ns",
    "DNS": "dns",
    "DNF": "dnf",
    "SCR": "scratched",
}


def normalize_result_status(source_value: str | None) -> str:
    """Map an official HY-TEK result token to the canonical status vocabulary."""
    if not source_value:
        return "unknown"
    normalized = source_value.strip().upper()
    if normalized in RESULT_STATUS_MAP:
        return RESULT_STATUS_MAP[normalized]
    normalized_time = normalized.removeprefix("X").removeprefix("J")
    return "finished" if time_to_seconds(normalized_time) is not None else "unknown"


# ---------------------------------------------------------------------------
# Helper: parse splits from a line of text
# ---------------------------------------------------------------------------

def parse_splits_line(line: str) -> tuple[Optional[str], list[Split]]:
    """
    Parse a split/reaction time line.

    HY-TEK format examples:
      "r:+0.66 29.54 1:05.33 (35.79) 1:45.88 (40.55) 2:18.62 (32.74)"
      "30.63 1:12.33 (41.70) 1:53.80 (41.47) DQ (36.94)"
      "r:+0.62"  (50m event, reaction time only)
      "3:18.57 (41.45) 4:00.02 (41.45) 4:41.82 (41.80) 5:24.14 (42.32)"  (1500m continuation)

    Pattern: CUMULATIVE (DELTA) CUMULATIVE (DELTA) ...
    The first cumulative may not have a preceding delta.

    Returns (reaction_time, [Split, ...]).
    """
    reaction = None
    m = RE_REACTION_TIME.search(line)
    if m:
        reaction = m.group(1)

    # Remove the reaction time portion for cleaner split parsing
    clean = RE_REACTION_TIME.sub("", line).strip()

    # For DQ lines, remove "DQ" from the split data
    clean = re.sub(r"\bDQ\b", "", clean).strip()

    if not clean:
        return reaction, []

    # Tokenize: walk through and pick out cumulative times and (delta) pairs
    # A cumulative time is either M:SS.ss or SS.ss that is NOT inside parens
    # A delta is (SS.ss) or (M:SS.ss) inside parens
    splits: list[Split] = []

    # Use a single regex to find all tokens in order:
    # - parenthesized delta: \(([\d:]+\.[\d]+)\)
    # - cumulative time: ([\d]+:[\d]+\.[\d]+) or ([\d]+\.[\d]+)
    TOKEN_RE = re.compile(
        r"\(([\d:]+\.[\d]+)\)"          # group 1: delta inside parens
        r"|"
        r"([\d]+:[\d]+\.[\d]+)"         # group 2: cumulative with colon (M:SS.ss)
        r"|"
        r"(?<![:(])([\d]+\.[\d]+)"      # group 3: cumulative without colon (SS.ss), not after ( or :
    )

    tokens = []  # list of ("cum", value) or ("delta", value)
    for tok_match in TOKEN_RE.finditer(clean):
        if tok_match.group(1):
            tokens.append(("delta", tok_match.group(1)))
        elif tok_match.group(2):
            tokens.append(("cum", tok_match.group(2)))
        elif tok_match.group(3):
            tokens.append(("cum", tok_match.group(3)))

    # Now pair them up: each cumulative may be followed by a delta
    i = 0
    while i < len(tokens):
        if tokens[i][0] == "cum":
            cum_val = tokens[i][1]
            delta_val = None
            if i + 1 < len(tokens) and tokens[i + 1][0] == "delta":
                delta_val = tokens[i + 1][1]
                i += 2
            else:
                i += 1
            splits.append(Split(cumulative_time=cum_val, split_time=delta_val))
        elif tokens[i][0] == "delta":
            # Orphan delta (e.g. DQ line where cumulative was "DQ") — skip
            i += 1

    return reaction, splits


# ---------------------------------------------------------------------------
# Core: parse all pages of extracted text
# ---------------------------------------------------------------------------

def _is_split_line(line: str) -> bool:
    """Check if a line is a split/reaction time line (not a result or header)."""
    stripped = line.strip()
    if not stripped:
        return False
    # Starts with reaction time
    if stripped.startswith("r:"):
        return True
    # Starts with a bare time (cumulative split) and contains parenthesized deltas
    # But NOT if it starts with a placement number or "---" or "Event" or "Name"
    if RE_DQ_CODE.match(stripped):
        return False
    if stripped.startswith("---") or stripped.startswith("Event"):
        return False
    if RE_RESULT_LINE.match(stripped):
        return False
    # Looks like splits: starts with a time-like pattern and has parens
    if re.match(r"^\d{1,2}[.:]\d{2}", stripped) and "(" in stripped:
        return True
    # Multi-line 1500m splits: just cumulative times with deltas
    if re.match(r"^\d+:\d{2}\.\d{2}\s", stripped) and "(" in stripped:
        return True
    # Bare first-split time (no parens) like "30.63 1:12.33 (41.70)..."
    if re.match(r"^\d{2}\.\d{2}\s", stripped) and "(" in stripped:
        return True
    return False


def _is_dq_code_line(line: str) -> bool:
    """Check if line is a DQ violation code."""
    return bool(RE_DQ_CODE.match(line.strip()))


_PRIVATE_USE_ASCII_TRANSLATION = str.maketrans(
    {codepoint: codepoint - 0xF000 for codepoint in range(0xF000, 0xF100)}
)


def _normalize_extracted_text(value: str) -> str:
    """Undo PDFs that map byte values into the U+F000 private-use block."""
    return value.translate(_PRIVATE_USE_ASCII_TRANSLATION)


def _normalize_private_use_hytek_signature(value: str) -> str:
    """Normalize PUA bytes only when they decode to an explicit HY-TEK header."""
    if not any("\uf000" <= char <= "\uf0ff" for char in value):
        return value
    normalized = _normalize_extracted_text(value)
    if "HY-TEK" in normalized and "MEET MANAGER" in normalized:
        return normalized
    return value


def _install_pdfplumber_hytek_signature_normalizer() -> None:
    """Make the registry's first-page sniff see private-use HY-TEK headers.

    Format detection lives in the parser registry and calls pdfplumber directly.
    Keep this adapter fail-closed: only text that deterministically decodes to
    both HY-TEK header markers is changed; unrelated private-use PDFs are left
    byte-for-byte as extracted.
    """
    extract_text = pdfplumber.page.Page.extract_text
    if getattr(extract_text, "_hytek_signature_normalizer", False):
        return

    @wraps(extract_text)
    def normalized_extract_text(page, *args, **kwargs):
        value = extract_text(page, *args, **kwargs)
        if not value:
            return value
        return _normalize_private_use_hytek_signature(value)

    normalized_extract_text._hytek_signature_normalizer = True
    pdfplumber.page.Page.extract_text = normalized_extract_text


_install_pdfplumber_hytek_signature_normalizer()


def parse_hytek_text(pages_text: list[str]) -> tuple[ParsedMeet, ConfidenceReport]:
    """
    Parse extracted page texts into a ParsedMeet.

    Args:
        pages_text: List of strings, one per PDF page.

    Returns:
        Tuple of (ParsedMeet, ConfidenceReport).
    """
    meet_name = ""
    meet_dates = None
    session = None
    start_date = None
    end_date = None
    day_number = None
    session_number = None
    session_conflicted = False
    metadata_conflicts: list[str] = []
    events: list[ParsedEvent] = []
    total_lines = 0
    classified_lines = 0
    unmatched_lines: list[str] = []
    current_event: Optional[ParsedEvent] = None
    current_result: Optional[ParsedResult] = None
    current_relay: Optional[ParsedRelayResult] = None
    in_relay_section = False  # True when we're inside a relay event
    time_type = "Prelim Time"

    # Map event_number -> ParsedEvent (to handle continuation pages)
    event_map: dict[str, ParsedEvent] = {}

    # id(ParsedRelayResult) -> its source leg rows, used to document quarantine
    # reasons that come from the immutable PDF layout rather than from a gap in
    # the parser.
    relay_source_lines: dict[int, list[str]] = {}

    for page_text in pages_text:
        if not page_text:
            continue

        page_text = _normalize_extracted_text(page_text)
        lines = page_text.split("\n")

        for i, raw_line in enumerate(lines):
            line = raw_line.strip()
            if not line:
                continue

            total_lines += 1

            # Skip page headers
            if RE_PAGE_HEADER.search(line):
                continue

            # Meet name + dates. HY-TEK repeats these on every page; repeated
            # values corroborate the first observation while disagreements hold
            # typed metadata as unresolved.
            m = RE_MEET_HEADER.match(line)
            if m:
                observed_name = m.group(1).strip()
                observed_dates = m.group(2).strip()
                observed_start, observed_end = parse_meet_date_range(observed_dates)
                if not meet_name:
                    meet_name = observed_name
                    meet_dates = observed_dates
                    start_date = observed_start
                    end_date = observed_end
                elif (observed_name, observed_dates) != (meet_name, meet_dates):
                    metadata_conflicts.append(
                        f"Conflicting meet header: {observed_name} - {observed_dates}"
                    )
                    start_date = None
                    end_date = None
                continue

            # Session
            m = RE_SESSION.match(line)
            if m:
                observed_day = int(m.group(1))
                observed_session = int(m.group(2))
                observed_label = f"Day {observed_day} Session {observed_session}"
                if observed_day <= 0 or observed_session <= 0:
                    if not session_conflicted:
                        metadata_conflicts.append(
                            f"Day and session numbers must be positive: {observed_label}"
                        )
                    session_conflicted = True
                    session = None
                    day_number = None
                    session_number = None
                elif session_conflicted:
                    continue
                elif session is None:
                    session = observed_label
                    day_number = observed_day
                    session_number = observed_session
                elif observed_label != session:
                    metadata_conflicts.append(
                        f"Conflicting session header: {observed_label}"
                    )
                    session_conflicted = True
                    session = None
                    day_number = None
                    session_number = None
                continue
            if RE_BARE_RESULTS.match(line):
                continue

            # Event header (new event)
            m = RE_EVENT_HEADER.match(line)
            if m:
                evt_num = m.group(1)
                evt_name = clean_event_name(m.group(2).strip())
                info = parse_event_name(evt_name)

                # Build a key that includes age group to distinguish sub-events
                # e.g. "101-Boys 13-14 200 LC Meter IM" vs "101-Men 15-17 200 LC Meter IM"
                evt_key = f"{evt_num}-{evt_name}"

                is_relay = "Relay" in evt_name

                if evt_key not in event_map:
                    current_event = ParsedEvent(
                        event_number=evt_num,
                        event_name=evt_name,
                        gender=info["gender"],
                        age_group=info["age_group"],
                        distance=info["distance"],
                        stroke=info["stroke"],
                        course=info["course"],
                        time_standard=None,
                        time_type="Prelim Time",
                        is_relay=is_relay,
                        relay_count=info["relay_count"],
                        leg_distance=info["leg_distance"],
                    )
                    event_map[evt_key] = current_event
                    events.append(current_event)
                else:
                    current_event = event_map[evt_key]
                in_relay_section = is_relay
                current_result = None
                current_relay = None
                continue

            # Continuation header
            m = RE_EVENT_CONTINUATION.match(line)
            if m:
                evt_num = m.group(1)
                evt_name = m.group(2).strip()
                evt_key = f"{evt_num}-{evt_name}"
                if evt_key in event_map:
                    current_event = event_map[evt_key]
                    in_relay_section = current_event.is_relay
                current_result = None
                current_relay = None
                continue

            # Time standard line
            m = RE_TIME_STANDARD.match(line)
            if m and current_event and current_event.time_standard is None:
                current_event.time_standard = m.group(1)
                continue

            # Column header — detect time type (round)
            m = RE_COLUMN_HEADER.match(line)
            if m:
                if m.group(1):
                    time_type = "Prelim Time"
                elif m.group(2):
                    time_type = "Finals Time"
                else:
                    time_type = "Timed Final"
                if current_event:
                    current_event.time_type = time_type
                in_relay_section = False
                continue

            # Relay column header
            if RE_RELAY_COLUMN_HEADER.match(line):
                in_relay_section = True
                # The first timing column distinguishes a seeded timed final
                # from a progression final whose input is a prelim time.
                if "Seed Time Prelim Time" in line:
                    time_type = "Prelim Time"
                elif "Prelim Time Finals Time" in line:
                    time_type = "Finals Time"
                else:
                    time_type = "Timed Final"
                if current_event:
                    current_event.time_type = time_type
                continue

            # Section marker
            if RE_SECTION_MARKER.match(line):
                continue

            # Relay leg line (must check before DQ/split since it contains numbers)
            if in_relay_section and current_relay:
                leg_matches = RE_RELAY_LEG.findall(line)
                if leg_matches:
                    # Preserve the source rows for the quarantine report below;
                    # relays are unhashable dataclasses, so key by identity.
                    rows = relay_source_lines.setdefault(id(current_relay), [])
                    if line not in rows:
                        rows.append(line)
                    for lm in leg_matches:
                        leg_num = int(lm[0])
                        rt = lm[1] if lm[1] else None
                        is_guest = bool(lm[2])
                        name = lm[3].strip()
                        gender_marker = lm[4] if lm[4] else None  # "M" or "W" for mixed
                        age = int(lm[5]) if lm[5] else None
                        current_relay.legs.append(ParsedRelayLeg(
                            leg_number=leg_num,
                            name=name,
                            is_guest=is_guest,
                            age=age,
                            gender=gender_marker,
                            reaction_time=rt,
                        ))
                    continue

            # Relay result line
            if in_relay_section and current_event:
                m = RE_RELAY_RESULT.match(line)
                if m:
                    placement_str = m.group(1)
                    team_name = m.group(2).strip()
                    relay_letter = m.group(3)
                    seed_raw = m.group(4).strip()
                    time_raw = m.group(5).strip()
                    raw_outcome = time_raw

                    placement = None
                    if placement_str != "---":
                        placement = int(placement_str.lstrip("*"))

                    is_judge_decision = time_raw.startswith("J")
                    is_exhibition = time_raw.startswith("X")
                    if is_judge_decision or is_exhibition:
                        time_raw = time_raw[1:]  # strip the source marker

                    is_dq = time_raw == "DQ"
                    is_ns = time_raw in ("NS", "DNS", "DNF", "SCR")
                    finals_time = None if (is_dq or is_ns) else time_raw
                    seed_time = seed_raw if seed_raw != "NT" else "NT"

                    current_relay = ParsedRelayResult(
                        team_name=team_name,
                        relay_letter=relay_letter,
                        placement=placement,
                        seed_time=seed_time,
                        finals_time=finals_time,
                        time_type=current_event.time_type,
                        is_dq=is_dq,
                        is_exhibition=is_exhibition,
                        status=normalize_result_status(time_raw),
                        is_judge_decision=is_judge_decision,
                        raw_outcome=raw_outcome,
                    )
                    current_event.relay_results.append(current_relay)
                    continue

            # DQ code line (must check before split line)
            dq_target = current_relay if (in_relay_section and current_relay and current_relay.is_dq) else (
                current_result if (current_result and current_result.is_dq) else None
            )
            if _is_dq_code_line(line) and dq_target:
                m = RE_DQ_CODE.match(line)
                if m:
                    dq_target.dq_code = m.group(1).strip()
                    dq_target.dq_description = m.group(2).strip()
                continue

            # Split line
            if _is_split_line(line):
                if in_relay_section and current_relay:
                    reaction, new_splits = parse_splits_line(line)
                    if reaction and current_relay.reaction_time is None:
                        current_relay.reaction_time = reaction
                    current_relay.splits.extend(new_splits)
                elif current_result:
                    reaction, new_splits = parse_splits_line(line)
                    if reaction and current_result.reaction_time is None:
                        current_result.reaction_time = reaction
                    current_result.splits.extend(new_splits)
                continue

            # Result line
            m = RE_RESULT_LINE.match(line)
            if m and current_event:
                placement_str = m.group(1)
                name_raw = m.group(2).strip()
                age_str = m.group(3)
                team = m.group(4).strip()
                seed_time = m.group(5).strip()
                finals_raw = m.group(6).strip()
                raw_outcome = finals_raw
                qualifier = m.group(7)

                # Placement
                is_tied = False
                placement = None
                if placement_str == "---":
                    placement = None
                elif placement_str.startswith("*"):
                    is_tied = True
                    placement = int(placement_str.lstrip("*"))
                else:
                    placement = int(placement_str)

                # HY-TEK uses either a leading * on the name or X on the result
                # time for guest/exhibition swims. The relational model preserves
                # both through its existing isGuest field.
                is_exhibition = bool(re.fullmatch(r"X[\d:]+\.[\d]+", finals_raw))
                is_guest = name_raw.startswith("*") or is_exhibition
                name = name_raw.lstrip("*").strip()

                if is_exhibition:
                    finals_raw = finals_raw[1:]

                # Age
                age = int(age_str) if age_str else None

                # Seed time
                if seed_time == "NT":
                    seed_time_val: Optional[str] = "NT"
                else:
                    seed_time_val = seed_time

                # Status flags
                is_dq = finals_raw in {"DQ", "XDQ"}
                is_ns = finals_raw in ("NS", "DNS", "DNF", "SCR")
                finals_time = None if (is_dq or is_ns) else finals_raw

                current_result = ParsedResult(
                    placement=placement,
                    is_tied=is_tied,
                    name=name,
                    is_guest=is_guest,
                    age=age,
                    team=team,
                    seed_time=seed_time_val,
                    finals_time=finals_time,
                    time_type=current_event.time_type,
                    is_dq=is_dq,
                    dq_code=None,
                    dq_description=None,
                    is_ns=is_ns,
                    qualifier=qualifier,
                    reaction_time=None,
                    is_exhibition=is_exhibition,
                    splits=[],
                    status=normalize_result_status(finals_raw),
                    raw_outcome=raw_outcome,
                )
                current_event.results.append(current_result)
                continue

            # A narrow HY-TEK unknown-outcome form.  It is only safe before any
            # parsed row in the event and when immutable source evidence has
            # established the exact row; all other one-token rows stay quarantined.
            m = RE_LEADING_UNKNOWN_NT_RESULT.match(line)
            source_identity = (
                meet_name,
                current_event.event_number if current_event else None,
                line,
            )
            if (
                m
                and current_event
                and current_result is None
                and source_identity in _EXPLICIT_UNKNOWN_NT_SOURCE_ROWS
            ):
                name_raw = m.group(1).strip()
                current_result = ParsedResult(
                    placement=None,
                    is_tied=False,
                    name=name_raw.lstrip("*").strip(),
                    is_guest=True,
                    age=int(m.group(2)),
                    team=m.group(3).strip(),
                    seed_time=None,
                    finals_time=None,
                    time_type=current_event.time_type,
                    is_dq=False,
                    dq_code=None,
                    dq_description=None,
                    is_ns=False,
                    qualifier=None,
                    reaction_time=None,
                    splits=[],
                    status="unknown",
                    raw_outcome="NT",
                )
                current_event.results.append(current_result)
                continue

            # Line matched nothing — track as unmatched
            # (Skip known noise: repeated meet headers, empty-ish lines, page numbers)
            if not RE_MEET_HEADER.match(line) and not line.isdigit():
                unmatched_lines.append(line)

    # Quarantine relay-leg identities that PDF column overlap has corrupted.
    # The team performance remains usable, but unsafe person rows must never be
    # promoted into the swimmer registry. Some of these relays carry source rows
    # whose columns are printed on top of each other, or that carry more leg
    # fields than the relay row owns (see RE_RELAY_LEG_COLUMN_OVERLAP); those are
    # immutable-source conditions, so the legs are reported as quarantined rather
    # than reconstructed from guesses.
    for event in events:
        for relay in event.relay_results:
            source_lines = relay_source_lines.get(id(relay), [])
            safe_legs: list[ParsedRelayLeg] = []
            reasons: list[str] = []
            seen_numbers: set[int] = set()
            for leg in relay.legs:
                reason = None
                if leg.leg_number not in {1, 2, 3, 4}:
                    reason = f"invalid leg number {leg.leg_number}"
                elif leg.leg_number in seen_numbers:
                    reason = f"duplicate leg number {leg.leg_number}"
                elif leg.age is not None and not 5 <= leg.age <= 100:
                    reason = f"implausible age {leg.age}"
                elif not _relay_leg_name_is_structurally_valid(leg.name):
                    reason = "corrupted name structure"

                if reason:
                    reasons.append(f"leg {leg.leg_number}: {reason}")
                    continue
                seen_numbers.add(leg.leg_number)
                safe_legs.append(leg)

            missing = sorted({1, 2, 3, 4} - seen_numbers)
            if missing:
                reasons.append(f"missing safe legs {missing}")
            relay.legs = safe_legs
            if reasons:
                source_reason = relay_leg_quarantine_source_reason(
                    source_lines,
                    is_no_show=relay.status in {"ns", "dns", "dnf", "scratched"},
                )
                if source_reason:
                    reasons.insert(0, source_reason)
                relay.leg_parse_status = "partial" if safe_legs else "unavailable"
                relay.leg_parse_warning = "; ".join(reasons)

    # Post-process: assign split distances
    for event in events:
        if event.distance:
            # Individual results
            for result in event.results:
                if result.splits:
                    n_splits = len(result.splits)
                    interval = event.distance // n_splits if n_splits > 0 else 50
                    for j, sp in enumerate(result.splits):
                        sp.distance = interval * (j + 1)

            # Relay results: assign distances and compute per-leg times
            for rr in event.relay_results:
                if rr.splits:
                    n_splits = len(rr.splits)
                    interval = event.distance // n_splits if n_splits > 0 else 50
                    for j, sp in enumerate(rr.splits):
                        sp.distance = interval * (j + 1)

                    # Compute per-leg times and assign per-swimmer splits
                    num_legs = event.relay_count or 4
                    leg_times = compute_relay_leg_times(rr.splits, num_legs=num_legs)
                    splits_per_leg = n_splits // num_legs if num_legs > 0 else 0
                    legs_by_number = {leg.leg_number: leg for leg in rr.legs}
                    for leg_number, lt in enumerate(leg_times, start=1):
                        leg = legs_by_number.get(leg_number)
                        if leg is None:
                            continue
                        leg_idx = leg_number - 1
                        if lt:
                            leg.split_time = lt
                        # Leg 1's RT is the team's start RT
                        if leg_idx == 0 and leg.reaction_time is None and rr.reaction_time:
                            leg.reaction_time = rr.reaction_time
                        # Slice this swimmer's lap splits from the team splits
                        if splits_per_leg > 0:
                            start = leg_idx * splits_per_leg
                            end = start + splits_per_leg
                            # Copy before re-numbering; relay-level cumulative
                            # distances and leg-relative distances are different facts.
                            leg_splits = [
                                Split(
                                    cumulative_time=sp.cumulative_time,
                                    split_time=sp.split_time,
                                    distance=interval * (j + 1),
                                )
                                for j, sp in enumerate(rr.splits[start:end])
                            ]
                            leg.splits = leg_splits

    meet = ParsedMeet(
        meet_name=meet_name,
        meet_dates=meet_dates,
        session=session,
        start_date=start_date,
        end_date=end_date,
        day_number=day_number,
        session_number=session_number,
        metadata_conflicts=metadata_conflicts,
        events=events,
    )

    classified = total_lines - len(unmatched_lines)
    confidence = compute_confidence(meet, total_lines, classified, unmatched_lines)

    return meet, confidence


# ---------------------------------------------------------------------------
# Confidence scoring
# ---------------------------------------------------------------------------

# Checks whose failure blocks an import. A check outside this set stays visible
# in the report so operators can judge quality without failing a whole package
# (line coverage, for example, is expected to drop where a source layout forces
# rows to be quarantined).
CRITICAL_CHECKS = frozenset(
    {
        "meet_name",
        "meet_dates",
        "metadata_consistent",
        "session_metadata",
        "positive_day_session",
        "has_events",
        "has_results",
        "relay_leg_integrity",
    }
)

# Critical checks that only describe identity printed on the page. When a caller
# supplies the competition name and date range, these are satisfied by that input
# instead of by the sheet; every other critical check still has to hold.
IDENTITY_CHECKS = frozenset({"meet_name", "meet_dates"})


@dataclass
class ConfidenceReport:
    """Result of confidence checks on parsed data."""
    score: float                     # 0.0 – 1.0
    checks: dict[str, bool]          # individual checks passed/failed
    total_lines: int = 0
    classified_lines: int = 0        # lines matched by a regex
    unmatched_lines: list[str] = field(default_factory=list)  # sample of unmatched

    @property
    def passed(self) -> bool:
        return self.score >= 0.6 and all(
            self.checks.get(name, False) for name in CRITICAL_CHECKS
        )


def compute_confidence(meet: ParsedMeet, total_lines: int, classified_lines: int,
                       unmatched_lines: list[str]) -> ConfidenceReport:
    """Score how confident we are in the parsed output."""
    checks: dict[str, bool] = {}

    # 1. Meet name extracted?
    checks["meet_name"] = bool(meet.meet_name)

    # 2. Meet dates resolved as valid calendar dates?
    checks["meet_dates"] = meet.start_date is not None and meet.end_date is not None

    # Repeated page metadata must agree. Bare "Results" is a valid signal that
    # no structured session metadata was supplied.
    checks["metadata_consistent"] = not meet.metadata_conflicts
    checks["session_metadata"] = (
        not meet.session
        or (meet.day_number is not None and meet.session_number is not None)
    )
    checks["positive_day_session"] = not any(
        "must be positive" in conflict for conflict in meet.metadata_conflicts
    ) and (
        meet.day_number is None
        or (meet.day_number > 0 and meet.session_number is not None and meet.session_number > 0)
    )

    # 3. At least one event found?
    checks["has_events"] = len(meet.events) > 0

    # 4. At least one result found?
    checks["has_results"] = meet.total_results + meet.total_relay_results > 0

    # 5. All events have time_type set?
    checks["all_events_typed"] = all(
        ev.time_type in ("Prelim Time", "Finals Time", "Timed Final") for ev in meet.events
    )

    # 6. >80% of non-blank lines classified?
    line_ratio = classified_lines / max(total_lines, 1)
    checks["line_coverage"] = line_ratio > 0.80

    # 7. No results with empty name?
    checks["no_empty_names"] = all(
        bool(r.name) for ev in meet.events for r in ev.results
    )

    # 8. All times are valid format?
    checks["valid_times"] = all(
        r.finals_time is None or bool(re.match(r"^\d+:[\d.]+$|^[\d.]+$", r.finals_time))
        for ev in meet.events for r in ev.results
    )

    checks["relay_leg_integrity"] = all(
        leg.leg_number in {1, 2, 3, 4}
        and (leg.age is None or 5 <= leg.age <= 100)
        and _relay_leg_name_is_structurally_valid(leg.name)
        for ev in meet.events
        for relay in ev.relay_results
        for leg in relay.legs
    )
    checks["relay_leg_completeness"] = all(
        relay.leg_parse_status == "complete"
        for ev in meet.events
        for relay in ev.relay_results
    )

    passed_count = sum(1 for v in checks.values() if v)
    score = passed_count / len(checks)

    return ConfidenceReport(
        score=round(score, 3),
        checks=checks,
        total_lines=total_lines,
        classified_lines=classified_lines,
        unmatched_lines=unmatched_lines[:20],  # keep sample
    )


# ---------------------------------------------------------------------------
# High-level: parse a PDF file
# ---------------------------------------------------------------------------

_NO_AGE_COLUMN_HEADER = re.compile(
    r"^\s*Name\s+Team\s+(?:Seed|Prelim)\s+Time\s+(?:Prelim|Finals)\s+Time\s*$",
    re.MULTILINE,
)
_NO_AGE_SEED_TOKEN = re.compile(r"(?:\d+:)?\d{2}\.\d{2}|NT")
_NO_AGE_OUTCOME_TOKEN = re.compile(
    r"(?:J|X)?(?:\d+:)?\d{2}\.\d{2}|XDQ|DQ|NS|DNS|DNF|SCR"
)


def _has_no_age_result_columns(page_text: str) -> bool:
    """Detect only the individual result header whose Age column is absent."""
    return bool(_NO_AGE_COLUMN_HEADER.search(_normalize_extracted_text(page_text)))


def _group_pdf_words_by_row(words: list[dict], tolerance: float = 1.0) -> list[list[dict]]:
    """Group pdfplumber words that share a printed baseline."""
    groups: list[tuple[float, list[dict]]] = []
    for word in sorted(words, key=lambda item: (item["top"], item["x0"])):
        for top, group_words in groups:
            if abs(word["top"] - top) <= tolerance:
                group_words.append(word)
                break
        else:
            groups.append((word["top"], [word]))
    return [sorted(group_words, key=lambda item: item["x0"]) for _, group_words in groups]


def _parse_no_age_coordinate_rows(
    pdf_pages: list,
) -> tuple[dict[str, list[ParsedResult]], set[str], list[str]]:
    """Parse HY-TEK's no-age result schema from its printed PDF columns.

    Flattened text cannot distinguish variable-length names from teams when the
    Age column is absent. Header coordinates provide the source's actual column
    boundaries without applying this mode to ordinary age-bearing reports.
    """
    results_by_event: dict[str, list[ParsedResult]] = {}
    no_age_events: set[str] = set()
    quarantined: list[str] = []
    current_event_number: str | None = None

    for page in pdf_pages:
        words = page.extract_words(use_text_flow=True)
        for word in words:
            word["text"] = _normalize_extracted_text(word["text"])

        column_bounds: tuple[float, float, float] | None = None
        for row in _group_pdf_words_by_row(words):
            row_text = " ".join(word["text"] for word in row)
            event_match = re.search(
                r"(?:^|\()Event\s+([0-9]+[A-Za-z]?)\s+", row_text
            )
            if event_match:
                current_event_number = event_match.group(1)
                column_bounds = None

            tokens = [word["text"] for word in row]
            if (
                current_event_number
                and "Name" in tokens
                and "Team" in tokens
                and "Age" not in tokens
                and tokens.count("Time") >= 2
            ):
                name_header = next(word for word in row if word["text"] == "Name")
                team_header = next(word for word in row if word["text"] == "Team")
                time_headers = [word for word in row if word["text"] == "Time"]
                column_bounds = (
                    name_header["x0"],
                    team_header["x0"],
                    time_headers[0]["x1"],
                )
                no_age_events.add(current_event_number)
                results_by_event.setdefault(current_event_number, [])
                continue

            if not column_bounds or not current_event_number or not row:
                continue
            placement_token = row[0]["text"]
            if not re.fullmatch(r"(?:\*?\d+|---)", placement_token):
                continue

            name_x, team_x, seed_column_end = column_bounds
            # Header labels are left-aligned while data can begin a few points
            # before the glyph itself. Keep that tolerance relative to the
            # detected Team header rather than hardcoding a page coordinate.
            team_split = team_x - 5
            name_words = [word for word in row if name_x <= word["x0"] < team_split]
            trailing_words = [word for word in row if word["x0"] >= team_split]
            seed_candidates = [
                word
                for word in trailing_words
                if word["x1"] <= seed_column_end + 1
                and _NO_AGE_SEED_TOKEN.fullmatch(word["text"].rstrip("!"))
            ]
            if not name_words or not seed_candidates:
                continue

            seed_word = seed_candidates[-1]
            outcome_candidates = [
                word
                for word in trailing_words
                if word["x1"] > seed_column_end + 1
                and _NO_AGE_OUTCOME_TOKEN.fullmatch(word["text"].rstrip("!"))
            ]
            name_raw = " ".join(word["text"] for word in name_words).strip()
            team = " ".join(
                word["text"] for word in trailing_words if word["x0"] < seed_word["x0"]
            ).strip()
            seed_time = seed_word["text"].rstrip("!")
            if not name_raw or not team:
                continue
            if not outcome_candidates:
                quarantined.append(
                    f"Quarantined no-age result: event {current_event_number} "
                    f"{name_raw} (missing outcome)"
                )
                continue

            outcome_word = outcome_candidates[0]
            raw_outcome = outcome_word["text"]
            outcome = raw_outcome.rstrip("!")
            qualifier = next(
                (
                    word["text"]
                    for word in trailing_words
                    if word["x0"] > outcome_word["x1"]
                    and word["text"] in {"qMTS", "MTS"}
                ),
                None,
            )

            is_tied = placement_token.startswith("*")
            placement = (
                None
                if placement_token == "---"
                else int(placement_token.lstrip("*"))
            )
            is_exhibition = bool(
                re.fullmatch(r"X(?:\d+:)?\d{2}\.\d{2}", outcome)
            )
            parsed_outcome = outcome[1:] if is_exhibition else outcome
            is_dq = parsed_outcome in {"DQ", "XDQ"}
            is_ns = parsed_outcome in {"NS", "DNS", "DNF", "SCR"}
            finals_time = None if is_dq or is_ns else parsed_outcome
            is_guest = name_raw.startswith("*") or is_exhibition

            results_by_event[current_event_number].append(
                ParsedResult(
                    placement=placement,
                    is_tied=is_tied,
                    name=name_raw.lstrip("*").strip(),
                    is_guest=is_guest,
                    age=None,
                    team=team,
                    seed_time=seed_time,
                    finals_time=finals_time,
                    time_type="Prelim Time",
                    is_dq=is_dq,
                    dq_code=None,
                    dq_description=None,
                    is_ns=is_ns,
                    qualifier=qualifier,
                    reaction_time=None,
                    is_exhibition=is_exhibition,
                    splits=[],
                    status=normalize_result_status(outcome),
                    raw_outcome=raw_outcome,
                )
            )

    return results_by_event, no_age_events, quarantined


def parse_hytek_pdf(pdf_path: str | Path) -> tuple[ParsedMeet, ConfidenceReport]:
    """
    Parse a HY-TEK Meet Manager PDF file.

    Args:
        pdf_path: Path to the PDF file.

    Returns:
        Tuple of (ParsedMeet, ConfidenceReport).
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    pages_text: list[str] = []
    coordinate_results: dict[str, list[ParsedResult]] = {}
    no_age_events: set[str] = set()
    quarantined: list[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            pages_text.append(text or "")
        if any(_has_no_age_result_columns(text) for text in pages_text):
            coordinate_results, no_age_events, quarantined = _parse_no_age_coordinate_rows(
                pdf.pages
            )

    meet, confidence = parse_hytek_text(pages_text)
    if no_age_events:
        for event in meet.events:
            if event.event_number in no_age_events:
                # Never retain age-bearing regex guesses for a schema that has
                # no printed Age column.
                event.results = coordinate_results.get(event.event_number, [])
        confidence = compute_confidence(
            meet,
            confidence.total_lines,
            confidence.classified_lines,
            quarantined + confidence.unmatched_lines,
        )
    return meet, confidence


# ---------------------------------------------------------------------------
# CLI: __name__ == "__main__"
# ---------------------------------------------------------------------------

def _fmt_time(t: Optional[str]) -> str:
    return t if t else "-"


def _fmt_splits(splits: list[Split], max_show: int = 8) -> str:
    if not splits:
        return ""
    parts = []
    for sp in splits[:max_show]:
        if sp.split_time:
            parts.append(f"{sp.cumulative_time} ({sp.split_time})")
        else:
            parts.append(sp.cumulative_time)
    suffix = f" ... +{len(splits) - max_show} more" if len(splits) > max_show else ""
    return "  Splits: " + " | ".join(parts) + suffix


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m app.parsers.hytek <pdf_path> [--verbose] [--event N]")
        print("       python app/parsers/hytek.py <pdf_path> [--verbose] [--event N]")
        sys.exit(1)

    pdf_path = sys.argv[1]
    verbose = "--verbose" in sys.argv or "-v" in sys.argv
    event_filter = None
    if "--event" in sys.argv:
        idx = sys.argv.index("--event")
        if idx + 1 < len(sys.argv):
            event_filter = sys.argv[idx + 1]

    print(f"Parsing: {pdf_path}")
    print("=" * 80)

    meet, confidence = parse_hytek_pdf(pdf_path)

    print(f"Meet:       {meet.meet_name}")
    print(f"Dates:      {meet.meet_dates}")
    print(f"Session:    {meet.session}")
    print(f"Events:     {len(meet.events)}")
    print(f"Results:    {meet.total_results}")
    print(f"Swimmers:   {len(meet.unique_swimmers)}")
    print(f"Confidence: {confidence.score:.1%} ({'PASS' if confidence.passed else 'FAIL'})")
    for check, ok in confidence.checks.items():
        print(f"  {'✓' if ok else '✗'} {check}")
    if confidence.unmatched_lines:
        print(f"Unmatched lines ({len(confidence.unmatched_lines)}):")
        for ul in confidence.unmatched_lines[:5]:
            print(f"  ? {ul}")
    print("=" * 80)

    for event in meet.events:
        if event_filter and event.event_number != event_filter:
            continue

        print(f"\n{'─' * 80}")
        print(f"Event {event.event_number}: {event.event_name}")
        print(f"  Gender: {event.gender} | Age Group: {event.age_group} | "
              f"Distance: {event.distance}m | Stroke: {event.stroke} | "
              f"Course: {event.course}")
        print(f"  Time Standard: {event.time_standard} | Type: {event.time_type}")
        print(f"  Results: {len(event.results)}")
        print()

        # Table header
        print(f"  {'#':>4}  {'Name':<32} {'Age':>3} {'Team':<25} "
              f"{'Seed':>9} {'Time':>9} {'Q':>4} {'Status':<6}")
        print(f"  {'─'*4}  {'─'*32} {'─'*3} {'─'*25} {'─'*9} {'─'*9} {'─'*4} {'─'*6}")

        for r in event.results:
            place = "---" if r.placement is None else str(r.placement)
            if r.is_tied:
                place = f"*{place}"
            guest = "*" if r.is_guest else " "
            status = ""
            if r.is_dq:
                status = "DQ"
            elif r.is_ns:
                status = "NS"

            name_display = f"{guest}{r.name}"[:32]
            team_display = r.team[:25]

            print(f"  {place:>4}  {name_display:<32} {r.age or '-':>3} "
                  f"{team_display:<25} {_fmt_time(r.seed_time):>9} "
                  f"{_fmt_time(r.finals_time):>9} {r.qualifier or '':>4} {status:<6}")

            if verbose:
                if r.reaction_time:
                    print(f"        RT: {r.reaction_time}")
                if r.dq_code:
                    print(f"        DQ: {r.dq_code} - {r.dq_description}")
                if r.splits:
                    print(f"      {_fmt_splits(r.splits)}")

    # Summary stats
    print(f"\n{'=' * 80}")
    print("SUMMARY")
    print(f"{'=' * 80}")
    total_dq = sum(1 for e in meet.events for r in e.results if r.is_dq)
    total_ns = sum(1 for e in meet.events for r in e.results if r.is_ns)
    total_guest = sum(1 for e in meet.events for r in e.results if r.is_guest)
    total_with_splits = sum(1 for e in meet.events for r in e.results if r.splits)
    total_with_rt = sum(1 for e in meet.events for r in e.results if r.reaction_time)

    print(f"  Total Events:          {len(meet.events)}")
    print(f"  Total Results:         {meet.total_results}")
    print(f"  Unique Swimmers:       {len(meet.unique_swimmers)}")
    print(f"  Guest/Foreign:         {total_guest}")
    print(f"  DQs:                   {total_dq}")
    print(f"  No Shows:              {total_ns}")
    print(f"  Results with Splits:   {total_with_splits}")
    print(f"  Results with RT:       {total_with_rt}")

    # List all teams
    teams = sorted({r.team for e in meet.events for r in e.results})
    print(f"  Teams ({len(teams)}): {', '.join(teams[:20])}")
    if len(teams) > 20:
        print(f"    ... and {len(teams) - 20} more")
