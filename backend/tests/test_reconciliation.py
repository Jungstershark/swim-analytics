"""Source-backed reconciliation tests for stale malformed relay identities."""

from __future__ import annotations

import hashlib
import subprocess
import sys
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base
from app.models import Meet, RawDocument, RelayLeg, RelayResult, Result, Swimmer
from app.reconciliation import (
    LegIdentity,
    ReconciliationMismatch,
    ReconciliationPlan,
    RelayIdentity,
    RelayTarget,
    execute_reconciliation,
    plan_sha256,
    reconcile_relay_legs,
)
from app.reconciliation_plans import SNAG_2026_MALFORMED_RELAY_LEGS


def _test_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, class_=Session, expire_on_commit=False)()


def _seed_false_leg(db: Session, source_path: Path) -> tuple[ReconciliationPlan, RelayResult]:
    content = b"%PDF-1.4\ncanonical relay evidence\n%%EOF"
    source_path.write_bytes(content)
    source_sha = hashlib.sha256(content).hexdigest()
    db.add(
        RawDocument(
            sha256=source_sha,
            byteSize=len(content),
            storagePath=str(source_path),
            originalFilename="result.pdf",
            isValidPdf=True,
        )
    )
    meet = Meet(name="Source Meet", startDate=datetime(2026, 3, 13), parserFormat="hytek")
    safe_swimmer = Swimmer(name="Ee, Emma", age=12, team="X Lab")
    false_swimmer = Swimmer(
        name="Abdul Khair, Daria Suhayr3 W) r1:02.53 Mark, Ivan Royston",
        age=11,
        team="X Lab",
    )
    db.add_all([meet, safe_swimmer, false_swimmer])
    db.flush()
    relay = RelayResult(
        id=55,
        meetId=meet.id,
        event="Mixed 11-12 200 LC Meter Medley Relay",
        teamName="X Lab",
        rawTeamName="X Lab",
        relayLetter="C",
        time="2:55.95",
        round="Final",
        sourceDocumentSha256=source_sha,
        sourceEventNumber="117",
        contentHash="relay-hash-55",
    )
    db.add(relay)
    db.flush()
    safe_leg = RelayLeg(
        id=211,
        relayResultId=relay.id,
        legNumber=1,
        swimmerId=safe_swimmer.id,
        swimmerName=safe_swimmer.name,
        age=12,
        gender="W",
        reactionTime="0.75",
    )
    false_leg = RelayLeg(
        id=212,
        relayResultId=relay.id,
        legNumber=2,
        swimmerId=false_swimmer.id,
        swimmerName=false_swimmer.name,
        age=11,
        gender="M",
        reactionTime="0.35",
    )
    db.add_all([safe_leg, false_leg])
    db.commit()

    plan = ReconciliationPlan(
        plan_id="test-relay-55-v1",
        targets=(
            RelayTarget(
                parent=RelayIdentity(
                    relay_result_id=55,
                    source_document_sha256=source_sha,
                    source_event_number="117",
                    event="Mixed 11-12 200 LC Meter Medley Relay",
                    raw_team_name="X Lab",
                    relay_letter="C",
                    result_time="2:55.95",
                    round="Final",
                    content_hash="relay-hash-55",
                ),
                expected_observed_count=2,
                expected_observed_legs=(
                    LegIdentity(211, 1, safe_swimmer.id, "Ee, Emma", 12, "W", False, "0.75"),
                    LegIdentity(
                        212,
                        2,
                        false_swimmer.id,
                        false_swimmer.name,
                        11,
                        "M",
                        False,
                        "0.35",
                    ),
                ),
                malformed_leg_ids=(212,),
                expected_safe_legs=(
                    LegIdentity(211, 1, safe_swimmer.id, "Ee, Emma", 12, "W", False, "0.75"),
                ),
            ),
        ),
    )
    return plan, relay


def test_dry_run_reports_exact_changes_and_rolls_back(tmp_path: Path):
    db = _test_session()
    source_path = tmp_path / "source.pdf"
    plan, relay = _seed_false_leg(db, source_path)

    report = reconcile_relay_legs(
        db,
        plan,
        source_resolver=lambda _sha: source_path,
        apply=False,
    )

    assert report.to_dict() == {
        "plan_id": "test-relay-55-v1",
        "mode": "dry-run",
        "verified_source_sha256": [relay.sourceDocumentSha256],
        "relay_changes": [
            {
                "relay_result_id": 55,
                "delete_relay_leg_ids": [212],
                "preserve_relay_leg_ids": [211],
                "leg_parse_status_before": None,
                "leg_parse_status_after": "partial",
                "leg_parse_warning_after": (
                    "source-backed reconciliation removed malformed RelayLeg ids [212]; "
                    "missing safe legs [2, 3, 4]"
                ),
            }
        ],
        "delete_swimmers": [
            {
                "swimmer_id": 2,
                "name": "Abdul Khair, Daria Suhayr3 W) r1:02.53 Mark, Ivan Royston",
                "reason": "no Result or remaining RelayLeg evidence",
            }
        ],
        "totals": {
            "relay_results_preserved": 1,
            "relay_legs_deleted": 1,
            "relay_legs_preserved": 1,
            "swimmers_deleted": 1,
        },
    }
    assert db.get(RelayResult, 55) is not None
    assert [leg.id for leg in db.query(RelayLeg).order_by(RelayLeg.id)] == [211, 212]
    assert db.get(Swimmer, 2) is not None
    assert db.get(RelayResult, 55).legParseStatus is None


def test_apply_removes_only_malformed_relationship_and_orphan(tmp_path: Path):
    db = _test_session()
    source_path = tmp_path / "source.pdf"
    plan, _relay = _seed_false_leg(db, source_path)

    report = execute_reconciliation(
        db,
        plan,
        source_resolver=lambda _sha: source_path,
        apply=True,
        confirm_plan_sha256=plan_sha256(plan),
    )

    assert report.mode == "apply"
    assert db.get(RelayResult, 55) is not None
    assert [leg.id for leg in db.query(RelayLeg).order_by(RelayLeg.id)] == [211]
    assert db.get(Swimmer, 1) is not None
    assert db.get(Swimmer, 2) is None
    relay = db.get(RelayResult, 55)
    assert relay.legParseStatus == "partial"
    assert relay.legParseWarning == (
        "source-backed reconciliation removed malformed RelayLeg ids [212]; "
        "missing safe legs [2, 3, 4]"
    )


def test_apply_preserves_removed_leg_swimmer_with_individual_result(tmp_path: Path):
    db = _test_session()
    source_path = tmp_path / "source.pdf"
    plan, relay = _seed_false_leg(db, source_path)
    db.add(
        Result(
            swimmerId=2,
            meetId=relay.meetId,
            event="Girls 50 LC Meter Freestyle",
            contentHash="individual-evidence-for-swimmer-2",
        )
    )
    db.commit()

    report = execute_reconciliation(
        db,
        plan,
        source_resolver=lambda _sha: source_path,
        apply=True,
        confirm_plan_sha256=plan_sha256(plan),
    )

    assert report.delete_swimmers == ()
    assert db.get(RelayLeg, 212) is None
    assert db.get(Swimmer, 2) is not None
    assert db.query(Result).filter(Result.swimmerId == 2).count() == 1


def test_duplicate_parent_target_fails_closed_before_apply(tmp_path: Path):
    db = _test_session()
    source_path = tmp_path / "source.pdf"
    plan, _relay = _seed_false_leg(db, source_path)
    duplicate_plan = replace(plan, targets=(plan.targets[0], plan.targets[0]))

    with pytest.raises(ReconciliationMismatch, match="duplicate RelayResult target 55"):
        execute_reconciliation(
            db,
            duplicate_plan,
            source_resolver=lambda _sha: source_path,
            apply=True,
            confirm_plan_sha256=plan_sha256(duplicate_plan),
        )
    assert [leg.id for leg in db.query(RelayLeg).order_by(RelayLeg.id)] == [211, 212]
    assert db.get(Swimmer, 2) is not None


def test_execute_rolls_back_when_apply_flush_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db = _test_session()
    source_path = tmp_path / "source.pdf"
    plan, _relay = _seed_false_leg(db, source_path)
    original_flush = db.flush
    flush_calls = 0

    def fail_second_flush(*args, **kwargs):
        nonlocal flush_calls
        flush_calls += 1
        if flush_calls == 2:
            raise RuntimeError("injected late apply failure")
        return original_flush(*args, **kwargs)

    monkeypatch.setattr(db, "flush", fail_second_flush)

    with pytest.raises(RuntimeError, match="injected late apply failure"):
        execute_reconciliation(
            db,
            plan,
            source_resolver=lambda _sha: source_path,
            apply=True,
            confirm_plan_sha256=plan_sha256(plan),
        )

    monkeypatch.setattr(db, "flush", original_flush)
    assert [leg.id for leg in db.query(RelayLeg).order_by(RelayLeg.id)] == [211, 212]
    assert db.get(Swimmer, 2) is not None
    assert db.get(RelayResult, 55).legParseStatus is None


def test_plan_sha256_fences_every_reviewed_expectation(tmp_path: Path):
    db = _test_session()
    plan, _relay = _seed_false_leg(db, tmp_path / "source.pdf")
    changed_target = replace(plan.targets[0], expected_observed_count=3)
    changed_plan = replace(plan, targets=(changed_target,))

    assert len(plan_sha256(plan)) == 64
    assert plan_sha256(plan) == plan_sha256(plan)
    assert plan_sha256(changed_plan) != plan_sha256(plan)


def test_apply_requires_exact_plan_sha256_before_transaction(tmp_path: Path):
    db = _test_session()
    source_path = tmp_path / "source.pdf"
    plan, _relay = _seed_false_leg(db, source_path)

    with pytest.raises(ReconciliationMismatch, match="requires confirmation"):
        execute_reconciliation(
            db,
            plan,
            source_resolver=lambda _sha: source_path,
            apply=True,
            confirm_plan_sha256="0" * 64,
        )

    assert not db.in_transaction()
    assert [leg.id for leg in db.query(RelayLeg).order_by(RelayLeg.id)] == [211, 212]


def test_low_level_preview_api_rejects_apply(tmp_path: Path):
    db = _test_session()
    source_path = tmp_path / "source.pdf"
    plan, _relay = _seed_false_leg(db, source_path)

    with pytest.raises(ReconciliationMismatch, match="apply requires execute_reconciliation"):
        reconcile_relay_legs(
            db,
            plan,
            source_resolver=lambda _sha: source_path,
            apply=True,
        )

    assert [leg.id for leg in db.query(RelayLeg).order_by(RelayLeg.id)] == [211, 212]


def test_dry_run_rejects_dirty_session_without_autoflush(tmp_path: Path):
    db = _test_session()
    source_path = tmp_path / "source.pdf"
    plan, _relay = _seed_false_leg(db, source_path)
    pending = Swimmer(name="Pending, Unrelated", age=12, team="Other")
    db.add(pending)

    with pytest.raises(ReconciliationMismatch, match="clean Session"):
        reconcile_relay_legs(
            db,
            plan,
            source_resolver=lambda _sha: source_path,
        )

    assert pending.id is None
    assert pending in db.new


def test_reviewed_production_plan_covers_known_and_broader_malformed_relationships():
    plan = SNAG_2026_MALFORMED_RELAY_LEGS
    malformed_ids = {
        leg_id for target in plan.targets for leg_id in target.malformed_leg_ids
    }
    source_hashes = {
        target.parent.source_document_sha256 for target in plan.targets
    }
    content_hashes = [target.parent.content_hash for target in plan.targets]

    assert len(plan.targets) == 20
    assert all(
        len(content_hash) == 64
        and all(char in "0123456789abcdef" for char in content_hash)
        for content_hash in content_hashes
    )
    assert len(set(content_hashes)) == len(plan.targets)
    assert malformed_ids == {
        111,
        114,
        117,
        193,
        212,
        415,
        442,
        476,
        708,
        830,
        885,
        936,
        956,
        995,
        1071,
        1090,
        1096,
        1113,
        1223,
        1350,
    }
    assert len(source_hashes) == 9
    relay_55 = next(target for target in plan.targets if target.parent.relay_result_id == 55)
    assert relay_55.malformed_leg_ids == (212,)
    assert relay_55.expected_observed_legs[1].swimmer_id == 698
    assert "r1:02.53" in relay_55.expected_observed_legs[1].swimmer_name


def test_cli_prints_plan_fence_without_opening_database():
    script = Path(__file__).resolve().parents[2] / "scripts" / "reconcile_malformed_relay_legs.py"

    completed = subprocess.run(
        [sys.executable, str(script), "--print-plan-sha256"],
        cwd=script.parents[1],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == plan_sha256(SNAG_2026_MALFORMED_RELAY_LEGS)


def test_cli_apply_requires_matching_plan_fence():
    script = Path(__file__).resolve().parents[2] / "scripts" / "reconcile_malformed_relay_legs.py"

    completed = subprocess.run(
        [sys.executable, str(script), "--apply"],
        cwd=script.parents[1],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 2
    assert "--confirm-plan-sha256" in completed.stderr


def test_cli_apply_rejects_explicit_mismatched_plan_fence_before_database_open():
    script = Path(__file__).resolve().parents[2] / "scripts" / "reconcile_malformed_relay_legs.py"

    completed = subprocess.run(
        [
            sys.executable,
            str(script),
            "--apply",
            "--confirm-plan-sha256",
            "0" * 64,
        ],
        cwd=script.parents[1],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 2
    assert "equal to the current reviewed plan" in completed.stderr


def test_observed_leg_id_mismatch_names_expected_and_observed_ids(tmp_path: Path):
    db = _test_session()
    source_path = tmp_path / "source.pdf"
    plan, _relay = _seed_false_leg(db, source_path)
    db.get(RelayLeg, 212).id = 999
    db.commit()

    with pytest.raises(
        ReconciliationMismatch,
        match=r"expected IDs \[211, 212\], observed IDs \[211, 999\]",
    ):
        execute_reconciliation(
            db,
            plan,
            source_resolver=lambda _sha: source_path,
            apply=True,
            confirm_plan_sha256=plan_sha256(plan),
        )

    assert [leg.id for leg in db.query(RelayLeg).order_by(RelayLeg.id)] == [211, 999]


def test_parent_content_hash_mismatch_fails_closed_before_apply(tmp_path: Path):
    db = _test_session()
    source_path = tmp_path / "source.pdf"
    plan, relay = _seed_false_leg(db, source_path)
    relay.contentHash = "changed-relay-hash"
    db.commit()

    with pytest.raises(
        ReconciliationMismatch,
        match=r"RelayResult 55 identity mismatch",
    ):
        execute_reconciliation(
            db,
            plan,
            source_resolver=lambda _sha: source_path,
            apply=True,
            confirm_plan_sha256=plan_sha256(plan),
        )

    assert db.get(RelayResult, 55) is not None
    assert [leg.id for leg in db.query(RelayLeg).order_by(RelayLeg.id)] == [211, 212]
    assert db.get(Swimmer, 2) is not None
    assert db.get(RelayResult, 55).legParseStatus is None


def test_source_file_sha_mismatch_fails_closed_before_apply(tmp_path: Path):
    db = _test_session()
    source_path = tmp_path / "source.pdf"
    plan, _relay = _seed_false_leg(db, source_path)
    source_path.write_bytes(b"changed canonical bytes")

    with pytest.raises(ReconciliationMismatch, match="canonical source SHA-256 mismatch"):
        execute_reconciliation(
            db,
            plan,
            source_resolver=lambda _sha: source_path,
            apply=True,
            confirm_plan_sha256=plan_sha256(plan),
        )

    assert db.get(RelayResult, 55) is not None
    assert [leg.id for leg in db.query(RelayLeg).order_by(RelayLeg.id)] == [211, 212]
    assert db.get(Swimmer, 2) is not None
