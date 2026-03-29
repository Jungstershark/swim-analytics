"""
HY-TEK Meet Manager PDF Parser

Parses HY-TEK Meet Manager 8.0 result PDFs into structured data.
Handles: prelims, finals, splits, reaction times, DQ/NS/NT, tied placements,
guest swimmers, qualification markers (qMTS/MTS), and all age groups.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

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
    splits: list[Split] = field(default_factory=list)


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


@dataclass
class ParsedRelayLeg:
    """One leg within a relay result."""
    leg_number: int                # 1-4
    name: str
    is_guest: bool
    age: Optional[int]
    gender: Optional[str] = None   # "M" or "W" (mixed relays: "W8", "M10")
    reaction_time: Optional[str] = None  # Exchange RT
    split_time: Optional[str] = None     # Computed leg time


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


@dataclass
class ParsedMeet:
    """Top-level parsed meet data."""
    meet_name: str                 # e.g. "56th SNAG Seniors"
    meet_dates: Optional[str]      # e.g. "17/3/2026 to 22/3/2026"
    session: Optional[str]         # e.g. "Day 1 Session 1"
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

# Page header: "56th SNAG Seniors - 17/3/2026 to 22/3/2026"
RE_MEET_HEADER = re.compile(
    r"^(.+?)\s*-\s*(\d{1,2}/\d{1,2}/\d{4}\s+to\s+\d{1,2}/\d{1,2}/\d{4})$"
)

# Session line: "Results - Day 1 Session 1"
RE_SESSION = re.compile(r"^Results\s*-\s*(.+)$")

# Event header: "Event 101 Boys 13-14 200 LC Meter IM"
RE_EVENT_HEADER = re.compile(
    r"^Event\s+(\d+)\s+(.+)$"
)

# Continuation header: "Preliminaries ... (Event 101 Boys 13-14 200 LC Meter IM)"
# or just "(Event 106 Girls 13-14 1500 LC Meter Freestyle)"
RE_EVENT_CONTINUATION = re.compile(
    r"(?:Preliminaries\s*\.\.\.\s*)?\(Event\s+(\d+)\s+(.+?)\)"
)

# Time standard line: "2:47.17 13-14 MTS MTS"
RE_TIME_STANDARD = re.compile(
    r"^(\d+:[\d.]+|[\d.]+)\s+.+MTS"
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
    r"(.+?)\s+"               # name (greedy but will be trimmed)
    r"(\d{1,2})\s+"           # age
    r"(.+?)\s+"               # team
    r"([\d:]+\.[\d]+|NT)\s+"  # seed time or NT
    r"([\d:]+\.[\d]+|DQ|NS|DNF|DNS|SCR)" # finals time or status
    r"(?:\s+(qMTS|MTS))?"     # optional qualifier
)

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
    r"(.+?)\s+"                        # team name
    r"([A-Z])\s+"                      # relay letter
    r"([\d:]+\.[\d]+|NT)\s+"           # seed time
    r"(X?[\d:]+\.[\d]+|DQ|NS|DNF|DNS|SCR)"  # time (X prefix = exhibition)
)

# Relay leg line: "1) *Uhle, Ella 17 2) r:0.07 *Thai, Kayla 17 ..."
# Mixed relay: "1) *Chen, Yuejia W8 2) *Peng, Vincent M8 ..."
RE_RELAY_LEG = re.compile(
    r"(\d)\)\s+"                       # leg number
    r"(?:r:([\d.-]+)\s+)?"             # optional reaction time
    r"(\*?)([^,]+,\s*\S.*?)\s+"        # guest marker + name
    r"(?:([MW])?(\d{1,2}))"            # optional gender marker + age
)

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

    # Distance
    m = re.search(r"(\d+)\s+[LS]C\s+Meter", event_name)
    if m:
        info["distance"] = int(m.group(1))

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

    for page_text in pages_text:
        if not page_text:
            continue

        lines = page_text.split("\n")

        for i, raw_line in enumerate(lines):
            line = raw_line.strip()
            if not line:
                continue

            total_lines += 1

            # Skip page headers
            if RE_PAGE_HEADER.search(line):
                continue

            # Meet name + dates
            if not meet_name:
                m = RE_MEET_HEADER.match(line)
                if m:
                    meet_name = m.group(1).strip()
                    meet_dates = m.group(2).strip()
                    continue

            # Session
            m = RE_SESSION.match(line)
            if m:
                session = m.group(1).strip()
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
                time_type = m.group(1) or m.group(2) or m.group(3) or "Finals Time"
                if current_event:
                    current_event.time_type = time_type
                in_relay_section = False
                continue

            # Relay column header
            if RE_RELAY_COLUMN_HEADER.match(line):
                in_relay_section = True
                # Detect time type from the relay header
                if "Finals Time" in line:
                    time_type = "Finals Time"
                elif "Prelim Time" in line and "Seed Time" not in line:
                    time_type = "Prelim Time"
                else:
                    time_type = "Finals Time"
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

                    placement = None
                    if placement_str != "---":
                        placement = int(placement_str.lstrip("*"))

                    is_exhibition = time_raw.startswith("X")
                    if is_exhibition:
                        time_raw = time_raw[1:]  # strip X prefix

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

                # Guest swimmer (name starts with *)
                is_guest = name_raw.startswith("*")
                name = name_raw.lstrip("*").strip()

                # Age
                age = int(age_str) if age_str else None

                # Seed time
                if seed_time == "NT":
                    seed_time_val: Optional[str] = "NT"
                else:
                    seed_time_val = seed_time

                # Status flags
                is_dq = finals_raw == "DQ"
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
                    splits=[],
                )
                current_event.results.append(current_result)
                continue

            # Line matched nothing — track as unmatched
            # (Skip known noise: repeated meet headers, empty-ish lines, page numbers)
            if not RE_MEET_HEADER.match(line) and not line.isdigit():
                unmatched_lines.append(line)

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

                    # Compute per-leg times
                    leg_times = compute_relay_leg_times(rr.splits, num_legs=len(rr.legs) or 4)
                    for leg, lt in zip(rr.legs, leg_times):
                        if lt:
                            leg.split_time = lt

    meet = ParsedMeet(
        meet_name=meet_name,
        meet_dates=meet_dates,
        session=session,
        events=events,
    )

    classified = total_lines - len(unmatched_lines)
    confidence = compute_confidence(meet, total_lines, classified, unmatched_lines)

    return meet, confidence


# ---------------------------------------------------------------------------
# Confidence scoring
# ---------------------------------------------------------------------------

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
        return self.score >= 0.6


def compute_confidence(meet: ParsedMeet, total_lines: int, classified_lines: int,
                       unmatched_lines: list[str]) -> ConfidenceReport:
    """Score how confident we are in the parsed output."""
    checks: dict[str, bool] = {}

    # 1. Meet name extracted?
    checks["meet_name"] = bool(meet.meet_name)

    # 2. Meet dates extracted?
    checks["meet_dates"] = bool(meet.meet_dates)

    # 3. At least one event found?
    checks["has_events"] = len(meet.events) > 0

    # 4. At least one result found?
    checks["has_results"] = meet.total_results > 0

    # 5. All events have time_type set?
    checks["all_events_typed"] = all(
        ev.time_type in ("Prelim Time", "Finals Time") for ev in meet.events
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
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            pages_text.append(text or "")

    return parse_hytek_text(pages_text)


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
