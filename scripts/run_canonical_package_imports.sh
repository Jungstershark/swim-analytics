#!/bin/sh
# Import every canonical SG Aquatics package and assert the per-package totals.
#
# This is the harness the cluster Job runs. It is deliberately explicit: the
# table below is the reviewable record of what each package must insert, so a
# regression shows up as a MISMATCH instead of a silent partial import.
#
#   TARGET_DB=swim_analytics_rehearsal ./scripts/run_canonical_package_imports.sh
#   DRY_RUN=1 TARGET_DB=...          ./scripts/run_canonical_package_imports.sh
#
# TARGET_DB is required and is verified against `current_database()` before any
# write, so a rehearsal can never land in production by accident. The expected
# counts are individual + relay results; a package that is already loaded will
# report 0 inserted, so use DRY_RUN=1 to verify an already-imported database.
set -eu

TARGET_DB="${TARGET_DB:?TARGET_DB must name the database to import into}"
ARCHIVE_ROOT="${ARCHIVE_ROOT:-/work/raw-documents}"
DRY_RUN="${DRY_RUN:-0}"

python3 - "$TARGET_DB" <<'PY'
import os, sys
from sqlalchemy import create_engine, text
expected = sys.argv[1]
with create_engine(os.environ["DATABASE_URL"]).connect() as connection:
    actual = connection.execute(text("select current_database()")).scalar_one()
if actual != expected:
    raise SystemExit(f"refusing to write: connected to {actual}, expected {expected}")
print(f"target_verified {actual}")
PY

alembic -c backend/alembic.ini upgrade head

run_one() {
  manifest="$1"; policy="$2"; title="$3"; expected="$4"; identity="${5:-}"
  extra=""
  [ -n "$identity" ] && extra="--identity $identity"

  python3 scripts/preview_archived_sgaquatics_event.py "$manifest" \
    --curation-policy "$policy" --title "$title" $extra >/work/preview.out
  if [ "$DRY_RUN" = "1" ]; then
    printf 'DRY-RUN %s preflight ok\n' "$title"
    return 0
  fi

  out="$(python3 scripts/import_archived_sgaquatics_event.py "$manifest" \
    --curation-policy "$policy" --title "$title" $extra --archive-root "$ARCHIVE_ROOT")"
  actual="$(printf '%s' "$out" | python3 -c 'import json,sys; print(json.load(sys.stdin)["results_inserted"])')"
  printf '%s inserted=%s expected=%s\n' "$title" "$actual" "$expected"
  if [ "$actual" != "$expected" ]; then
    printf 'MISMATCH %s expected=%s actual=%s\n' "$title" "$expected" "$actual"
    exit 1
  fi
}

# canonical package                                  title                                   expected
run_one raw-data/sg-aquatics/events/55th-snag-2025/manifest.json config/package-curation/55th-snag-2025.json '55th SNAG 2025' 11191
run_one raw-data/sg-aquatics/events/20th-snsc-2025/manifest.json config/package-curation/20th-snsc-2025.json '20th SNSC 2025' 2703 config/package-identity/20th-snsc-2025.json
run_one raw-data/sg-aquatics/events/singapore-swim-series-2025/manifest.json config/package-curation/singapore-swim-series-2025.json 'Singapore Swim Series 2025' 9043
run_one raw-data/sg-aquatics/events/11th-singapore-national-swimming-championships-25m-2025/manifest.json config/package-curation/11th-singapore-national-swimming-championships-25m-2025.json '11th Singapore National Swimming Championships (25m) 2025' 2242
run_one raw-data/sg-aquatics/events/47th-sea-age-group-aquatics-championships/manifest.json config/package-curation/47th-sea-age-group-aquatics-championships.json '47th SEA AGE Group Aquatics Championships' 1458
run_one raw-data/sg-aquatics/events/singapore-swim-series-2026/manifest.json config/package-curation/singapore-swim-series-2026.json 'Singapore Swim Series 2026' 9204
run_one raw-data/sg-aquatics/56th-snag-2026-full/manifest.json config/package-curation/56th-snag-2026-full.json '56th SNAG 2026' 11254
run_one raw-data/sg-aquatics/events/21st-snsc-2026/manifest.json config/package-curation/21st-snsc-2026.json '21st SNSC 2026' 3593
run_one raw-data/sg-aquatics/events/saq-etp-championships-2026/manifest.json config/package-curation/saq-etp-championships-2026.json 'SAQ ETP Championships 2026' 410
run_one raw-data/sg-aquatics/events/singapore-short-course-invitational-2026/manifest.json config/package-curation/singapore-short-course-invitational-2026.json 'Singapore National Swimming SCM Invitational' 1461

printf 'CANONICAL_IMPORT_COMPLETE\n'
