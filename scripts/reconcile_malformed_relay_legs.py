#!/usr/bin/env python3
"""Reconcile the reviewed SNAG 2026 malformed relay-leg relationships.

Dry-run is the default.  Apply additionally requires the SHA-256 fence printed
by ``--print-plan-sha256``; database/source preconditions are still rechecked
inside the same locked transaction before any deletion.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

_REPO_ROOT = Path(__file__).resolve().parents[1]
_BACKEND_ROOT = _REPO_ROOT / "backend"
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from app.database import SessionLocal
from app.models import RawDocument
from app.reconciliation import execute_reconciliation, plan_sha256
from app.reconciliation_plans import SNAG_2026_MALFORMED_RELAY_LEGS


def _manifest_sources(manifest_paths: Sequence[Path]) -> dict[str, Path]:
    sources: dict[str, Path] = {}
    for supplied_manifest in manifest_paths:
        manifest = supplied_manifest.resolve(strict=True)
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        for record in payload.get("files", []):
            sha256 = str(record.get("sha256") or "")
            raw_path = record.get("saved") or record.get("filename_saved")
            if len(sha256) != 64 or not raw_path:
                continue
            candidate = Path(str(raw_path))
            if not candidate.is_absolute():
                repo_candidate = _REPO_ROOT / candidate
                manifest_candidate = manifest.parent / candidate
                candidate = repo_candidate if repo_candidate.exists() else manifest_candidate
            previous = sources.get(sha256)
            if previous is not None and previous.resolve() != candidate.resolve():
                raise ValueError(
                    f"source manifest maps SHA-256 {sha256} to multiple paths"
                )
            sources[sha256] = candidate
    return sources


def _source_resolver(db, manifest_sources: dict[str, Path], storage_root: Path):
    def resolve(sha256: str) -> Path:
        manifest_path = manifest_sources.get(sha256)
        if manifest_path is not None:
            return manifest_path
        document = db.query(RawDocument).filter(RawDocument.sha256 == sha256).one()
        storage_path = Path(document.storagePath)
        return storage_path if storage_path.is_absolute() else storage_root / storage_path

    return resolve


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Source-backed reconciliation of reviewed malformed SNAG 2026 relay legs"
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="preview only (default)")
    mode.add_argument("--apply", action="store_true", help="commit verified proposed changes")
    parser.add_argument(
        "--confirm-plan-sha256",
        help="required with --apply; must match --print-plan-sha256",
    )
    parser.add_argument(
        "--print-plan-sha256",
        action="store_true",
        help="print the immutable reviewed-plan fence and exit",
    )
    parser.add_argument(
        "--source-manifest",
        action="append",
        type=Path,
        default=[],
        help="optional archive manifest used to locate canonical PDFs (repeatable)",
    )
    parser.add_argument(
        "--storage-root",
        type=Path,
        default=Path.cwd(),
        help="base for relative RawDocument.storagePath values",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    plan = SNAG_2026_MALFORMED_RELAY_LEGS
    expected_fence = plan_sha256(plan)

    if args.print_plan_sha256:
        if args.apply or args.confirm_plan_sha256 or args.source_manifest:
            parser.error("--print-plan-sha256 cannot be combined with execution options")
        print(expected_fence)
        return 0

    if args.apply and args.confirm_plan_sha256 != expected_fence:
        parser.error(
            "--apply requires --confirm-plan-sha256 equal to the current reviewed plan"
        )
    if not args.apply and args.confirm_plan_sha256:
        parser.error("--confirm-plan-sha256 is valid only with --apply")

    db = SessionLocal()
    try:
        manifest_sources = _manifest_sources(args.source_manifest)
        report = execute_reconciliation(
            db,
            plan,
            source_resolver=_source_resolver(
                db,
                manifest_sources,
                args.storage_root.resolve(),
            ),
            apply=args.apply,
            confirm_plan_sha256=args.confirm_plan_sha256,
        )
        payload = report.to_dict()
        payload["plan_sha256"] = expected_fence
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        db.rollback()
        print(f"reconciliation failed: {exc}", file=sys.stderr)
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
