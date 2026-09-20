"""
Comprehensive tests for the HY-TEK Meet Manager PDF parser.

Tests cover:
- Meet metadata extraction
- Event header parsing (gender, age group, distance, stroke, course)
- Standard result parsing (placement, name, age, team, times)
- Guest/foreign swimmer detection
- DQ detection with violation codes
- NS (No Show) handling
- Qualification markers (qMTS, MTS)
- Reaction time extraction
- Split parsing (50m, 100m, 200m, 1500m)
- Continuation pages (same event across pages)
- Time-to-seconds conversion
- Edge cases (empty input, malformed data)
"""

import os
import sys
from datetime import date
from pathlib import Path

import pytest

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import app.parsers.hytek as hytek_parser
from app.parsers.base import HyTekParser
from app.parsers.hytek import (
    ParsedEvent,
    ParsedMeet,
    ParsedResult,
    Split,
    parse_event_name,
    parse_hytek_pdf,
    parse_hytek_text,
    parse_meet_date_range,
    parse_splits_line,
    time_to_seconds,
)

# ---------------------------------------------------------------------------
# Path to the real test PDF
# ---------------------------------------------------------------------------

PDF_PATH = Path(__file__).resolve().parents[3] / ".." / "data" / "56th-snag-seniors-2026-results-day-1-session-1.pdf"
HAS_PDF = PDF_PATH.exists()
REPO_ROOT = Path(__file__).resolve().parents[4]
SNSC20_DAY2_PATH = (
    REPO_ROOT
    / "raw-data/sg-aquatics/events/20th-snsc-2025/overall_results"
    / "snsc2025-day-2-heats-results.pdf"
)
SNSC20_DAY1_PATH = (
    REPO_ROOT
    / "raw-data/sg-aquatics/events/20th-snsc-2025/overall_results"
    / "snsc2025-day-1-heats-results.pdf"
)
SNSC21_SESSION1_PATH = (
    REPO_ROOT
    / "raw-data/sg-aquatics/events/21st-snsc-2026/overall_results"
    / "21st-snsc-2026-results-day-1-session-1.pdf"
)
SSS25_FEB_DAY3_SESSION4_PATH = (
    REPO_ROOT
    / "raw-data/sg-aquatics/events/singapore-swim-series-2025/overall_results"
    / "feb-swim-series-2025-day-3-session-4-results_v2.pdf"
)


# ===========================================================================
# Unit tests: time_to_seconds
# ===========================================================================

class TestTimeToSeconds:
    def test_minutes_and_seconds(self):
        assert time_to_seconds("2:22.15") == pytest.approx(142.15)

    def test_seconds_only(self):
        assert time_to_seconds("58.42") == pytest.approx(58.42)

    def test_long_time(self):
        assert time_to_seconds("17:46.09") == pytest.approx(1066.09)

    def test_dq_returns_none(self):
        assert time_to_seconds("DQ") is None

    def test_ns_returns_none(self):
        assert time_to_seconds("NS") is None

    def test_nt_returns_none(self):
        assert time_to_seconds("NT") is None

    def test_empty_returns_none(self):
        assert time_to_seconds("") is None

    def test_none_returns_none(self):
        assert time_to_seconds(None) is None


# ===========================================================================
# Unit tests: parse_event_name
# ===========================================================================

class TestParseEventName:
    def test_boys_13_14_200_im(self):
        info = parse_event_name("Boys 13-14 200 LC Meter IM")
        assert info["gender"] == "Boys"
        assert info["age_group"] == "13-14"
        assert info["distance"] == 200
        assert info["stroke"] == "IM"
        assert info["course"] == "LC"

    def test_women_18_over_butterfly(self):
        info = parse_event_name("Women 18 & Over 200 LC Meter Butterfly")
        assert info["gender"] == "Women"
        assert info["age_group"] == "18 & Over"
        assert info["distance"] == 200
        assert info["stroke"] == "Butterfly"

    def test_men_15_17_freestyle(self):
        info = parse_event_name("Men 15-17 100 LC Meter Freestyle")
        assert info["gender"] == "Men"
        assert info["age_group"] == "15-17"
        assert info["distance"] == 100
        assert info["stroke"] == "Freestyle"

    def test_girls_50_breaststroke(self):
        info = parse_event_name("Girls 13-14 50 LC Meter Breaststroke")
        assert info["gender"] == "Girls"
        assert info["distance"] == 50
        assert info["stroke"] == "Breaststroke"

    def test_boys_11_year_olds(self):
        info = parse_event_name("Boys 11 Year Olds 1500 LC Meter Freestyle")
        assert info["gender"] == "Boys"
        assert info["age_group"] == "11 Year Olds"
        assert info["distance"] == 1500
        assert info["stroke"] == "Freestyle"

    def test_backstroke(self):
        info = parse_event_name("Boys 13-14 100 LC Meter Backstroke")
        assert info["stroke"] == "Backstroke"

    def test_sc_course(self):
        info = parse_event_name("Boys 13-14 100 SC Meter Freestyle")
        assert info["course"] == "SC"


# ===========================================================================
# Unit tests: parse_splits_line
# ===========================================================================

class TestParseSplitsLine:
    def test_standard_200m_with_rt(self):
        line = "r:+0.66 29.54 1:05.33 (35.79) 1:45.88 (40.55) 2:18.62 (32.74)"
        rt, splits = parse_splits_line(line)
        assert rt == "0.66"
        assert len(splits) == 4
        assert splits[0].cumulative_time == "29.54"
        assert splits[0].split_time is None  # first split has no delta
        assert splits[1].cumulative_time == "1:05.33"
        assert splits[1].split_time == "35.79"
        assert splits[3].cumulative_time == "2:18.62"
        assert splits[3].split_time == "32.74"

    def test_no_reaction_time(self):
        line = "30.63 1:12.33 (41.70) 1:53.80 (41.47) DQ (36.94)"
        rt, splits = parse_splits_line(line)
        assert rt is None
        assert len(splits) == 3  # DQ removed, 3 cumulative times remain
        assert splits[0].cumulative_time == "30.63"

    def test_reaction_time_only(self):
        line = "r:+0.62"
        rt, splits = parse_splits_line(line)
        assert rt == "0.62"
        assert len(splits) == 0

    def test_100m_splits(self):
        line = "r:+0.66 27.78 56.67 (28.89)"
        rt, splits = parse_splits_line(line)
        assert rt == "0.66"
        assert len(splits) == 2
        assert splits[0].cumulative_time == "27.78"
        assert splits[1].cumulative_time == "56.67"
        assert splits[1].split_time == "28.89"

    def test_1500m_continuation_splits(self):
        line = "3:18.57 (41.45) 4:00.02 (41.45) 4:41.82 (41.80) 5:24.14 (42.32)"
        rt, splits = parse_splits_line(line)
        assert rt is None
        assert len(splits) == 4
        assert splits[0].cumulative_time == "3:18.57"
        assert splits[0].split_time == "41.45"


# ===========================================================================
# Unit tests: parse_hytek_text (synthetic input)
# ===========================================================================

class TestParseHytekTextSynthetic:
    """Tests using synthetic text input to verify parsing logic."""

    SAMPLE_PAGE = """Red Dot Aquatics HY-TEK's MEET MANAGER 8.0 - 9:37 AM 18/3/2026 Page 1
56th SNAG Seniors - 17/3/2026 to 22/3/2026
Results - Day 1 Session 1
Event 101 Boys 13-14 200 LC Meter IM
2:47.17 13-14 MTS MTS
Name Age Team Seed Time Prelim Time
Preliminaries
1 WU, Dylan Jiaxu 14 Pacific Swimming Club 2:19.50 2:18.62 qMTS
r:+0.66 29.54 1:05.33 (35.79) 1:45.88 (40.55) 2:18.62 (32.74)
2 Low, Nigel 14 Chinese Swimming Club S'Pore 2:22.87 2:20.09 qMTS
r:+0.62 29.67 1:06.32 (36.65) 1:48.23 (41.91) 2:20.09 (31.86)
--- *Tao, Shoichi 14 D'Ace Seahawks (Phi) 2:28.04 DQ
SW 7.4c Hands brought back beyond the hip line during stroke - breast
r:+0.67 29.52 1:07.34 (37.82) 1:51.92 (44.58) DQ (33.63)
--- Hong, Cheng Hou 13 Swimfast Aquatic Club 3:00.90 NS"""

    def test_meet_metadata(self):
        meet, _confidence = parse_hytek_text([self.SAMPLE_PAGE])
        assert meet.meet_name == "56th SNAG Seniors"
        assert meet.meet_dates == "17/3/2026 to 22/3/2026"
        assert meet.session == "Day 1 Session 1"
        assert meet.start_date == date(2026, 3, 17)
        assert meet.end_date == date(2026, 3, 22)
        assert meet.day_number == 1
        assert meet.session_number == 1
        assert meet.metadata_conflicts == []

    def test_single_day_meet_metadata(self):
        """Some HY-TEK PDFs use one meet date instead of a date range."""
        page = """Spectrum Aquatics Swim Team HY-TEK's MEET MANAGER 8.0 - 12:48 PM 31/5/2026 Page 1
SAQ Emerging Talents Championships 2026 - 31/5/2026
Results
Event 1 Mixed 10 Year Olds 50 SC Meter Butterfly
Name Age Team Seed Time Finals Time
1 Drum, Hayden F 10 X Lab 34.42 34.02
15.72 34.02 (18.30)"""
        meet, confidence = parse_hytek_text([page])

        assert meet.meet_name == "SAQ Emerging Talents Championships 2026"
        assert meet.meet_dates == "31/5/2026"
        assert meet.start_date == date(2026, 5, 31)
        assert meet.end_date == date(2026, 5, 31)
        assert meet.day_number is None
        assert meet.session_number is None
        assert confidence.checks["meet_name"] is True
        assert confidence.checks["meet_dates"] is True

    def test_abbreviated_month_date_range_is_parsed(self):
        page = """11th SNSC SCM 2025 - 07-Nov-25 to 09-Nov-25
Results - Day 1 Session 1
Event 1 Men 50 SC Meter Freestyle
Name Age Team Seed Time Finals Time
1 Example, Athlete 20 Example Club 24.00 23.50"""

        meet, confidence = parse_hytek_text([page])

        assert meet.meet_dates == "07-Nov-25 to 09-Nov-25"
        assert meet.start_date == date(2025, 11, 7)
        assert meet.end_date == date(2025, 11, 9)
        assert confidence.checks["meet_dates"] is True

    def test_unambiguous_us_slash_date_range_is_parsed(self):
        page = """47th SEA Age 2025 - 6/25/2025 to 6/27/2025
Results - Day 1 Session 1
Event 1 Men 50 LC Meter Freestyle
Name Age Team Seed Time Finals Time
1 Example, Athlete 20 Example Club 24.00 23.50"""

        meet, confidence = parse_hytek_text([page])

        assert meet.meet_dates == "6/25/2025 to 6/27/2025"
        assert meet.start_date == date(2025, 6, 25)
        assert meet.end_date == date(2025, 6, 27)
        assert confidence.checks["meet_dates"] is True

    def test_spelled_month_date_range_is_parsed(self):
        """55th SNAG prints 'D Mon YYYY to D Mon YYYY' page headers."""
        page = """Red Dot Aquatics HY-TEK's MEET MANAGER 8.0 - 1:39 PM 16 Mar 2025 Page 37
55th SNAG Juniors - 14 Mar 2025 to 16 Mar 2025
Results - Day 1 Session 1
Event 107 Mixed 8-10 200 LC Meter Medley Relay
Team Relay Seed Time Finals Time
1 Example Club A 2:30.54 2:23.67
r:+0.67 37.32 1:19.39 (42.07) 2:02.82 (43.43) 2:23.67 (20.85)"""

        meet, confidence = parse_hytek_text([page])

        assert meet.meet_name == "55th SNAG Juniors"
        assert meet.meet_dates == "14 Mar 2025 to 16 Mar 2025"
        assert meet.start_date == date(2025, 3, 14)
        assert meet.end_date == date(2025, 3, 16)
        assert meet.session == "Day 1 Session 1"
        assert meet.day_number == 1
        assert meet.session_number == 1
        assert confidence.checks["meet_name"] is True
        assert confidence.checks["meet_dates"] is True
        assert confidence.passed is True

    def test_single_spelled_month_date_is_parsed(self):
        page = """Singapore Short Course Invitational 2026 - 29 Aug 2026
Results - Day 2 Session 4
Event 107 Women 200 SC Meter Freestyle Relay
Team Relay Seed Time Finals Time
1 Example Club A 1:50.00 1:47.00
1) Sun, Youyou 12 2) r:0.33 Tan, Alice 12 3) r:0.28 Lim, Beth 12 4) r:0.08 Ong, Cara 12
r:+0.60 25.00 52.00 (27.00) 1:19.00 (27.00) 1:47.00 (28.00)"""

        meet, confidence = parse_hytek_text([page])

        assert meet.meet_name == "Singapore Short Course Invitational 2026"
        assert meet.meet_dates == "29 Aug 2026"
        assert meet.start_date == date(2026, 8, 29)
        assert meet.end_date == date(2026, 8, 29)
        assert confidence.checks["meet_dates"] is True

    @pytest.mark.parametrize(
        "raw_value",
        [
            "14 Mar 25",          # abbreviated year stays unsupported
            "14 March 2025",      # full month name stays unsupported
            "14-Mar-2025",        # dashed four-digit year stays unsupported
            "14 Mar 2025 to 12 Mar 2025",  # reversed range
            "31 Feb 2025",        # invalid calendar day
            "14 Mar 2025 to ",    # trailing separator is not a range
        ],
    )
    def test_spelled_month_date_grammar_is_not_broadened(self, raw_value):
        assert parse_meet_date_range(raw_value) == (None, None)

    def test_repeated_spelled_month_headers_are_consistent(self):
        first_page = """55th SNAG Juniors - 14 Mar 2025 to 16 Mar 2025
Results - Day 1 Session 1
Event 1 Mixed 8-10 200 LC Meter Medley Relay
Team Relay Seed Time Finals Time
1 Example Club A 2:30.54 2:23.67
r:+0.67 37.32 1:19.39 (42.07) 2:02.82 (43.43) 2:23.67 (20.85)"""
        second_page = """55th SNAG Juniors - 14 Mar 2025 to 16 Mar 2025
Results - Day 1 Session 1"""

        meet, confidence = parse_hytek_text([first_page, second_page])

        assert meet.start_date == date(2025, 3, 14)
        assert meet.end_date == date(2025, 3, 16)
        assert meet.metadata_conflicts == []
        assert confidence.checks["meet_dates"] is True

    def test_conflicting_spelled_month_and_slash_headers_are_held(self):
        first_page = """55th SNAG Juniors - 14 Mar 2025 to 16 Mar 2025
Results - Day 1 Session 1"""
        second_page = """55th SNAG Juniors - 14/3/2025 to 16/3/2025
Results - Day 1 Session 1"""

        meet, confidence = parse_hytek_text([first_page, second_page])

        assert meet.metadata_conflicts
        assert meet.start_date is None
        assert meet.end_date is None
        assert confidence.checks["meet_dates"] is False

    def test_ambiguous_slash_date_remains_day_first(self):
        page = """Day First Meet - 5/6/2025
Results - Day 1 Session 1
Event 1 Men 50 LC Meter Freestyle
Name Age Team Seed Time Finals Time
1 Example, Athlete 20 Example Club 24.00 23.50"""

        meet, _confidence = parse_hytek_text([page])

        assert meet.start_date == date(2025, 6, 5)
        assert meet.end_date == date(2025, 6, 5)

    def test_bare_results_keeps_day_and_session_unknown(self):
        page = """HY-TEK's MEET MANAGER 8.0 Page 1
Single Day Meet - 31/5/2026
Results
Event 1 Boys 10 50 LC Meter Freestyle
Name Age Team Seed Time Finals Time
1 Example, Athlete 10 Example Club 31.00 30.00"""

        meet, confidence = parse_hytek_text([page])

        assert meet.session is None
        assert meet.day_number is None
        assert meet.session_number is None
        assert confidence.checks["session_metadata"] is True

    def test_malformed_date_is_not_treated_as_resolved(self):
        page = """HY-TEK's MEET MANAGER 8.0 Page 1
Broken Meet - 31/2/2026
Results - Day 1 Session 1
Event 1 Boys 10 50 LC Meter Freestyle
Name Age Team Seed Time Finals Time
1 Example, Athlete 10 Example Club 31.00 30.00"""

        meet, confidence = parse_hytek_text([page])

        assert meet.meet_dates == "31/2/2026"
        assert meet.start_date is None
        assert meet.end_date is None
        assert confidence.checks["meet_dates"] is False

    def test_repeated_identical_headers_are_consistent(self):
        first_page = self.SAMPLE_PAGE
        second_page = """HY-TEK's MEET MANAGER 8.0 Page 2
56th SNAG Seniors - 17/3/2026 to 22/3/2026
Results - Day 1 Session 1"""

        meet, confidence = parse_hytek_text([first_page, second_page])

        assert meet.metadata_conflicts == []
        assert confidence.checks["metadata_consistent"] is True

    def test_conflicting_page_headers_are_held(self):
        first_page = self.SAMPLE_PAGE
        second_page = """HY-TEK's MEET MANAGER 8.0 Page 2
56th SNAG Seniors - 17/3/2026 to 22/3/2026
Results - Day 2 Session 3"""

        meet, confidence = parse_hytek_text([first_page, second_page])

        assert meet.day_number is None
        assert meet.session_number is None
        assert meet.metadata_conflicts
        assert confidence.checks["metadata_consistent"] is False

    def test_session_conflict_is_sticky_and_fails_critical_confidence(self):
        pages = [
            "Example Meet - 1/6/2026 to 2/6/2026\nResults - Day 1 Session 1",
            "Example Meet - 1/6/2026 to 2/6/2026\nResults - Day 2 Session 2",
            """Example Meet - 1/6/2026 to 2/6/2026
Results - Day 2 Session 2
Event 1 Men 50 LC Meter Freestyle
Name Age Team Seed Time Finals Time
1 Example, Athlete 20 Example Club 24.00 23.50""",
        ]

        meet, confidence = parse_hytek_text(pages)

        assert meet.session is None
        assert meet.day_number is None
        assert meet.session_number is None
        assert meet.metadata_conflicts
        assert confidence.score >= 0.6
        assert confidence.passed is False

    def test_non_positive_day_or_session_fails_closed(self):
        for label in ("Day 0 Session 1", "Day 1 Session 0"):
            meet, confidence = parse_hytek_text([f"""Example Meet - 1/6/2026
Results - {label}
Event 1 Men 50 LC Meter Freestyle
Name Age Team Seed Time Finals Time
1 Example, Athlete 20 Example Club 24.00 23.50"""])

            assert confidence.checks["positive_day_session"] is False
            assert confidence.passed is False

    def test_coordinate_mode_only_detects_individual_header_without_age(self):
        assert hytek_parser._has_no_age_result_columns(
            "Name Team Seed Time Prelim Time"
        ) is True
        assert hytek_parser._has_no_age_result_columns(
            "Name Age Team Seed Time Prelim Time"
        ) is False
        assert hytek_parser._has_no_age_result_columns(
            "Team Relay Seed Time Finals Time"
        ) is False

    def test_private_use_encoded_text_is_normalized_before_parsing(self):
        plain = """Singapore Swim Series II February 2025 - 14/2/2025 to 16/2/2025
Results - Day 3 Session 4
Event 801 Girls 13-14 50 LC Meter Freestyle
Name Age Team Seed Time Finals Time
1 Example, Athlete 14 Example Club 28.00 27.50"""
        encoded = "".join(chr(ord(char) + 0xF000) if ord(char) <= 0xFF else char for char in plain)

        meet, confidence = parse_hytek_text([encoded])

        assert meet.meet_name == "Singapore Swim Series II February 2025"
        assert meet.start_date == date(2025, 2, 14)
        assert meet.total_results == 1
        assert confidence.passed is True

    def test_alphanumeric_event_token_is_retained_across_continuation(self):
        event_name = "Men 13 & Over 100 LC Meter Breaststroke"
        pages = [
            f"""Alpha Event Meet - 1/6/2026
Results - Day 1 Session 1
Event 101F {event_name}
Name Age Team Seed Time Finals Time
1 First, Athlete 18 Example Club 1:00.00 59.50""",
            f"""Alpha Event Meet - 1/6/2026
Results - Day 1 Session 1
(Event 101F {event_name})
Name Age Team Seed Time Finals Time
2 Second, Athlete 19 Example Club 1:01.00 1:00.00""",
        ]

        meet, _confidence = parse_hytek_text(pages)

        assert [(event.event_number, len(event.results)) for event in meet.events] == [("101F", 2)]

    @pytest.mark.parametrize(
        ("standard_line", "expected"),
        [
            ("2:47.17 13-14 MTS MTS", "2:47.17"),
            ("1:17.19 MTS Minimum TimeStandard", "1:17.19"),
        ],
    )
    def test_explicit_time_standard_lines_are_parsed(self, standard_line, expected):
        page = f"""Standards Meet - 1/6/2026
Results - Day 1 Session 1
Event 1 Men 50 LC Meter Freestyle
{standard_line}
Name Age Team Seed Time Prelim Time
1 Example, Athlete 20 Example Club 24.00 23.50 MTS"""

        meet, _confidence = parse_hytek_text([page])

        assert meet.events[0].time_standard == expected
        assert len(meet.events[0].results) == 1

    @pytest.mark.parametrize("placement", ["1", "12"])
    def test_placement_led_first_result_is_not_consumed_as_time_standard(self, placement):
        page = f"""Standards Meet - 1/6/2026
Results - Day 1 Session 1
Event 1 Men 50 LC Meter Freestyle
Name Age Team Seed Time Prelim Time
{placement} Example, Athlete 20 Example Club 24.00 23.50 MTS"""

        meet, _confidence = parse_hytek_text([page])

        assert meet.events[0].time_standard is None
        assert [result.name for result in meet.events[0].results] == ["Example, Athlete"]

    def test_xdq_is_dq_without_becoming_exhibition_and_retains_source_marker(self):
        page = """Singapore Swim Series I January 2025 - 18/1/2025 to 19/1/2025
Results - Day 1 Session 1
Event 1 Girls 8 Year Olds 50 LC Meter Freestyle
Name Age Team Seed Time Prelim Time
--- Xu, Ruiqi 8 Swimfast Aquatic Club NT XDQ"""

        meet, _confidence = parse_hytek_text([page])
        result = meet.events[0].results[0]

        assert result.is_dq is True
        assert result.status == "dq"
        assert result.finals_time is None
        assert result.is_guest is False
        assert result.is_exhibition is False
        assert result.raw_outcome == "XDQ"

    def test_individual_exhibition_time_is_parsed_without_split_bleed(self):
        page = """Singapore Short Course Invitational 2026 - 1/6/2026 to 2/6/2026
Results - Day 2 Session 3
Event 24 Men 200 SC Meter Freestyle
Name Age Team Seed Time Finals Time
1 Wong, Example 17 Example Club 1:48.00 1:46.00
r:+0.60 25.00 51.00 (26.00) 1:17.50 (26.50) 1:46.00 (28.50)
--- Lim, Glen 17 Example Club 1:50.00 X1:47.30
r:+0.61 25.20 51.40 (26.20) 1:18.10 (26.70) 1:47.30 (29.20)"""

        meet, confidence = parse_hytek_text([page])
        results = meet.events[0].results

        assert [result.name for result in results] == ["Wong, Example", "Lim, Glen"]
        assert results[0].finals_time == "1:46.00"
        assert results[0].is_exhibition is False
        assert len(results[0].splits) == 4
        assert results[1].finals_time == "1:47.30"
        assert results[1].is_guest is True
        assert results[1].is_exhibition is True
        assert len(results[1].splits) == 4
        assert confidence.passed is True

    def test_malformed_relay_legs_are_quarantined_not_exposed_as_swimmers(self):
        page = """Example Meet - 1/6/2026
Results - Day 1 Session 1
Event 117 Mixed 11-12 200 LC Meter Freestyle Relay
Team Relay Seed Time Finals Time
1 Example Club A 2:20.00 2:17.00
1) Ee, Emma W12 2) r:0.35 Abdul Khair, Daria Suhayr3 W) r1:02.53 Mark, Ivan Royston M11 4) r:0.27 Lim, Le Jin M12
r:+0.56 35.91 1:11.60 (35.69) 1:44.40 (32.80) 2:17.00 (32.60)"""

        meet, confidence = parse_hytek_text([page])
        relay = meet.events[0].relay_results[0]

        assert relay.leg_parse_status == "partial"
        assert relay.leg_parse_warning
        assert [leg.leg_number for leg in relay.legs] == [1, 4]
        assert relay.legs[1].split_time == "32.60"
        assert all(5 <= leg.age <= 100 for leg in relay.legs if leg.age is not None)
        assert all("r:" not in leg.name and not any(char.isdigit() for char in leg.name) for leg in relay.legs)
        assert confidence.checks["relay_leg_integrity"] is True
        assert confidence.passed is True

    def test_balanced_parenthetical_relay_swimmer_name_is_retained(self):
        page = """Singapore Short Course Invitational 2026 - 29/8/2026 to 30/8/2026
Results - Day 2 Session 4
Event 107 Women 200 SC Meter Freestyle Relay
Team Relay Seed Time Finals Time
1 Example Club A 1:50.00 1:47.00
1) Sun, Youyou (Tianyou) 12 2) r:0.33 Tan, Alice 12 3) r:0.28 Lim, Beth 12 4) r:0.08 Ong, Cara 12
r:+0.60 25.00 52.00 (27.00) 1:19.00 (27.00) 1:47.00 (28.00)"""

        meet, confidence = parse_hytek_text([page])
        relay = meet.events[0].relay_results[0]

        assert [leg.name for leg in relay.legs] == [
            "Sun, Youyou (Tianyou)",
            "Tan, Alice",
            "Lim, Beth",
            "Ong, Cara",
        ]
        assert relay.leg_parse_status == "complete"
        assert relay.leg_parse_warning is None
        assert confidence.passed is True

    @pytest.mark.parametrize(
        ("relay_line", "corrupted_name"),
        [
            (
                "1) Flosi, Kamryn 18 2) r:0.33 Sim, Si Xuan Rianne 16 "
                "3) r:0.28 Wong, Rachel, Zhuo Xuan 41)5 r:0.08 Lai, Kaelyn Edla 14",
                "Wong, Rachel, Zhuo Xuan",
            ),
            (
                "1) Loh Jing, Jairus Kaiser 16 2) r:0.34 Tan, Benjamin 17 "
                "3) r:0.50 Lim, Zhe Quan Lawrence 146) r:0.13 Teo, Bo Xuan 17",
                "Lim, Zhe Quan Lawrence",
            ),
        ],
    )
    def test_relay_column_overlap_does_not_promote_next_leg_number_as_age(
        self, relay_line, corrupted_name
    ):
        page = f"""Singapore Short Course Invitational 2026 - 29/8/2026 to 30/8/2026
Results - Day 2 Session 4
Event 107 Women 200 SC Meter Freestyle Relay
Team Relay Seed Time Finals Time
1 Example Club A 1:50.00 1:47.00
{relay_line}
r:+0.60 25.00 52.00 (27.00) 1:19.00 (27.00) 1:47.00 (28.00)"""

        meet, confidence = parse_hytek_text([page])
        relay = meet.events[0].relay_results[0]

        assert corrupted_name not in {leg.name for leg in relay.legs}
        assert relay.leg_parse_status == "partial"
        assert relay.leg_parse_warning
        assert confidence.passed is True

    def test_superimposed_leg_columns_are_reported_as_a_source_condition(self):
        """``W130)`` is ``W10`` printed under the next leg's marker ``3)``."""
        page = """55th SNAG Juniors - 14 Mar 2025 to 16 Mar 2025
Results - Day 1 Session 1
Event 107 Mixed 8-10 200 LC Meter Medley Relay
Team Relay Seed Time Finals Time
1 Example Club A 2:30.54 2:23.67
1) Nagamochi, Renji M10 2) r:0.67 Edwards, Rebecca rae W130) r:0.22 Song, Jaedan M10 4) Hua, Clara W10
r:+0.67 37.32 1:19.39 (42.07) 2:02.82 (43.43) 2:23.67 (20.85)"""

        meet, confidence = parse_hytek_text([page])
        relay = meet.events[0].relay_results[0]
        warning = relay.leg_parse_warning or ""

        assert relay.leg_parse_status == "partial"
        assert "source columns overlap in the immutable PDF" in warning
        assert warning.count("leg 2: implausible age 1") == 1
        assert [leg.leg_number for leg in relay.legs] == [1, 4]
        # The source condition is real, so completeness stays failed and no leg
        # is invented to satisfy it.
        assert confidence.checks["relay_leg_completeness"] is False
        assert confidence.passed is True

    def test_interleaved_leg_row_is_reported_as_a_source_condition(self):
        """The repo's known column-overlap row keeps a source-backed warning."""
        page = """Example Meet - 1/6/2026
Results - Day 1 Session 1
Event 117 Mixed 11-12 200 LC Meter Freestyle Relay
Team Relay Seed Time Finals Time
1 Example Club A 2:20.00 2:17.00
1) Ee, Emma W12 2) r:0.35 Abdul Khair, Daria Suhayr3 W) r1:02.53 Mark, Ivan Royston M11 4) r:0.27 Lim, Le Jin M12
r:+0.56 35.91 1:11.60 (35.69) 1:44.40 (32.80) 2:17.00 (32.60)"""

        meet, _confidence = parse_hytek_text([page])
        relay = meet.events[0].relay_results[0]

        assert relay.leg_parse_status == "partial"
        assert "source columns overlap in the immutable PDF" in (
            relay.leg_parse_warning or ""
        )

    def test_no_show_relay_is_reported_as_a_source_condition_not_a_parser_gap(self):
        """A no-show relay is printed with no leg row at all in the source."""
        page = """55th SNAG Juniors - 14 Mar 2025 to 16 Mar 2025
Results - Day 1 Session 1
Event 107 Mixed 8-10 200 LC Meter Medley Relay
Team Relay Seed Time Finals Time
--- AquaTech Swimming B NT NS"""

        meet, confidence = parse_hytek_text([page])
        relay = meet.events[0].relay_results[0]

        assert relay.status == "ns"
        assert relay.legs == []
        assert relay.leg_parse_status == "unavailable"
        assert "source prints no relay legs for a no-show relay" in (
            relay.leg_parse_warning or ""
        )
        assert confidence.checks["relay_leg_completeness"] is False
        assert confidence.passed is True

    @pytest.mark.parametrize(
        ("source_value", "expected_status"),
        [
            ("23.50", "finished"),
            ("DQ", "dq"),
            ("NS", "ns"),
            ("DNS", "dns"),
            ("DNF", "dnf"),
            ("SCR", "scratched"),
        ],
    )
    def test_individual_result_status_is_preserved(self, source_value, expected_status):
        page = f"""Status Meet - 1/6/2026
Results - Day 1 Session 1
Event 1 Men 50 LC Meter Freestyle
Name Age Team Seed Time Finals Time
--- Example, Athlete 20 Example Club 24.00 {source_value}"""

        meet, _confidence = parse_hytek_text([page])

        assert meet.events[0].results[0].status == expected_status

    @pytest.mark.parametrize(
        ("source_value", "expected_status"),
        [("1:39.00", "finished"), ("DQ", "dq"), ("DNS", "dns"), ("DNF", "dnf"), ("SCR", "scratched")],
    )
    def test_relay_result_status_is_preserved(self, source_value, expected_status):
        page = f"""Status Meet - 1/6/2026
Results - Day 1 Session 1
Event 2 Men 200 LC Meter Freestyle Relay
Team Relay Seed Time Finals Time
--- Example Club A 1:40.00 {source_value}"""

        meet, _confidence = parse_hytek_text([page])

        assert meet.events[0].relay_results[0].status == expected_status

    def test_judge_decision_relay_time_is_distinct_from_exhibition(self):
        page = """11th SNSC SCM 2025 - 07-Nov-25 to 09-Nov-25
Results - Day 1 Session 1
Event 106 Mixed 200 SC Meter Freestyle Relay
Team Relay Seed Time Finals Time
3 Nexus International School A 1:48.17 J1:45.65
--- Exhibition Club B 1:49.00 X1:46.00"""

        meet, _confidence = parse_hytek_text([page])
        judge, exhibition = meet.events[0].relay_results

        assert judge.finals_time == "1:45.65"
        assert judge.is_judge_decision is True
        assert judge.is_exhibition is False
        assert judge.raw_outcome == "J1:45.65"
        assert exhibition.finals_time == "1:46.00"
        assert exhibition.is_judge_decision is False
        assert exhibition.is_exhibition is True

    def test_relay_round_headers_distinguish_final_from_timed_final(self):
        page = """Round Meet - 1/6/2026
Results - Day 1 Session 1
Event 10 Men 200 LC Meter Freestyle Relay
Team Relay Prelim Time Finals Time
1 Final Club A 1:40.00 1:39.00
Event 11 Men 200 LC Meter Freestyle Relay
Team Relay Seed Time Finals Time
1 Timed Club A 1:42.00 1:41.00"""

        meet, _confidence = parse_hytek_text([page])

        assert meet.events[0].relay_results[0].time_type == "Finals Time"
        assert meet.events[1].relay_results[0].time_type == "Timed Final"

    def test_relay_distance_is_total_and_leg_distance_is_explicit(self):
        page = """Relay Meet - 1/6/2026
Results - Day 1 Session 1
Event 3 Mixed 11-12 4x50 SC Meter Freestyle Relay
Team Relay Seed Time Finals Time
1 Example Club A 1:50.00 1:45.00
1) One, Alpha W12 2) Two, Beta M12 3) Three, Gamma W11 4) Four, Delta M11
r:+0.50 25.00 51.00 (26.00) 1:18.00 (27.00) 1:45.00 (27.00)"""

        meet, _confidence = parse_hytek_text([page])
        event = meet.events[0]

        assert event.distance == 200
        assert event.relay_count == 4
        assert event.leg_distance == 50
        assert [split.distance for split in event.relay_results[0].splits] == [50, 100, 150, 200]

    def test_event_parsed(self):
        meet, _confidence = parse_hytek_text([self.SAMPLE_PAGE])
        assert len(meet.events) == 1
        evt = meet.events[0]
        assert evt.event_number == "101"
        assert evt.event_name == "Boys 13-14 200 LC Meter IM"
        assert evt.gender == "Boys"
        assert evt.age_group == "13-14"
        assert evt.distance == 200
        assert evt.stroke == "IM"
        assert evt.course == "LC"
        assert evt.time_standard == "2:47.17"
        assert evt.time_type == "Prelim Time"

    def test_result_count(self):
        meet, _confidence = parse_hytek_text([self.SAMPLE_PAGE])
        assert len(meet.events[0].results) == 4  # 2 normal + 1 DQ + 1 NS

    def test_first_result(self):
        meet, _confidence = parse_hytek_text([self.SAMPLE_PAGE])
        r = meet.events[0].results[0]
        assert r.placement == 1
        assert r.name == "WU, Dylan Jiaxu"
        assert r.is_guest is False
        assert r.age == 14
        assert r.team == "Pacific Swimming Club"
        assert r.seed_time == "2:19.50"
        assert r.finals_time == "2:18.62"
        assert r.qualifier == "qMTS"
        assert r.is_dq is False
        assert r.is_ns is False

    def test_first_result_reaction_time(self):
        meet, _confidence = parse_hytek_text([self.SAMPLE_PAGE])
        r = meet.events[0].results[0]
        assert r.reaction_time == "0.66"

    def test_first_result_splits(self):
        meet, _confidence = parse_hytek_text([self.SAMPLE_PAGE])
        r = meet.events[0].results[0]
        assert len(r.splits) == 4
        assert r.splits[0].cumulative_time == "29.54"
        assert r.splits[0].distance == 50
        assert r.splits[1].cumulative_time == "1:05.33"
        assert r.splits[1].split_time == "35.79"
        assert r.splits[1].distance == 100
        assert r.splits[3].cumulative_time == "2:18.62"
        assert r.splits[3].split_time == "32.74"
        assert r.splits[3].distance == 200

    def test_dq_result(self):
        meet, _confidence = parse_hytek_text([self.SAMPLE_PAGE])
        dq = meet.events[0].results[2]
        assert dq.placement is None
        assert dq.name == "Tao, Shoichi"
        assert dq.is_guest is True
        assert dq.is_dq is True
        assert dq.finals_time is None
        assert dq.dq_code == "SW 7.4c"
        assert "Hands brought back" in dq.dq_description

    def test_ns_result(self):
        meet, _confidence = parse_hytek_text([self.SAMPLE_PAGE])
        ns = meet.events[0].results[3]
        assert ns.placement is None
        assert ns.name == "Hong, Cheng Hou"
        assert ns.is_ns is True
        assert ns.finals_time is None

    def test_empty_input(self):
        meet, _confidence = parse_hytek_text([])
        assert meet.meet_name == ""
        assert len(meet.events) == 0

    def test_empty_page(self):
        meet, _confidence = parse_hytek_text(["", None, ""])
        assert len(meet.events) == 0

    def test_total_results_property(self):
        meet, _confidence = parse_hytek_text([self.SAMPLE_PAGE])
        assert meet.total_results == 4

    def test_unique_swimmers_property(self):
        meet, _confidence = parse_hytek_text([self.SAMPLE_PAGE])
        swimmers = meet.unique_swimmers
        assert len(swimmers) == 4
        assert "WU, Dylan Jiaxu" in swimmers
        assert "Hong, Cheng Hou" in swimmers


# ===========================================================================
# Integration tests: archived source PDFs
# ===========================================================================

@pytest.mark.skipif(not SNSC21_SESSION1_PATH.exists(), reason="Archived 21st SNSC PDF not found")
def test_snsc21_lone_nt_row_is_retained_as_explicit_unknown_outcome():
    meet, confidence = parse_hytek_pdf(SNSC21_SESSION1_PATH)
    matches = [
        result
        for event in meet.events
        if event.event_number == "108"
        for result in event.results
        if result.name == "Yu, Chengyou"
    ]

    assert len(matches) == 1
    result = matches[0]
    assert result.age == 17
    assert result.team == "Nexus International School"
    assert result.seed_time is None
    assert result.finals_time is None
    assert result.status == "unknown"
    assert result.raw_outcome == "NT"
    assert not any("Yu, Chengyou" in line for line in confidence.unmatched_lines)


@pytest.mark.skipif(not SNSC20_DAY1_PATH.exists(), reason="Archived 20th SNSC PDF not found")
def test_unconfirmed_lone_nt_row_remains_quarantined():
    meet, confidence = parse_hytek_pdf(SNSC20_DAY1_PATH)
    unknown_matches = [
        result
        for event in meet.events
        for result in event.results
        if result.name == "Langeveld, Wout" and result.raw_outcome == "NT"
    ]

    assert unknown_matches == []
    assert any("Langeveld, Wout" in line for line in confidence.unmatched_lines)


@pytest.mark.skipif(
    not SSS25_FEB_DAY3_SESSION4_PATH.exists(),
    reason="Archived Singapore Swim Series 2025 PDF not found",
)
def test_private_use_encoded_source_is_detected_and_parsed():
    assert HyTekParser().can_parse(SSS25_FEB_DAY3_SESSION4_PATH) is True

    meet, confidence = parse_hytek_pdf(SSS25_FEB_DAY3_SESSION4_PATH)

    assert meet.meet_name == "Singapore Swim Series II February 2025"
    assert meet.session == "Day 3 Session 4"
    assert meet.total_results == 1164
    assert meet.total_relay_results == 0
    assert confidence.passed is True

@pytest.mark.skipif(not SNSC20_DAY2_PATH.exists(), reason="Archived 20th SNSC PDF not found")
def test_snsc20_day2_no_age_layout_uses_coordinate_columns_safely():
    meet, confidence = parse_hytek_pdf(SNSC20_DAY2_PATH)
    counts = {event.event_number: len(event.results) for event in meet.events}
    results = [result for event in meet.events for result in event.results]

    assert counts == {
        "201": 61,
        "202": 49,
        "203": 96,
        "204": 79,
        "205": 64,
        "206": 62,
        "207": 26,
        "208": 19,
    }
    assert len(results) == 456
    assert all(result.age is None for result in results)
    assert not any(result.name == "Midsayap Pirates Team" and result.age == 7 for result in results)
    assert not any(result.name == "Kate Ona" for result in results)
    assert any("Kate Ona" in line and "missing outcome" in line for line in confidence.unmatched_lines)


# ===========================================================================
# Source-backed relay column overlap (immutable source condition, not a parser
# gap): the PDF prints adjacent leg columns on top of each other.
# ===========================================================================

SNAG55_JUNIORS_J1_PATH = (
    REPO_ROOT
    / "raw-data/sg-aquatics/events/55th-snag-2025/overall_results"
    / "55th-snag-juniors-results-j1-day-1-session-1-16-march-2025.pdf"
)


@pytest.mark.parametrize(
    ("source_lines", "expected_phrase"),
    [
        # Observed superimposed rows in 55th SNAG Juniors Day 1 Session 1.
        (
            [
                "1) Nagamochi, Renji M10 2) r:0.67 Edwards, Rebecca rae W130) "
                "r:0.22 Song, Jaedan M10 4) Hua, Clara W10"
            ],
            "source columns overlap in the immutable PDF",
        ),
        (
            [
                "1) Loh Xing, Jamiel Raiyan M10 2) r:0.33 Chua, Hao Xiang M10 "
                "3) r:0.29 Lam, Mikayla Joan Xin Ya W4)1 G0u, Jia Yu W10"
            ],
            "source columns overlap in the immutable PDF",
        ),
        (
            [
                "1) Lau Xuan Zhi, Elijah M10 2) Suang Keng, Lim W9 "
                "3) r:0.10 Tan Zong Xian, George M94) Dai, Qixuan W9"
            ],
            "source columns overlap in the immutable PDF",
        ),
        (
            [
                "1) Ng, Garrett Jun Chang M9 2) r:0.08 Schlager, Leon Alexander "
                "3M)9 r:0.04 Joshua, Kiara W10 4) r:0.33 Lau, Wan Xuan Celine W10"
            ],
            "source columns overlap in the immutable PDF",
        ),
        # Gender-less age token with the next marker drawn over it: `146)` is
        # age `16` plus marker `4)`.
        (
            [
                "1) Loh Jing, Jairus Kaiser 16 2) r:0.34 Tan, Benjamin 17 "
                "3) r:0.50 Lim, Zhe Quan Lawrence 146) r:0.13 Teo, Bo Xuan 17"
            ],
            "source columns overlap in the immutable PDF",
        ),
        # Whole-row superimposition: glyphs of another row land inside names.
        (
            [
                "1) *Septionus, Samuel Maxson 17 2) *Andoko, Liquor Harrison 18 "
                "3) *Ganesha Damanik, Jeremy Elyon4) M *Fasattehro 1n8i, Erick Ahmad 25"
            ],
            "source columns overlap in the immutable PDF",
        ),
        # Digits fused inside name tokens: the row is superimposed text.
        (
            [
                "1) *Widjaja, Stephen Gerald M12 2) r:0.51 *Afandi, Nabhan "
                "Aldebara3n) Mr:102.32 *Mulyadi, Hayuningtyas E4lo)k r :W0.1620 "
                "*Hariyanto, Jane Audrey W11"
            ],
            "source columns overlap in the immutable PDF",
        ),
        # The printed row stops at marker 3): the fourth leg never printed.
        (
            [
                "1) Cortes, Frank Sebastian 17 2) r:0.34 Sison, Brendan 17 "
                "3) r:0.40 Ramirez, Santiago Emma Titus 14"
            ],
            "source row does not print all four leg markers",
        ),
        # The source prints a second leg row that no relay row introduces.
        (
            [
                "1) Yang, Francesca, Wenxian W21 2) Goh, Yu Heng Ashton M19 "
                "3) Lim, Jun Feng Keagan M20 4) Wu, Yujia Eugenia W20",
                "1) Tan, Ella Grace W15 2) Yeo, Tze Wei Andrew M15 "
                "3) Ung, Luke M15 4) David, Callie-Ann Sim S W14",
            ],
            "source prints more leg fields than one relay row can own",
        ),
        # A clean, complete source row carries no source defect at all.
        (
            [
                "1) Ee, Emma W12 2) r:0.33 Tan, Alice 12 3) r:0.28 Lim, Beth 12 "
                "4) r:0.08 Ong, Cara 12"
            ],
            None,
        ),
        ([""], None),
        (None, None),
    ],
)
def test_relay_quarantine_source_reason_only_reports_source_evidence(
    source_lines, expected_phrase
):
    reason = hytek_parser.relay_leg_quarantine_source_reason(source_lines)

    if expected_phrase is None:
        assert reason is None
    else:
        assert reason is not None
        assert expected_phrase in reason


@pytest.mark.skipif(
    not SNAG55_JUNIORS_J1_PATH.exists(), reason="Archived 55th SNAG PDF not found"
)
def test_snag55_juniors_superimposed_relay_legs_stay_quarantined():
    meet, confidence = parse_hytek_pdf(SNAG55_JUNIORS_J1_PATH)

    # The header date grammar resolves the D Mon YYYY range on this source.
    assert meet.meet_name == "55th SNAG Juniors"
    assert meet.meet_dates == "14 Mar 2025 to 16 Mar 2025"
    assert meet.start_date == date(2025, 3, 14)
    assert meet.end_date == date(2025, 3, 16)
    assert (meet.day_number, meet.session_number) == (1, 1)
    assert confidence.checks["meet_name"] is True
    assert confidence.checks["meet_dates"] is True
    assert confidence.passed is True

    relays = [relay for event in meet.events for relay in event.relay_results]
    quarantined = [relay for relay in relays if relay.leg_parse_status != "complete"]

    assert quarantined, "source overlap condition vanished; re-verify the immutable PDF"
    for relay in quarantined:
        warning = relay.leg_parse_warning or ""
        assert relay.leg_parse_status in {"partial", "unavailable"}
        assert (
            "source columns overlap in the immutable PDF" in warning
            or "source row does not print all four leg markers" in warning
            or "source prints no relay legs for a no-show relay" in warning
        ), warning
        assert all(leg.leg_number in {1, 2, 3, 4} for leg in relay.legs)
        assert all(5 <= leg.age <= 100 for leg in relay.legs if leg.age is not None)
        assert all(
            leg.name and not any(char.isdigit() for char in leg.name) for leg in relay.legs
        )

    # Genuine source incompleteness: the check stays failed and the parser never
    # invents the missing legs to make it pass.
    assert confidence.checks["relay_leg_completeness"] is False


# ===========================================================================
# Integration tests: real PDF (skip if not present)
# ===========================================================================

@pytest.mark.skipif(not HAS_PDF, reason="Test PDF not found")
class TestRealPDF:
    """Integration tests against the real 56th SNAG Seniors PDF."""

    @pytest.fixture(scope="class")
    def parsed(self):
        return parse_hytek_pdf(PDF_PATH)

    @pytest.fixture(scope="class")
    def meet(self, parsed):
        return parsed[0]

    @pytest.fixture(scope="class")
    def confidence(self, parsed):
        return parsed[1]

    def test_meet_name(self, meet):
        assert meet.meet_name == "56th SNAG Seniors"

    def test_meet_dates(self, meet):
        assert "17/3/2026" in meet.meet_dates
        assert "22/3/2026" in meet.meet_dates

    def test_confidence_passes(self, confidence):
        assert confidence.passed
        assert confidence.score >= 0.6

    def test_session(self, meet):
        assert meet.session == "Day 1 Session 1"

    def test_event_count(self, meet):
        assert len(meet.events) == 19

    def test_total_results(self, meet):
        assert meet.total_results > 800

    def test_unique_swimmers(self, meet):
        assert len(meet.unique_swimmers) > 600

    # --- Event 101: Boys 13-14 200 LC Meter IM ---

    def test_event_101_boys_exists(self, meet):
        evt = self._find_event(meet, "101", "Boys 13-14")
        assert evt is not None
        assert evt.event_name == "Boys 13-14 200 LC Meter IM"
        assert evt.gender == "Boys"
        assert evt.age_group == "13-14"
        assert evt.distance == 200
        assert evt.stroke == "IM"

    def test_event_101_boys_first_place(self, meet):
        evt = self._find_event(meet, "101", "Boys 13-14")
        first = evt.results[0]
        assert first.placement == 1
        assert first.name == "WU, Dylan Jiaxu"
        assert first.age == 14
        assert first.team == "Pacific Swimming Club"
        assert first.seed_time == "2:19.50"
        assert first.finals_time == "2:18.62"
        assert first.qualifier == "qMTS"
        assert first.reaction_time == "0.66"

    def test_event_101_boys_splits(self, meet):
        evt = self._find_event(meet, "101", "Boys 13-14")
        first = evt.results[0]
        assert len(first.splits) == 4  # 200m = 4 x 50m
        assert first.splits[0].distance == 50
        assert first.splits[3].distance == 200

    def test_event_101_boys_guest_swimmer(self, meet):
        evt = self._find_event(meet, "101", "Boys 13-14")
        guests = [r for r in evt.results if r.is_guest]
        assert len(guests) > 0
        # Cammer, Lansen should be a guest
        cammer = next((r for r in guests if "Cammer" in r.name), None)
        assert cammer is not None
        assert cammer.team == "Olympians Swimming (Can)"

    def test_event_101_boys_dqs(self, meet):
        evt = self._find_event(meet, "101", "Boys 13-14")
        dqs = [r for r in evt.results if r.is_dq]
        assert len(dqs) == 7
        # Check one specific DQ
        tao = next((r for r in dqs if "Tao" in r.name), None)
        assert tao is not None
        assert tao.dq_code == "SW 7.4c"
        assert "breast" in tao.dq_description.lower()

    def test_event_101_boys_ns(self, meet):
        evt = self._find_event(meet, "101", "Boys 13-14")
        ns = [r for r in evt.results if r.is_ns]
        assert len(ns) >= 1
        assert any("Hong" in r.name for r in ns)

    # --- Event 101: Men 15-17 200 LC Meter IM ---

    def test_event_101_men_15_17_exists(self, meet):
        evt = self._find_event(meet, "101", "Men 15-17")
        assert evt is not None
        assert evt.gender == "Men"
        assert evt.age_group == "15-17"

    def test_event_101_men_15_17_first_place(self, meet):
        evt = self._find_event(meet, "101", "Men 15-17")
        first = evt.results[0]
        assert first.placement == 1
        assert "Yosuke" in first.name or "Sato" in first.name
        assert first.is_guest is True  # Japan swimmer

    # --- Event 103: Boys 13-14 100 LC Meter Freestyle ---

    def test_event_103_boys_100_free(self, meet):
        evt = self._find_event(meet, "103", "Boys 13-14")
        assert evt is not None
        assert evt.distance == 100
        assert evt.stroke == "Freestyle"
        assert len(evt.results) > 80

    def test_event_103_100m_has_2_splits(self, meet):
        evt = self._find_event(meet, "103", "Boys 13-14")
        first = evt.results[0]
        assert len(first.splits) == 2  # 100m = 2 x 50m

    # --- Event 104: 50m Breaststroke ---

    def test_event_104_50m_breaststroke(self, meet):
        evt = self._find_event(meet, "104", "Girls 13-14")
        assert evt is not None
        assert evt.distance == 50
        assert evt.stroke == "Breaststroke"

    # --- Event 106/108: 1500m Freestyle ---

    def test_event_1500m_exists(self, meet):
        evt = self._find_event(meet, "106", "Girls 13-14")
        assert evt is not None
        assert evt.distance == 1500
        assert evt.stroke == "Freestyle"

    def test_event_1500m_has_many_splits(self, meet):
        evt = self._find_event(meet, "106", "Girls 13-14")
        first = evt.results[0]
        # 1500m should have 30 splits (30 x 50m)
        assert len(first.splits) >= 20  # Allow some flexibility

    # --- Cross-cutting checks ---

    def test_all_normal_results_have_times(self, meet):
        """Every non-DQ, non-NS result should have a finals time."""
        for evt in meet.events:
            for r in evt.results:
                if not r.is_dq and not r.is_ns:
                    assert r.finals_time is not None, (
                        f"Event {evt.event_number} {evt.event_name}: "
                        f"{r.name} has no finals_time"
                    )

    def test_all_normal_results_have_placement(self, meet):
        """Every non-DQ, non-NS result should have a placement."""
        for evt in meet.events:
            for r in evt.results:
                if not r.is_dq and not r.is_ns:
                    assert r.placement is not None, (
                        f"Event {evt.event_number}: {r.name} missing placement"
                    )

    def test_all_results_have_name_and_team(self, meet):
        for evt in meet.events:
            for r in evt.results:
                assert r.name, f"Event {evt.event_number}: result missing name"
                assert r.team, f"Event {evt.event_number}: {r.name} missing team"

    def test_all_results_have_age(self, meet):
        for evt in meet.events:
            for r in evt.results:
                assert r.age is not None, f"Event {evt.event_number}: {r.name} missing age"
                assert 8 <= r.age <= 99, f"Unreasonable age {r.age} for {r.name}"

    def test_dq_results_have_codes(self, meet):
        """Every DQ result should have a DQ code."""
        for evt in meet.events:
            for r in evt.results:
                if r.is_dq:
                    assert r.dq_code is not None, (
                        f"Event {evt.event_number}: {r.name} DQ without code"
                    )

    def test_no_duplicate_results_per_event(self, meet):
        """Same swimmer shouldn't appear twice in the same event."""
        for evt in meet.events:
            names = [r.name for r in evt.results]
            assert len(names) == len(set(names)), (
                f"Event {evt.event_number} {evt.event_name}: duplicate swimmers found"
            )

    def test_qualifier_distribution(self, meet):
        """Check qMTS and MTS qualifiers are present."""
        all_qualifiers = [r.qualifier for e in meet.events for r in e.results if r.qualifier]
        assert "qMTS" in all_qualifiers
        assert "MTS" in all_qualifiers

    def test_guest_swimmers_detected(self, meet):
        guests = [r for e in meet.events for r in e.results if r.is_guest]
        assert len(guests) > 100  # This PDF has many international swimmers

    def test_reaction_times_present(self, meet):
        with_rt = [r for e in meet.events for r in e.results if r.reaction_time]
        assert len(with_rt) > 700

    # --- Helper ---

    @staticmethod
    def _find_event(meet: ParsedMeet, event_num: str, name_contains: str) -> ParsedEvent:
        for evt in meet.events:
            if evt.event_number == event_num and name_contains in evt.event_name:
                return evt
        return None


# ===========================================================================
# Run with __main__
# ===========================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
