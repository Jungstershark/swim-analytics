"""Fail-closed reconciliation for source-backed relay-leg corruption.

The caller supplies an immutable, reviewed plan.  No target is selected from a
name pattern: every parent relay, observed relationship, source hash, and safe
relationship is matched exactly before any change can be proposed or applied.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Callable

from sqlalchemy import text
from sqlalchemy.orm import Session

from .models import RawDocument, RelayLeg, RelayResult, Result, Swimmer


class ReconciliationMismatch(ValueError):
    """The database or canonical source no longer matches the reviewed plan."""


@dataclass(frozen=True)
class LegIdentity:
    leg_id: int
    leg_number: int
    swimmer_id: int | None
    swimmer_name: str
    age: int | None
    gender: str | None
    is_guest: bool
    reaction_time: str | None

    @classmethod
    def from_model(cls, leg: RelayLeg) -> "LegIdentity":
        return cls(
            leg_id=leg.id,
            leg_number=leg.legNumber,
            swimmer_id=leg.swimmerId,
            swimmer_name=leg.swimmerName,
            age=leg.age,
            gender=leg.gender,
            is_guest=leg.isGuest,
            reaction_time=leg.reactionTime,
        )


@dataclass(frozen=True)
class RelayIdentity:
    relay_result_id: int
    source_document_sha256: str | None
    source_event_number: str | None
    event: str
    raw_team_name: str | None
    relay_letter: str | None
    result_time: str | None
    round: str | None
    content_hash: str | None


@dataclass(frozen=True)
class RelayTarget:
    parent: RelayIdentity
    expected_observed_count: int
    expected_observed_legs: tuple[LegIdentity, ...]
    malformed_leg_ids: tuple[int, ...]
    expected_safe_legs: tuple[LegIdentity, ...]


@dataclass(frozen=True)
class ReconciliationPlan:
    plan_id: str
    targets: tuple[RelayTarget, ...]


def plan_sha256(plan: ReconciliationPlan) -> str:
    """Digest the complete reviewed plan for an explicit apply fence."""

    canonical = json.dumps(
        asdict(plan),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


@dataclass(frozen=True)
class ReconciliationReport:
    plan_id: str
    mode: str
    verified_source_sha256: tuple[str, ...]
    relay_changes: tuple[dict[str, object], ...]
    delete_swimmers: tuple[dict[str, object], ...]
    totals: dict[str, int]

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["verified_source_sha256"] = list(self.verified_source_sha256)
        payload["relay_changes"] = list(self.relay_changes)
        payload["delete_swimmers"] = list(self.delete_swimmers)
        return payload


SourceResolver = Callable[[str], Path]


def _verify_source(db: Session, sha256: str | None, source_resolver: SourceResolver) -> None:
    if (
        not isinstance(sha256, str)
        or len(sha256) != 64
        or any(char not in "0123456789abcdef" for char in sha256)
    ):
        raise ReconciliationMismatch(f"invalid source SHA-256: {sha256!r}")
    documents = db.query(RawDocument).filter(RawDocument.sha256 == sha256).all()
    if len(documents) != 1:
        raise ReconciliationMismatch(
            f"source {sha256} expected one RawDocument row, observed {len(documents)}"
        )
    path = Path(source_resolver(sha256)).resolve(strict=True)
    actual_sha = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual_sha != sha256:
        raise ReconciliationMismatch(
            f"canonical source SHA-256 mismatch: expected {sha256}, observed {actual_sha}"
        )


def _verify_parent(relay: RelayResult, expected: RelayIdentity) -> None:
    observed = RelayIdentity(
        relay_result_id=relay.id,
        source_document_sha256=relay.sourceDocumentSha256,
        source_event_number=relay.sourceEventNumber,
        event=relay.event,
        raw_team_name=relay.rawTeamName,
        relay_letter=relay.relayLetter,
        result_time=relay.time,
        round=relay.round,
        content_hash=relay.contentHash,
    )
    if observed != expected:
        raise ReconciliationMismatch(
            f"RelayResult {expected.relay_result_id} identity mismatch: "
            f"expected {expected!r}, observed {observed!r}"
        )


def _diagnostics(safe_legs: tuple[LegIdentity, ...], removed_ids: tuple[int, ...]) -> tuple[str, str]:
    safe_numbers = {leg.leg_number for leg in safe_legs}
    missing = sorted({1, 2, 3, 4} - safe_numbers)
    if not safe_legs:
        status = "unavailable"
    elif not missing and len(safe_numbers) == 4:
        status = "complete"
    else:
        status = "partial"
    warning = f"source-backed reconciliation removed malformed RelayLeg ids {list(removed_ids)}"
    if missing:
        warning += f"; missing safe legs {missing}"
    return status, warning


PreparedRelay = tuple[RelayTarget, RelayResult, tuple[RelayLeg, ...], str, str]


def _prepare_reconciliation(
    db: Session,
    plan: ReconciliationPlan,
    *,
    source_resolver: SourceResolver,
) -> tuple[ReconciliationReport, list[PreparedRelay]]:
    """Preflight every immutable expectation without staging any writes."""

    verified_sources: list[str] = []
    seen_sources: set[str] = set()
    seen_relays: set[int] = set()
    for target in plan.targets:
        relay_id = target.parent.relay_result_id
        if relay_id in seen_relays:
            raise ReconciliationMismatch(f"duplicate RelayResult target {relay_id}")
        seen_relays.add(relay_id)

    prepared: list[PreparedRelay] = []

    for target in plan.targets:
        source_sha = target.parent.source_document_sha256
        if source_sha is None:
            raise ReconciliationMismatch(
                f"RelayResult {target.parent.relay_result_id} has no planned source SHA-256"
            )
        if source_sha not in seen_sources:
            _verify_source(db, source_sha, source_resolver)
            seen_sources.add(source_sha)
            verified_sources.append(source_sha)

        relay = db.get(RelayResult, target.parent.relay_result_id)
        if relay is None:
            raise ReconciliationMismatch(
                f"RelayResult {target.parent.relay_result_id} does not exist"
            )
        _verify_parent(relay, target.parent)

        legs = tuple(
            db.query(RelayLeg)
            .filter(RelayLeg.relayResultId == relay.id)
            .order_by(RelayLeg.id)
            .all()
        )
        observed = tuple(LegIdentity.from_model(leg) for leg in legs)
        expected = tuple(sorted(target.expected_observed_legs, key=lambda leg: leg.leg_id))
        if len(legs) != target.expected_observed_count:
            raise ReconciliationMismatch(
                f"RelayResult {relay.id} leg count mismatch: expected "
                f"{target.expected_observed_count}, observed {len(legs)}"
            )
        expected_ids = [leg.leg_id for leg in expected]
        observed_ids_in_order = [leg.leg_id for leg in observed]
        if observed_ids_in_order != expected_ids:
            raise ReconciliationMismatch(
                f"RelayResult {relay.id} leg ID mismatch: expected IDs "
                f"{expected_ids}, observed IDs {observed_ids_in_order}"
            )
        if observed != expected:
            raise ReconciliationMismatch(
                f"RelayResult {relay.id} observed leg identities differ from plan"
            )

        observed_ids = set(observed_ids_in_order)
        malformed_ids = set(target.malformed_leg_ids)
        if not malformed_ids or not malformed_ids <= observed_ids:
            raise ReconciliationMismatch(
                f"RelayResult {relay.id} malformed leg IDs are not an exact observed subset"
            )
        computed_safe = tuple(
            identity for identity in observed if identity.leg_id not in malformed_ids
        )
        expected_safe = tuple(sorted(target.expected_safe_legs, key=lambda leg: leg.leg_id))
        if computed_safe != expected_safe:
            raise ReconciliationMismatch(
                f"RelayResult {relay.id} expected safe leg set differs from observed remainder"
            )
        status, warning = _diagnostics(expected_safe, target.malformed_leg_ids)
        prepared.append((target, relay, legs, status, warning))

    removal_ids = {
        leg_id for target, _relay, _legs, _status, _warning in prepared
        for leg_id in target.malformed_leg_ids
    }
    affected_swimmer_ids = {
        leg.swimmerId
        for _target, _relay, legs, _status, _warning in prepared
        for leg in legs
        if leg.id in removal_ids and leg.swimmerId is not None
    }
    swimmer_deletions: list[dict[str, object]] = []
    for swimmer_id in sorted(affected_swimmer_ids):
        result_count = db.query(Result).filter(Result.swimmerId == swimmer_id).count()
        remaining_leg_count = (
            db.query(RelayLeg)
            .filter(RelayLeg.swimmerId == swimmer_id, RelayLeg.id.not_in(removal_ids))
            .count()
        )
        if result_count == 0 and remaining_leg_count == 0:
            swimmer = db.get(Swimmer, swimmer_id)
            if swimmer is None:
                raise ReconciliationMismatch(f"Swimmer {swimmer_id} does not exist")
            swimmer_deletions.append(
                {
                    "swimmer_id": swimmer.id,
                    "name": swimmer.name,
                    "reason": "no Result or remaining RelayLeg evidence",
                }
            )

    relay_changes = tuple(
        {
            "relay_result_id": relay.id,
            "delete_relay_leg_ids": list(target.malformed_leg_ids),
            "preserve_relay_leg_ids": [
                leg.leg_id for leg in target.expected_safe_legs
            ],
            "leg_parse_status_before": relay.legParseStatus,
            "leg_parse_status_after": status,
            "leg_parse_warning_after": warning,
        }
        for target, relay, _legs, status, warning in prepared
    )

    report = ReconciliationReport(
        plan_id=plan.plan_id,
        mode="dry-run",
        verified_source_sha256=tuple(verified_sources),
        relay_changes=relay_changes,
        delete_swimmers=tuple(swimmer_deletions),
        totals={
            "relay_results_preserved": len(prepared),
            "relay_legs_deleted": len(removal_ids),
            "relay_legs_preserved": sum(len(target.expected_safe_legs) for target, *_ in prepared),
            "swimmers_deleted": len(swimmer_deletions),
        },
    )
    return report, prepared


def _require_clean_session(db: Session) -> None:
    if db.new or db.dirty or db.deleted:
        raise ReconciliationMismatch(
            "reconciliation requires a clean Session with no pending changes"
        )


def reconcile_relay_legs(
    db: Session,
    plan: ReconciliationPlan,
    *,
    source_resolver: SourceResolver,
    apply: bool = False,
) -> ReconciliationReport:
    """Preview a reconciliation without writes or transaction ownership.

    Apply is deliberately available only through :func:`execute_reconciliation`,
    which enforces the confirmation fence and owns the dedicated transaction.
    """

    if apply:
        raise ReconciliationMismatch(
            "apply requires execute_reconciliation with an exact plan confirmation"
        )
    _require_clean_session(db)
    with db.no_autoflush:
        report, _prepared = _prepare_reconciliation(
            db,
            plan,
            source_resolver=source_resolver,
        )
    return report


def execute_reconciliation(
    db: Session,
    plan: ReconciliationPlan,
    *,
    source_resolver: SourceResolver,
    apply: bool = False,
    confirm_plan_sha256: str | None = None,
) -> ReconciliationReport:
    """Run one dedicated reconciliation transaction and own its outcome."""

    expected_confirmation = plan_sha256(plan)
    if apply and confirm_plan_sha256 != expected_confirmation:
        raise ReconciliationMismatch(
            "apply requires confirmation equal to the current reconciliation plan SHA-256"
        )
    if not apply and confirm_plan_sha256 is not None:
        raise ReconciliationMismatch("plan confirmation is valid only for apply")
    _require_clean_session(db)
    if db.in_transaction():
        raise ReconciliationMismatch(
            "reconciliation requires a Session without an active transaction"
        )

    transaction = db.begin()
    try:
        if apply and db.get_bind().dialect.name == "postgresql":
            db.execute(
                text(
                    'LOCK TABLE "RelayResult", "RelayLeg", "Result", "Swimmer" '
                    "IN SHARE ROW EXCLUSIVE MODE"
                )
            )
        with db.no_autoflush:
            report, prepared = _prepare_reconciliation(
                db,
                plan,
                source_resolver=source_resolver,
            )
        if apply:
            for target, relay, legs, status, warning in prepared:
                malformed_ids = set(target.malformed_leg_ids)
                for leg in legs:
                    if leg.id in malformed_ids:
                        db.delete(leg)
                relay.legParseStatus = status
                relay.legParseWarning = warning
            db.flush()
            for deletion in report.delete_swimmers:
                swimmer = db.get(Swimmer, deletion["swimmer_id"])
                if swimmer is None:
                    raise ReconciliationMismatch(
                        f"Swimmer {deletion['swimmer_id']} disappeared during apply"
                    )
                db.delete(swimmer)
            db.flush()
            report = replace(report, mode="apply")
            transaction.commit()
        else:
            transaction.rollback()
        return report
    except Exception:
        if transaction.is_active:
            transaction.rollback()
        raise
