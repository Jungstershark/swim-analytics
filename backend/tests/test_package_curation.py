"""Fail-closed canonical document and parsed-row curation tests."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path

import pytest

from app.package_curation import (
    PackageCurationError,
    apply_package_curation,
    load_manifest_curation_policy,
    load_package_curation,
    select_manifest_records,
)
from app.package_import import (
    ParsedCompetitionDocument,
    _preflight_documents,
    parse_competition_manifest,
)
from app.parsers.hytek import ConfidenceReport, parse_hytek_text


def _document(filename: str, source_sha: str, body: str) -> ParsedCompetitionDocument:
    parsed, confidence = parse_hytek_text([body])
    content = f"%PDF-1.4\n{filename}\n%%EOF".encode()
    return ParsedCompetitionDocument(
        filename=filename,
        source_url=f"https://example.test/{filename}",
        content=content,
        sha256=source_sha,
        parsed=parsed,
        parser_name="hytek",
        parser_version="test",
        confidence_score=confidence.score,
    )


def _write_policy(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / "curation.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _base_policy(*, documents: list[dict], rules: list[dict] | None = None,
                 individual: int = 1, relay: int = 0) -> dict:
    return {
        "version": 1,
        "package_id": "fixture",
        "source_page": "https://example.test/competition",
        "status": "ready",
        "documents": documents,
        "shared_evidence": [],
        "rules": rules or [],
        "expected": {
            "documents": len(documents),
            "individual_results": individual,
            "relay_results": relay,
        },
    }


def test_document_selection_is_sha_based_and_can_explicitly_select_other_pdf(tmp_path: Path):
    chosen = "a" * 64
    ignored = "b" * 64
    policy = load_package_curation(_write_policy(tmp_path, _base_policy(documents=[{
        "filename": "misclassified-results.pdf",
        "sha256": chosen,
        "category": "other_pdf",
    }])))
    manifest = {
        "source_page": "HTTPS://EXAMPLE.TEST/competition/#results",
        "files": [
            {"filename": "ignored.pdf", "sha256": ignored, "category": "overall_results"},
            {"filename": "misclassified-results.pdf", "sha256": chosen, "category": "other_pdf"},
        ],
    }

    selected = select_manifest_records(manifest, policy)

    assert [row["sha256"] for row in selected] == [chosen]


def test_document_selection_rejects_absent_and_duplicate_source_hashes(tmp_path: Path):
    chosen = "a" * 64
    policy = load_package_curation(_write_policy(tmp_path, _base_policy(documents=[{
        "filename": "result.pdf", "sha256": chosen, "category": "overall_results",
    }])))

    with pytest.raises(PackageCurationError, match="absent"):
        select_manifest_records({
            "source_page": "https://example.test/competition",
            "files": [],
        }, policy)

    duplicate = {"filename": "result.pdf", "sha256": chosen, "category": "overall_results"}
    with pytest.raises(PackageCurationError, match="duplicate"):
        select_manifest_records({
            "source_page": "https://example.test/competition",
            "files": [duplicate, dict(duplicate)],
        }, policy)


def test_policy_rejects_duplicate_allowlisted_hash(tmp_path: Path):
    chosen = "a" * 64
    payload = _base_policy(documents=[
        {"filename": "one.pdf", "sha256": chosen, "category": "overall_results"},
        {"filename": "two.pdf", "sha256": chosen, "category": "overall_results"},
    ])

    with pytest.raises(PackageCurationError, match="duplicate allowlisted SHA-256"):
        load_package_curation(_write_policy(tmp_path, payload))


def test_semantic_rules_curate_copies_and_enforce_rule_and_final_cardinality(tmp_path: Path):
    source_sha = "a" * 64
    document = _document("session.pdf", source_sha, """Fixture Meet - 1/6/2026
Results - Day 1 Session 1
Event 1 Men 50 SC Meter Freestyle
Name Age Team Seed Time Finals Time
1 Keep, One 20 Club 24.00 23.00
Event 2 Men 100 SC Meter Freestyle
Name Age Team Seed Time Finals Time
1 Drop, One 20 Club 52.00 51.00
2 Drop, Two 20 Club 53.00 52.00""")
    before = deepcopy(document.parsed)
    policy = load_package_curation(_write_policy(tmp_path, _base_policy(
        documents=[{"filename": "session.pdf", "sha256": source_sha, "category": "overall_results"}],
        rules=[{
            "id": "drop-cumulative-event",
            "source_sha256": source_sha,
            "row_kind": "individual",
            "action": "exclude",
            "match": {"event_number": "2", "round": "Timed Final"},
            "expected_matches": 2,
        }],
        individual=1,
    )))

    curated, report = apply_package_curation((document,), policy)

    assert curated[0].parsed.total_results == 1
    assert curated[0].parsed.events[0].results[0].name == "Keep, One"
    assert document.parsed == before
    assert curated[0].parsed is not document.parsed
    assert report.rule_matches == {"drop-cumulative-event": 2}
    assert report.individual_results == 1


def test_include_rules_default_their_source_and_kind_to_excluded(tmp_path: Path):
    source_sha = "a" * 64
    document = _document("supplement.pdf", source_sha, """Fixture Meet - 1/6/2026
Results - Day 1 Session 1
Event 10 Men 200 SC Meter Freestyle Relay
Team Relay Seed Time Finals Time
1 Keep Club A 1:42.00 1:41.00
Event 11 Men 200 SC Meter Medley Relay
Team Relay Seed Time Finals Time
1 Drop Club A 1:52.00 1:51.00""")
    policy = load_package_curation(_write_policy(tmp_path, _base_policy(
        documents=[{"filename": "supplement.pdf", "sha256": source_sha, "category": "overall_results"}],
        rules=[{
            "id": "only-direct-relay",
            "source_sha256": source_sha,
            "row_kind": "relay",
            "action": "include",
            "match": {"event_number": "10"},
            "expected_matches": 1,
        }],
        individual=0,
        relay=1,
    )))

    curated, _report = apply_package_curation((document,), policy)

    assert curated[0].parsed.total_relay_results == 1
    assert curated[0].parsed.events[0].relay_results[0].team_name == "Keep Club"


def test_cross_source_duplicate_rule_uses_semantic_identity_not_placement(tmp_path: Path):
    origin_sha = "a" * 64
    ranking_sha = "b" * 64
    origin = _document("origin.pdf", origin_sha, """Fixture Meet - 1/6/2026
Results - Day 1 Session 1
Event 10 Men 50 SC Meter Freestyle
Name Age Team Seed Time Finals Time
1 Same, Athlete 20 Club 24.00 23.00""")
    ranking = _document("ranking.pdf", ranking_sha, """Fixture Meet - 1/6/2026
Results - Day 1 Session 2
Event 10 Men 50 SC Meter Freestyle
Name Age Team Seed Time Finals Time
2 Same, Athlete 20 Club 24.00 23.00
3 Unique, Athlete 20 Club 25.00 24.00""")
    policy = load_package_curation(_write_policy(tmp_path, _base_policy(
        documents=[
            {"filename": "origin.pdf", "sha256": origin_sha, "category": "overall_results"},
            {"filename": "ranking.pdf", "sha256": ranking_sha, "category": "overall_results"},
        ],
        rules=[{
            "id": "ranking-reprint",
            "source_sha256": ranking_sha,
            "row_kind": "individual",
            "action": "exclude",
            "match": {
                "event_number": "10",
                "duplicate_of_source_sha256": origin_sha,
            },
            "expected_matches": 1,
        }],
        individual=2,
    )))

    curated, report = apply_package_curation((origin, ranking), policy)

    assert [row.name for row in curated[1].parsed.events[0].results] == ["Unique, Athlete"]
    assert report.rule_matches == {"ranking-reprint": 1}


def test_individual_exhibition_rule_excludes_only_source_backed_exhibition_row(tmp_path: Path):
    source_sha = "a" * 64
    document = _document("session.pdf", source_sha, """Fixture Meet - 1/6/2026
Results - Day 1 Session 1
Event 1 Men 50 SC Meter Freestyle
Name Age Team Seed Time Finals Time
1 Keep, One 20 Club 24.00 23.00
--- Exhibition, One 20 Club 25.00 X24.00""")
    policy = load_package_curation(_write_policy(tmp_path, _base_policy(
        documents=[{"filename": "session.pdf", "sha256": source_sha, "category": "overall_results"}],
        rules=[{
            "id": "exclude-individual-exhibition",
            "source_sha256": source_sha,
            "row_kind": "individual",
            "action": "exclude",
            "match": {"event_number": "1", "is_exhibition": True},
            "expected_matches": 1,
        }],
        individual=1,
    )))

    curated, report = apply_package_curation((document,), policy)

    assert document.parsed.events[0].results[0].is_exhibition is False
    assert document.parsed.events[0].results[1].is_exhibition is True
    assert [row.name for row in curated[0].parsed.events[0].results] == ["Keep, One"]
    assert report.rule_matches == {"exclude-individual-exhibition": 1}


def test_cross_source_identity_distinguishes_individual_exhibition_provenance(tmp_path: Path):
    origin_sha = "a" * 64
    exhibition_sha = "b" * 64
    origin = _document("origin.pdf", origin_sha, """Fixture Meet - 1/6/2026
Results - Day 1 Session 1
Event 10 Men 50 SC Meter Freestyle
Name Age Team Seed Time Finals Time
1 Same, Athlete 20 Club 24.00 23.00""")
    exhibition = _document("exhibition.pdf", exhibition_sha, """Fixture Meet - 1/6/2026
Results - Day 1 Session 2
Event 10 Men 50 SC Meter Freestyle
Name Age Team Seed Time Finals Time
--- Same, Athlete 20 Club 24.00 X23.00""")
    policy = load_package_curation(_write_policy(tmp_path, _base_policy(
        documents=[
            {"filename": "origin.pdf", "sha256": origin_sha, "category": "overall_results"},
            {"filename": "exhibition.pdf", "sha256": exhibition_sha, "category": "overall_results"},
        ],
        rules=[{
            "id": "not-a-reprint",
            "source_sha256": exhibition_sha,
            "row_kind": "individual",
            "action": "exclude",
            "match": {
                "event_number": "10",
                "duplicate_of_source_sha256": origin_sha,
            },
            "expected_matches": 0,
        }],
        individual=2,
    )))

    curated, report = apply_package_curation((origin, exhibition), policy)

    assert report.rule_matches == {"not-a-reprint": 0}
    assert curated[0].parsed.events[0].results[0].is_exhibition is False
    assert curated[1].parsed.events[0].results[0].is_exhibition is True


def test_curation_fails_closed_on_rule_or_final_count_mismatch(tmp_path: Path):
    source_sha = "a" * 64
    document = _document("session.pdf", source_sha, """Fixture Meet - 1/6/2026
Results - Day 1 Session 1
Event 1 Men 50 SC Meter Freestyle
Name Age Team Seed Time Finals Time
1 Keep, One 20 Club 24.00 23.00""")
    bad_rule = _base_policy(
        documents=[{"filename": "session.pdf", "sha256": source_sha, "category": "overall_results"}],
        rules=[{
            "id": "wrong-cardinality", "source_sha256": source_sha,
            "row_kind": "individual", "action": "exclude",
            "match": {"event_number": "1"}, "expected_matches": 2,
        }],
        individual=0,
    )
    with pytest.raises(PackageCurationError, match="wrong-cardinality.*expected 2.*observed 1"):
        apply_package_curation((document,), load_package_curation(_write_policy(tmp_path, bad_rule)))

    bad_total = _base_policy(
        documents=[{"filename": "session.pdf", "sha256": source_sha, "category": "overall_results"}],
        individual=2,
    )
    with pytest.raises(PackageCurationError, match="final individual_results.*expected 2.*observed 1"):
        apply_package_curation((document,), load_package_curation(_write_policy(tmp_path, bad_total)))


def test_parse_manifest_uses_policy_for_selection_and_row_curation(tmp_path: Path):
    selected_bytes = b"%PDF-1.4\nselected\n%%EOF"
    ignored_bytes = b"%PDF-1.4\nignored\n%%EOF"
    selected_sha = hashlib.sha256(selected_bytes).hexdigest()
    ignored_sha = hashlib.sha256(ignored_bytes).hexdigest()
    selected_path = tmp_path / "selected.pdf"
    ignored_path = tmp_path / "ignored.pdf"
    selected_path.write_bytes(selected_bytes)
    ignored_path.write_bytes(ignored_bytes)
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps({
        "source_page": "https://example.test/competition",
        "files": [
            {
                "filename": "ignored.pdf", "saved": str(ignored_path),
                "sha256": ignored_sha, "category": "overall_results",
            },
            {
                "filename": "selected.pdf", "saved": str(selected_path),
                "sha256": selected_sha, "category": "other_pdf",
            },
        ],
    }), encoding="utf-8")
    policy = load_package_curation(_write_policy(tmp_path, _base_policy(
        documents=[{
            "filename": "selected.pdf", "sha256": selected_sha, "category": "other_pdf",
        }],
    )))
    parsed = parse_hytek_text(["""Fixture Meet - 1/6/2026
Results - Day 1 Session 1
Event 1 Men 50 SC Meter Freestyle
Name Age Team Seed Time Finals Time
1 Keep, One 20 Club 24.00 23.00"""])[0]
    parsed_paths: list[Path] = []

    def fake_parser(path: Path):
        parsed_paths.append(path)
        return parsed, ConfidenceReport(score=1.0, checks={"fixture": True}), "hytek", "test"

    package = parse_competition_manifest(
        manifest_path,
        package_root=tmp_path,
        path_root=tmp_path,
        parser=fake_parser,
        curation_policy=policy,
    )

    assert [document.sha256 for document in package.documents] == [selected_sha]
    assert package.curation_report is not None
    assert package.curation_report.individual_results == 1
    assert len(parsed_paths) == 1


def test_policy_curated_documents_can_intentionally_share_a_session(tmp_path: Path):
    body = """Fixture Meet - 1/6/2026
Results - Day 1 Session 1
Event 1 Men 50 SC Meter Freestyle
Name Age Team Seed Time Finals Time
1 Keep, One 20 Club 24.00 23.00"""
    one_content = b"%PDF-1.4\none.pdf\n%%EOF"
    two_content = b"%PDF-1.4\ntwo.pdf\n%%EOF"
    one_sha = hashlib.sha256(one_content).hexdigest()
    two_sha = hashlib.sha256(two_content).hexdigest()
    one = _document("one.pdf", one_sha, body)
    two = _document("two.pdf", two_sha, body)
    policy = load_package_curation(_write_policy(tmp_path, _base_policy(
        documents=[
            {"filename": "one.pdf", "sha256": one_sha, "category": "overall_results"},
            {"filename": "two.pdf", "sha256": two_sha, "category": "overall_results"},
        ],
        individual=2,
    )))

    with pytest.raises(ValueError, match="Multiple result documents claim"):
        _preflight_documents((one, two))

    # Sharing a package is not authorisation: the policy has to name the pair.
    curated, _report = apply_package_curation((one, two), policy)
    with pytest.raises(ValueError, match="does not declare them as an overlapping pair"):
        _preflight_documents(curated)

    declaring = load_package_curation(_write_policy(tmp_path, _base_policy(
        documents=[
            {"filename": "one.pdf", "sha256": one_sha, "category": "overall_results"},
            {"filename": "two.pdf", "sha256": two_sha, "category": "overall_results"},
        ],
        individual=2,
    ) | {"shared_evidence": [{"documents": ["one.pdf", "two.pdf"]}]}))

    curated, _report = apply_package_curation((one, two), declaring)
    _preflight_documents(curated)


def test_unresolved_policy_always_fails_closed(tmp_path: Path):
    policy = load_package_curation(_write_policy(tmp_path, {
        "version": 1,
        "package_id": "unresolved-fixture",
        "source_page": "https://example.test/unresolved",
        "status": "unresolved",
        "reason": "canonical evidence is incomplete",
    }))

    with pytest.raises(PackageCurationError, match="canonical evidence is incomplete"):
        select_manifest_records({
            "source_page": "https://example.test/unresolved",
            "files": [],
        }, policy)


def _repository_policy_cases() -> dict[str, dict]:
    event_prefix = Path("raw-data/sg-aquatics/events")
    return {
        "11th-singapore-national-swimming-championships-25m-2025": {
            "manifest": event_prefix / "11th-singapore-national-swimming-championships-25m-2025/manifest.json",
            "status": "ready",
            "expected": (5, 2154, 88),
        },
        "20th-snsc-2025": {
            "manifest": event_prefix / "20th-snsc-2025/manifest.json",
            "status": "ready",
            "expected": (8, 2636, 67),
        },
        "21st-snsc-2026": {
            "manifest": event_prefix / "21st-snsc-2026/manifest.json",
            "status": "ready",
            "expected": (8, 3540, 53),
        },
        "47th-sea-age-group-aquatics-championships": {
            "manifest": event_prefix / "47th-sea-age-group-aquatics-championships/manifest.json",
            "status": "ready",
            "expected": (3, 1410, 48),
        },
        "55th-snag-2025": {
            "manifest": event_prefix / "55th-snag-2025/manifest.json",
            "status": "ready",
            "expected": (18, 10876, 315),
        },
        "56th-snag-2026-full": {
            "manifest": Path("raw-data/sg-aquatics/56th-snag-2026-full/manifest.json"),
            "status": "ready",
            "expected": (17, 10906, 348),
        },
        "saq-etp-championships-2026": {
            "manifest": event_prefix / "saq-etp-championships-2026/manifest.json",
            "status": "ready",
            "expected": (1, 410, 0),
        },
        "singapore-short-course-invitational-2026": {
            "manifest": event_prefix / "singapore-short-course-invitational-2026/manifest.json",
            "status": "ready",
            "expected": (4, 1419, 42),
        },
        "singapore-swim-series-2025": {
            "manifest": event_prefix / "singapore-swim-series-2025/manifest.json",
            "status": "ready",
            "expected": (10, 9043, 0),
        },
        "singapore-swim-series-2026": {
            "manifest": event_prefix / "singapore-swim-series-2026/manifest.json",
            "status": "ready",
            "expected": (12, 9204, 0),
        },
    }


def test_repository_package_policies_bind_all_ten_immutable_manifests():
    repo_root = Path(__file__).resolve().parents[2]
    config_dir = repo_root / "config" / "package-curation"
    cases = _repository_policy_cases()
    policy_paths = sorted(config_dir.glob("*.json"))

    assert {path.stem for path in policy_paths} == set(cases)

    ready = 0
    unresolved = 0
    selected_other_pdf = []
    for policy_path in policy_paths:
        case = cases[policy_path.stem]
        policy = load_package_curation(policy_path)
        manifest_path = repo_root / case["manifest"]
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        assert policy.package_id == policy_path.stem
        assert policy.status == case["status"]
        if policy.status == "unresolved":
            unresolved += 1
            assert case["reason"] in policy.reason
            with pytest.raises(PackageCurationError, match="unresolved"):
                select_manifest_records(manifest, policy)
            continue

        ready += 1
        expected = case["expected"]
        assert (
            policy.expected_documents,
            policy.expected_individual_results,
            policy.expected_relay_results,
        ) == expected
        selected = select_manifest_records(manifest, policy)
        assert len(selected) == expected[0]
        selected_other_pdf.extend(
            (policy.package_id, record["filename"])
            for record in selected
            if record["category"] == "other_pdf"
        )

    assert ready == 10
    assert unresolved == 0
    assert set(selected_other_pdf) == {
        (
            "11th-singapore-national-swimming-championships-25m-2025",
            "11th-snsc-scm-day-3-session-5-finals.pdf",
        ),
        (
            "singapore-swim-series-2025",
            "jan-swim-series-2025-day-1-session-1.pdf",
        ),
        (
            "singapore-swim-series-2025",
            "jan-swim-series-2025-day-2-session-2.pdf",
        ),
    }


@pytest.mark.skipif(
    os.environ.get("RUN_ARCHIVE_PACKAGE_TESTS") != "1",
    reason="set RUN_ARCHIVE_PACKAGE_TESTS=1 to parse all immutable package PDFs",
)
def test_ready_repository_policies_execute_exact_current_parser_previews():
    repo_root = Path(__file__).resolve().parents[2]
    config_dir = repo_root / "config" / "package-curation"

    for package_id, case in _repository_policy_cases().items():
        if case["status"] != "ready":
            continue
        manifest_path = repo_root / case["manifest"]
        policy = load_package_curation(config_dir / f"{package_id}.json")
        package = parse_competition_manifest(
            manifest_path,
            package_root=manifest_path.parent,
            path_root=repo_root,
            curation_policy=policy,
        )
        report = package.curation_report

        assert report is not None
        assert (
            report.documents,
            report.individual_results,
            report.relay_results,
        ) == case["expected"]

        if package_id == "saq-etp-championships-2026":
            assert [document.sha256 for document in package.documents] == [
                "f92eb8550a009b487fc97ade5d69fbec237169b88186f661a273a1db946bcd39"
            ]
        elif package_id == "11th-singapore-national-swimming-championships-25m-2025":
            assert sum(report.rule_matches.values()) == 10
            assert sum(
                relay.is_judge_decision
                for document in package.documents
                for event in document.parsed.events
                for relay in event.relay_results
            ) == 9
        elif package_id == "21st-snsc-2026":
            assert sum(report.rule_matches.values()) == 58
        elif package_id == "singapore-swim-series-2025":
            private_use_document = next(
                document
                for document in package.documents
                if document.filename == "feb-swim-series-2025-day-3-session-4-results_v2.pdf"
            )
            assert sum(
                len(event.results)
                for event in private_use_document.parsed.events
            ) == 1164
        elif package_id == "56th-snag-2026-full":
            exhibition_results = [
                result
                for document in package.documents
                for event in document.parsed.events
                for result in event.results
                if result.is_exhibition
            ]
            assert len(exhibition_results) == 1
            assert exhibition_results[0].name == "Chen, Jun Jie Zachary"


def test_manifest_policy_resolution_is_shared_and_missing_config_fails_closed(tmp_path: Path):
    package_root = tmp_path / "fixture"
    package_root.mkdir()
    manifest_path = package_root / "manifest.json"
    manifest_path.write_text("{}", encoding="utf-8")
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    policy_path = config_dir / "fixture.json"
    policy_path.write_text(json.dumps({
        "version": 1,
        "package_id": "fixture",
        "source_page": "https://example.test/fixture",
        "status": "unresolved",
        "reason": "held",
    }), encoding="utf-8")

    assert load_manifest_curation_policy(
        manifest_path, config_dir=config_dir
    ).package_id == "fixture"
    assert load_manifest_curation_policy(
        manifest_path, explicit_path=policy_path, config_dir=tmp_path / "ignored"
    ).package_id == "fixture"

    with pytest.raises(PackageCurationError, match="No package curation policy"):
        load_manifest_curation_policy(
            tmp_path / "missing" / "manifest.json", config_dir=config_dir
        )
