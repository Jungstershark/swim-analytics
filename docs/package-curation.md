# Archived package curation

Archived SG Aquatics manifests are evidence archives, not import instructions. A result-like filename or an `overall_results` category can refer to a full-meet duplicate, cumulative standings, an alternate view, or another discipline. Preview and import therefore require the same versioned policy from `config/package-curation/<manifest-parent>.json`.

## Safety contract

A `ready` policy must:

- bind the canonical package to its canonicalized `source_page`;
- list every selected document by exact lowercase SHA-256, filename, and manifest category;
- select exactly one manifest record per hash (absent or duplicate hashes fail);
- select only `overall_results` or explicitly named `other_pdf` records;
- declare every row rule with source SHA, row kind, action, semantic match, and exact match count;
- declare exact final document, individual-result, and relay-result totals;
- pass an executable preview with the current parser.

Anything outside the allowlist is ignored as performance input. Raw PDFs, manifests, and parser outputs are never rewritten. Row filtering is applied to deep-copied parser output. A rule-cardinality or final-total mismatch aborts before import.

An `unresolved` policy contains a precise reason and always fails closed. A missing policy also fails closed. A source-backed target is not enough to mark a policy `ready` when the current parser cannot reproduce it exactly.

## Row rule schema

```json
{
  "id": "exclude-known-carryover",
  "source_sha256": "<64 lowercase hex characters>",
  "row_kind": "individual",
  "action": "exclude",
  "match": {
    "event_number": "109",
    "round": "Timed Final"
  },
  "expected_matches": 9
}
```

`action` is `include` or `exclude`. If a source SHA and row kind has one or more `include` rules, rows in that scope are excluded by default and only the union of matching include rules is eligible. Exclude rules are then applied.

Supported shared semantic fields are event number, event name, time type, normalized round, and status. Individual rules may also match placement, athlete name/age/team, seed/final time, DQ, no-show state, and exhibition state. Relay rules may match placement, team, relay letter, seed/final time, DQ, exhibition state, and relay-leg parse status. `duplicate_of_source_sha256` performs multiplicity-aware semantic identity matching against another selected source, deliberately ignoring placement changes in cumulative rankings but preserving individual and relay exhibition distinctions.

## Reconciled canonical packages

The current archive has ten canonical manifests: nine under `raw-data/sg-aquatics/events/` and the previously rebuild-verified 56th SNAG manifest at `raw-data/sg-aquatics/56th-snag-2026-full/manifest.json`.

| Package | Selected documents | Individual | Relay | Policy state and evidence |
|---|---:|---:|---:|---|
| SAQ ETP Championships 2026 | 1 | 410 | 0 | **ready**; exact result SHA `f92eb8550a009b487fc97ade5d69fbec237169b88186f661a273a1db946bcd39` |
| Singapore Short-Course Invitational 2026 | 4 | 1,419 | 42 | **ready**; four session reports selected, meet-wide combined report excluded |
| 11th SNSC 25m 2025 | 5 | 2,154 | 88 | **ready**; ten timed-final reprints excluded (3 + 4 + 3), Session 5 selected from `other_pdf`, nine `J` Judge's Decision relays retained |
| 21st SNSC 2026 | 8 | 3,540 | 53 | **ready**; the official Yu, Chengyou `NT` row is preserved as an explicit unknown outcome and 58 cumulative reprints are excluded |
| 47th SEA Age Group swimming 2025 | 3 | 1,410 | 48 | **ready**; only three competitive-swimming daily reports selected |
| 20th SNSC 2025 | 8 | 2,636 | 67 | **ready**; 38 timed-final carryovers excluded (9 + 9 + 16 + 4) |
| Singapore Swim Series 2025 | 10 | 9,043 | 0 | **ready**; two explicitly allowlisted January reports use the `other_pdf` category and the private-use encoded February report is normalized before detection |
| Singapore Swim Series 2026 | 12 | 9,204 | 0 | **ready** |
| 55th SNAG 2025 | 18 | 10,876 | 315 | **ready**; 207 individual reprints excluded and direct/alternate Day 6 relays selected explicitly |
| 56th SNAG 2026 | 17 | 10,906 | 348 | **ready**; the official source-marked exhibition swim (`X29.69`) is retained with its exhibition flag |

The 21st SNSC source row `--- *Yu, Chengyou 17 Nexus International School NT` is preserved as explicit `unknown` status with no result time. The parser returns 3,598 individual observations before curation; removing 58 proven cumulative reprints leaves the source-backed 3,540.

For 56th SNAG, the parser preserves `--- Chen, Jun Jie Zachary 17 Singapore Island Country Club 30.80 X29.69` as an official source-backed performance and marks it exhibition. Curation does not delete source facts merely to reproduce an older parser total. The exhibition flag is provenance only: fastest-recorded eligibility remains the existing finished + valid time + non-DQ rule.

Across all ten ready packages the canonical projection contains **51,598 individual + 961 relay = 52,559 performances**: **48,446 LCM** and **4,113 SCM**. LCM and SCM remain separate analytical domains.

## Per-package preview verification

From the repository root, set the read-only preview command once:

```bash
PREVIEW="backend/.venv/bin/python scripts/preview_archived_sgaquatics_event.py"
```

Each table row below is the literal manifest argument appended to `$PREVIEW`. Ready rows exited `0`; unresolved rows exited nonzero before any import or database access.

| Package | Command (`$PREVIEW …`) | Reconciliation result |
|---|---|---|
| SAQ ETP 2026 | `raw-data/sg-aquatics/events/saq-etp-championships-2026/manifest.json` | exit 0; 1 file, 410 individual, 0 relay |
| SSCI 2026 | `raw-data/sg-aquatics/events/singapore-short-course-invitational-2026/manifest.json` | exit 0; 4 files, 1,419 individual, 42 relay |
| 11th SNSC 25m 2025 | `raw-data/sg-aquatics/events/11th-singapore-national-swimming-championships-25m-2025/manifest.json` | exit 0; 5 files, 2,154 individual, 88 relay; rule matches 3/4/3 |
| 21st SNSC 2026 | `raw-data/sg-aquatics/events/21st-snsc-2026/manifest.json` | exit 0; 8 files, 3,540 individual, 53 relay; rule matches 21/37 |
| 47th SEA Age Group | `raw-data/sg-aquatics/events/47th-sea-age-group-aquatics-championships/manifest.json` | exit 0; 3 files, 1,410 individual, 48 relay |
| 20th SNSC 2025 | `raw-data/sg-aquatics/events/20th-snsc-2025/manifest.json` | exit 0; 8 files, 2,636 individual, 67 relay; rule matches 9/9/16/4 |
| Swim Series 2025 | `raw-data/sg-aquatics/events/singapore-swim-series-2025/manifest.json` | exit 0; 10 files, 9,043 individual, 0 relay; private-use report contributes 1,164 rows |
| Swim Series 2026 | `raw-data/sg-aquatics/events/singapore-swim-series-2026/manifest.json` | exit 0; 12 files, 9,204 individual, 0 relay |
| 55th SNAG 2025 | `raw-data/sg-aquatics/events/55th-snag-2025/manifest.json` | exit 0; 18 files, 10,876 individual, 315 relay |
| 56th SNAG 2026 | `raw-data/sg-aquatics/56th-snag-2026-full/manifest.json` | exit 0; 17 files, 10,906 individual, 348 relay; one source-marked exhibition swim retained |

Run the fast policy/manifest contract tests normally. Opt into parsing every ready immutable package when changing the parser or policies:

```bash
backend/.venv/bin/pytest backend/tests/test_package_curation.py -q
RUN_ARCHIVE_PACKAGE_TESTS=1 \
  backend/.venv/bin/pytest backend/tests/test_package_curation.py -q
```

The archive preview and tests do not import, stage, migrate, or commit data.

## Operator import

Only a `ready` package may proceed to the import command after preview review:

```bash
backend/.venv/bin/python scripts/import_archived_sgaquatics_event.py \
  raw-data/sg-aquatics/events/<package>/manifest.json \
  --title "Authoritative competition title"
```

Both commands resolve the same default policy. `--curation-policy PATH` is available for an explicit reviewed policy path. Import still performs its parser-confidence, metadata, PDF, hash, transaction, and archive checks after curation.
