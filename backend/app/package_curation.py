"""Fail-closed canonical source-document and parsed-row curation.

Policies bind a package to immutable source SHA-256 values.  Parsed rows are
curated only on deep copies, so raw documents and parser output remain evidence
rather than becoming mutable working state.
"""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
from dataclasses import dataclass, replace
import json
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

from .source_monitoring import canonicalize_url

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ALLOWED_CATEGORIES = {"overall_results", "other_pdf"}
_ALLOWED_ROW_KINDS = {"individual", "relay"}
_ALLOWED_ACTIONS = {"include", "exclude"}
_COMMON_MATCH_FIELDS = {"event_number", "event_name", "time_type", "status"}
_INDIVIDUAL_MATCH_FIELDS = {
    "placement", "name", "age", "team", "seed_time", "finals_time",
    "is_dq", "is_ns", "is_exhibition",
}
_RELAY_MATCH_FIELDS = {
    "placement", "team_name", "relay_letter", "seed_time", "finals_time",
    "is_dq", "is_exhibition", "leg_parse_status",
}
_SPECIAL_MATCH_FIELDS = {"duplicate_of_source_sha256", "round"}


class PackageCurationError(ValueError):
    """The package cannot be curated exactly under its declared policy."""


@dataclass(frozen=True)
class CanonicalDocument:
    filename: str
    sha256: str
    category: str


@dataclass(frozen=True)
class RowRule:
    id: str
    source_sha256: str
    row_kind: str
    action: str
    match: Mapping[str, Any]
    expected_matches: int


@dataclass(frozen=True)
class PackageCurationPolicy:
    version: int
    package_id: str
    source_page: str
    status: str
    reason: str | None
    documents: tuple[CanonicalDocument, ...]
    # Explicitly declared overlapping document pairs (as filename pairs, each
    # sorted). A policy must name the pair it authorises; sharing a package is
    # not by itself permission for two documents to claim the same evidence.
    shared_evidence: tuple[tuple[str, str], ...]
    rules: tuple[RowRule, ...]
    expected_documents: int | None
    expected_individual_results: int | None
    expected_relay_results: int | None


@dataclass(frozen=True)
class PackageCurationReport:
    package_id: str
    documents: int
    individual_results: int
    relay_results: int
    rule_matches: Mapping[str, int]


def _require_mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise PackageCurationError(f"{label} must be an object")
    return value


def _require_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PackageCurationError(f"{label} must be a non-empty string")
    return value.strip()


def _require_sha(value: object, label: str) -> str:
    sha = _require_string(value, label)
    if not _SHA256_RE.fullmatch(sha):
        raise PackageCurationError(f"{label} must be a lowercase SHA-256")
    return sha


def _require_nonnegative_int(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise PackageCurationError(f"{label} must be a non-negative integer")
    return value


def load_manifest_curation_policy(
    manifest_path: Path,
    *,
    explicit_path: Path | None = None,
    config_dir: Path,
) -> PackageCurationPolicy:
    """Resolve a manifest's required policy by package-directory slug."""
    policy_path = explicit_path or config_dir / f"{manifest_path.parent.name}.json"
    if not policy_path.is_file():
        raise PackageCurationError(
            f"No package curation policy for {manifest_path.parent.name}: {policy_path}"
        )
    return load_package_curation(policy_path)


def load_package_curation(path: Path) -> PackageCurationPolicy:
    """Load and strictly validate one versioned package policy JSON file."""
    try:
        payload = _require_mapping(json.loads(path.read_text(encoding="utf-8")), "policy")
    except (OSError, json.JSONDecodeError) as exc:
        raise PackageCurationError(f"Cannot load package curation policy {path}: {exc}") from exc

    if payload.get("version") != 1:
        raise PackageCurationError("package curation policy version must be 1")
    package_id = _require_string(payload.get("package_id"), "package_id")
    source_page = canonicalize_url(_require_string(payload.get("source_page"), "source_page"))
    status = _require_string(payload.get("status"), "status")
    reason = payload.get("reason")
    if reason is not None:
        reason = _require_string(reason, "reason")
    if status not in {"ready", "unresolved"}:
        raise PackageCurationError("status must be ready or unresolved")

    if status == "unresolved":
        if not reason:
            raise PackageCurationError("unresolved policy requires a reason")
        return PackageCurationPolicy(
            version=1,
            package_id=package_id,
            source_page=source_page,
            status=status,
            reason=reason,
            documents=(),
            shared_evidence=(),
            rules=(),
            expected_documents=None,
            expected_individual_results=None,
            expected_relay_results=None,
        )

    raw_documents = payload.get("documents")
    if not isinstance(raw_documents, list) or not raw_documents:
        raise PackageCurationError("ready policy requires a non-empty documents allowlist")
    documents: list[CanonicalDocument] = []
    seen_hashes: set[str] = set()
    for index, raw_document in enumerate(raw_documents):
        item = _require_mapping(raw_document, f"documents[{index}]")
        sha = _require_sha(item.get("sha256"), f"documents[{index}].sha256")
        if sha in seen_hashes:
            raise PackageCurationError(f"duplicate allowlisted SHA-256: {sha}")
        seen_hashes.add(sha)
        category = _require_string(item.get("category"), f"documents[{index}].category")
        if category not in _ALLOWED_CATEGORIES:
            raise PackageCurationError(
                f"documents[{index}].category must be overall_results or other_pdf"
            )
        documents.append(CanonicalDocument(
            filename=_require_string(item.get("filename"), f"documents[{index}].filename"),
            sha256=sha,
            category=category,
        ))

    raw_shared = payload.get("shared_evidence", [])
    if not isinstance(raw_shared, list):
        raise PackageCurationError("shared_evidence must be an array")
    allowed_filenames = {document.filename for document in documents}
    shared_evidence: list[tuple[str, str]] = []
    for index, raw_pair in enumerate(raw_shared):
        item = _require_mapping(raw_pair, f"shared_evidence[{index}]")
        names = item.get("documents")
        if not isinstance(names, list) or len(names) != 2:
            raise PackageCurationError(
                f"shared_evidence[{index}] needs exactly two document filenames"
            )
        first = _require_string(names[0], f"shared_evidence[{index}].documents[0]")
        second = _require_string(names[1], f"shared_evidence[{index}].documents[1]")
        if first == second:
            raise PackageCurationError(
                f"shared_evidence[{index}] names one document twice"
            )
        for name in (first, second):
            if name not in allowed_filenames:
                raise PackageCurationError(
                    f"shared_evidence[{index}] names '{name}', which is not allowlisted"
                )
        pair: tuple[str, str] = (first, second) if first < second else (second, first)
        if pair in shared_evidence:
            raise PackageCurationError(f"duplicate shared_evidence pair: {pair}")
        shared_evidence.append(pair)

    raw_rules = payload.get("rules", [])
    if not isinstance(raw_rules, list):
        raise PackageCurationError("rules must be an array")
    rules: list[RowRule] = []
    seen_rule_ids: set[str] = set()
    for index, raw_rule in enumerate(raw_rules):
        item = _require_mapping(raw_rule, f"rules[{index}]")
        rule_id = _require_string(item.get("id"), f"rules[{index}].id")
        if rule_id in seen_rule_ids:
            raise PackageCurationError(f"duplicate row rule id: {rule_id}")
        seen_rule_ids.add(rule_id)
        source_sha = _require_sha(item.get("source_sha256"), f"rules[{index}].source_sha256")
        if source_sha not in seen_hashes:
            raise PackageCurationError(f"rule {rule_id} references a non-allowlisted source SHA-256")
        row_kind = _require_string(item.get("row_kind"), f"rules[{index}].row_kind")
        action = _require_string(item.get("action"), f"rules[{index}].action")
        if row_kind not in _ALLOWED_ROW_KINDS:
            raise PackageCurationError(f"rule {rule_id} has invalid row_kind")
        if action not in _ALLOWED_ACTIONS:
            raise PackageCurationError(f"rule {rule_id} has invalid action")
        match = _require_mapping(item.get("match"), f"rules[{index}].match")
        if not match:
            raise PackageCurationError(f"rule {rule_id} requires at least one semantic match field")
        allowed_fields = _COMMON_MATCH_FIELDS | _SPECIAL_MATCH_FIELDS
        allowed_fields |= _INDIVIDUAL_MATCH_FIELDS if row_kind == "individual" else _RELAY_MATCH_FIELDS
        unsupported = set(match) - allowed_fields
        if unsupported:
            raise PackageCurationError(
                f"rule {rule_id} has unsupported match fields: {', '.join(sorted(unsupported))}"
            )
        duplicate_sha = match.get("duplicate_of_source_sha256")
        if duplicate_sha is not None:
            duplicate_sha = _require_sha(
                duplicate_sha, f"rules[{index}].match.duplicate_of_source_sha256"
            )
            if duplicate_sha not in seen_hashes:
                raise PackageCurationError(
                    f"rule {rule_id} duplicate source is not allowlisted"
                )
            match = dict(match)
            match["duplicate_of_source_sha256"] = duplicate_sha
        rules.append(RowRule(
            id=rule_id,
            source_sha256=source_sha,
            row_kind=row_kind,
            action=action,
            match=dict(match),
            expected_matches=_require_nonnegative_int(
                item.get("expected_matches"), f"rules[{index}].expected_matches"
            ),
        ))

    expected = _require_mapping(payload.get("expected"), "expected")
    expected_documents = _require_nonnegative_int(expected.get("documents"), "expected.documents")
    if expected_documents != len(documents):
        raise PackageCurationError(
            f"expected.documents is {expected_documents}, allowlist contains {len(documents)}"
        )
    return PackageCurationPolicy(
        version=1,
        package_id=package_id,
        source_page=source_page,
        status=status,
        reason=reason,
        documents=tuple(documents),
        shared_evidence=tuple(shared_evidence),
        rules=tuple(rules),
        expected_documents=expected_documents,
        expected_individual_results=_require_nonnegative_int(
            expected.get("individual_results"), "expected.individual_results"
        ),
        expected_relay_results=_require_nonnegative_int(
            expected.get("relay_results"), "expected.relay_results"
        ),
    )


def _require_ready(policy: PackageCurationPolicy) -> None:
    if policy.status != "ready":
        raise PackageCurationError(
            f"Package {policy.package_id} is unresolved: {policy.reason or 'no reason recorded'}"
        )


def select_manifest_records(
    manifest: Mapping[str, Any], policy: PackageCurationPolicy
) -> tuple[Mapping[str, Any], ...]:
    """Select exactly one manifest record for every allowlisted source hash."""
    _require_ready(policy)
    manifest_source = canonicalize_url(str(manifest.get("source_page") or ""))
    if manifest_source != policy.source_page:
        raise PackageCurationError(
            f"Policy source_page {policy.source_page} does not match manifest {manifest_source}"
        )
    records = manifest.get("files")
    if not isinstance(records, list):
        raise PackageCurationError("manifest files must be an array")

    by_sha: dict[str, list[Mapping[str, Any]]] = {}
    for index, raw_record in enumerate(records):
        record = _require_mapping(raw_record, f"manifest files[{index}]")
        raw_sha = record.get("sha256")
        if isinstance(raw_sha, str):
            by_sha.setdefault(raw_sha, []).append(record)

    selected: list[Mapping[str, Any]] = []
    for allowed in policy.documents:
        matches = by_sha.get(allowed.sha256, [])
        if not matches:
            raise PackageCurationError(
                f"Allowlisted source SHA-256 is absent from manifest: {allowed.sha256}"
            )
        if len(matches) != 1:
            raise PackageCurationError(
                f"Allowlisted source SHA-256 has duplicate manifest records: {allowed.sha256}"
            )
        record = matches[0]
        if record.get("filename") != allowed.filename:
            raise PackageCurationError(
                f"Allowlisted SHA-256 {allowed.sha256} filename mismatch"
            )
        if record.get("category") != allowed.category:
            raise PackageCurationError(
                f"Allowlisted SHA-256 {allowed.sha256} category mismatch"
            )
        selected.append(record)
    return tuple(selected)


def _round_name(time_type: object) -> str:
    value = str(time_type or "").strip().lower()
    if value == "prelim time":
        return "Prelim"
    if value == "finals time":
        return "Final"
    if value == "timed final":
        return "Timed Final"
    return str(time_type or "")


def _semantic_identity(event: object, row: object, row_kind: str) -> tuple[object, ...]:
    common = (
        getattr(event, "event_number"),
        getattr(event, "event_name"),
        getattr(row, "seed_time"),
        getattr(row, "finals_time"),
        getattr(row, "time_type"),
        getattr(row, "status"),
        getattr(row, "is_dq"),
    )
    if row_kind == "individual":
        return common + (
            getattr(row, "name"),
            getattr(row, "age"),
            getattr(row, "team"),
            getattr(row, "is_ns"),
            getattr(row, "is_exhibition"),
        )
    return common + (
        getattr(row, "team_name"),
        getattr(row, "relay_letter"),
        getattr(row, "is_exhibition"),
    )


def _rows(document: Any, row_kind: str):
    attribute = "results" if row_kind == "individual" else "relay_results"
    for event_index, event in enumerate(document.parsed.events):
        for row_index, row in enumerate(getattr(event, attribute)):
            yield event_index, row_index, event, row


def _matches_fields(event: object, row: object, match: Mapping[str, Any]) -> bool:
    for field, expected in match.items():
        if field == "duplicate_of_source_sha256":
            continue
        if field == "event_number":
            actual = getattr(event, "event_number")
        elif field == "event_name":
            actual = getattr(event, "event_name")
        elif field == "round":
            actual = _round_name(getattr(row, "time_type", None))
        else:
            actual = getattr(row, field)
        if isinstance(expected, list):
            if actual not in expected:
                return False
        elif actual != expected:
            return False
    return True


def _matching_positions(
    document: Any,
    rule: RowRule,
    by_sha: Mapping[str, Any],
) -> set[tuple[int, int]]:
    duplicate_sha = rule.match.get("duplicate_of_source_sha256")
    available: Counter[tuple[object, ...]] | None = None
    if duplicate_sha is not None:
        available = Counter(
            _semantic_identity(event, row, rule.row_kind)
            for _event_index, _row_index, event, row in _rows(by_sha[duplicate_sha], rule.row_kind)
        )

    positions: set[tuple[int, int]] = set()
    for event_index, row_index, event, row in _rows(document, rule.row_kind):
        if not _matches_fields(event, row, rule.match):
            continue
        if available is not None:
            identity = _semantic_identity(event, row, rule.row_kind)
            if available[identity] <= 0:
                continue
            available[identity] -= 1
        positions.add((event_index, row_index))
    return positions


def apply_package_curation(
    documents: Sequence[Any], policy: PackageCurationPolicy
) -> tuple[tuple[Any, ...], PackageCurationReport]:
    """Apply exact row policy to copied parser outputs and verify final totals."""
    _require_ready(policy)
    by_sha: dict[str, Any] = {}
    for document in documents:
        sha = document.sha256
        if sha in by_sha:
            raise PackageCurationError(f"Parsed documents contain duplicate source SHA-256: {sha}")
        by_sha[sha] = document
    expected_hashes = {document.sha256 for document in policy.documents}
    actual_hashes = set(by_sha)
    if actual_hashes != expected_hashes:
        absent = sorted(expected_hashes - actual_hashes)
        extra = sorted(actual_hashes - expected_hashes)
        raise PackageCurationError(
            f"Parsed document SHA-256 set mismatch; absent={absent}, extra={extra}"
        )

    rules_by_scope: dict[tuple[str, str], list[RowRule]] = {}
    rule_positions: dict[str, set[tuple[int, int]]] = {}
    rule_matches: dict[str, int] = {}
    for rule in policy.rules:
        document = by_sha[rule.source_sha256]
        positions = _matching_positions(document, rule, by_sha)
        observed = len(positions)
        if observed != rule.expected_matches:
            raise PackageCurationError(
                f"Rule {rule.id} expected {rule.expected_matches} matches, observed {observed}"
            )
        rule_positions[rule.id] = positions
        rule_matches[rule.id] = observed
        rules_by_scope.setdefault((rule.source_sha256, rule.row_kind), []).append(rule)

    curated_documents: list[Any] = []
    for document in documents:
        parsed = deepcopy(document.parsed)
        for row_kind, attribute in (("individual", "results"), ("relay", "relay_results")):
            scoped_rules = rules_by_scope.get((document.sha256, row_kind), [])
            include_rules = [rule for rule in scoped_rules if rule.action == "include"]
            exclude_rules = [rule for rule in scoped_rules if rule.action == "exclude"]
            for event_index, event in enumerate(parsed.events):
                kept = []
                for row_index, row in enumerate(getattr(event, attribute)):
                    position = (event_index, row_index)
                    included = not include_rules or any(
                        position in rule_positions[rule.id] for rule in include_rules
                    )
                    excluded = any(
                        position in rule_positions[rule.id] for rule in exclude_rules
                    )
                    if included and not excluded:
                        kept.append(row)
                setattr(event, attribute, kept)
        shared_evidence_group = next(
            (
                f"{pair[0]}\x00{pair[1]}"
                for pair in policy.shared_evidence
                if document.filename in pair
            ),
            None,
        )
        curated_documents.append(replace(
            document,
            parsed=parsed,
            curation_policy_id=policy.package_id,
            shared_evidence_group=shared_evidence_group,
        ))

    individual_results = sum(document.parsed.total_results for document in curated_documents)
    relay_results = sum(document.parsed.total_relay_results for document in curated_documents)
    if individual_results != policy.expected_individual_results:
        raise PackageCurationError(
            "Package final individual_results "
            f"expected {policy.expected_individual_results}, observed {individual_results}"
        )
    if relay_results != policy.expected_relay_results:
        raise PackageCurationError(
            "Package final relay_results "
            f"expected {policy.expected_relay_results}, observed {relay_results}"
        )
    if len(curated_documents) != policy.expected_documents:
        raise PackageCurationError(
            f"Package final documents expected {policy.expected_documents}, "
            f"observed {len(curated_documents)}"
        )

    report = PackageCurationReport(
        package_id=policy.package_id,
        documents=len(curated_documents),
        individual_results=individual_results,
        relay_results=relay_results,
        rule_matches=rule_matches,
    )
    return tuple(curated_documents), report
