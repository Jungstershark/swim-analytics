# Implementation Slice 1 Status — Shared Ingestion Core

## Current Status

Implementation is complete for the website upload/shared-ingestion foundation, pending final role-agent review results and live deployment decisions.

## Implemented

- Added shared ingestion helper module: `backend/app/ingestion.py`.
- Added ingestion/provenance models:
  - `RawDocument`
  - `SourceReference`
  - `DocumentClassification`
  - `ParseJob`
  - `IngestionRun`
- Added provenance columns to `Result` and `RelayResult`:
  - `sourceDocumentSha256`
  - `parseJobId`
  - `ingestionRunId`
  - `parserVersion`
  - `sourceEventNumber`
- Kept `/api/upload/preview` non-mutating.
- Wired `/api/upload` to archive raw docs, record parse jobs/ingestion run, and attach provenance to imported results.
- Added import eligibility gate:
  - importable: `overall_results`, `other_pdf` if parser/confidence passes
  - skipped/archive-only: `age_group_results`, `start_list`, `medal_tally`, `event_information`
- Fixed classifier precedence so result/start-list/medal/age-group-result signals beat broad meet-title words like `Championships`/`Cships`.
- Added frontend warning display for backend `errors` on upload success.
- Added real Alembic migration: `backend/alembic/versions/c2f7a6d9e801_add_ingestion_provenance.py`.
- Updated Alembic env model imports.

## Validation

- Backend tests: `37 passed, 29 skipped, 2 warnings`.
- Frontend build: `npm run build` passed.
- Python compile check passed for changed backend/migration files.
- Migration validation against simulated existing SQLite DB stamped at `b0aed82fb3bd` passed:
  - `MIGRATION_EXISTING_SCHEMA_VALIDATION_OK`
- Migration write validation also passed after replacing PostgreSQL-only `now()` defaults with dialect-portable `sa.func.now()`:
  - `MIGRATION_EXISTING_SCHEMA_WRITE_VALIDATION_OK`

## Important Migration Note

The historical Alembic baseline migrations are mostly stubs. Therefore `alembic upgrade head` from a completely empty DB does not create the existing legacy schema before this new migration alters `Result` and `RelayResult`.

The new migration was validated against the realistic path for the current deployed app: an existing pre-provenance schema stamped at previous head `b0aed82fb3bd`, then upgraded to `c2f7a6d9e801`.

A future cleanup should replace/fix the historical baseline if fresh DB bootstrap via Alembic is desired.

- Domain-model alignment note created: `docs/domain-model-roadmap.md`.
- Current implementation intentionally treats `Swimmer` as parsed-person v0 and `Meet` as competition v0; deeper athlete identity, sessions, normalized events, clubs, and ranking contexts are staged future models rather than hidden assumptions.

- Multi-competition SG Aquatics discovery added:
  - `scripts/discover_sgaquatics_events.py`
  - `scripts/archive_sgaquatics_events.py`
  - `scripts/preview_archived_sgaquatics_event.py`
  - `docs/sg-aquatics-event-discovery.md`
- First non-SNAG smoke test archived/previewed SAQ ETP Championships 2026: 1 result PDF, 15 events, 410 individual results, 100% parser confidence after single-day HY-TEK header fix, 0 failures.

- Parser-routing architecture added:
  - explicit `DetectionResult`
  - `detect_parser(...)` selects the highest-confidence parser candidate
  - existing HY-TEK parser remains the only active parser and is not broadened
  - preview JSON now includes `parser_version`, `detection_confidence`, and `detection_reason`
  - architecture documented in `docs/parser-routing-and-json-architecture.md`

- Source Monitoring Foundation backend added after Gate 1 review:
  - `SourceSite`, `SourceRule`, `SourceEvent`, `SourceEventDocument`, `MonitorRun` models;
  - source monitoring service in `backend/app/source_monitoring.py`;
  - admin API helpers/endpoints for sources, events, monitor runs, and manual discovery preview;
  - live SG Aquatics adapter wired to the existing discovery script;
  - migration `d4b63ef2a9c0_add_source_monitoring_foundation.py`;
  - tests in `backend/tests/test_source_monitoring.py`.
- Live adapter smoke test against SG Aquatics succeeded in a temp DB: 10 events, 241 documents, 9 events with results, 0 domain rows created.
- Migration validation succeeded from simulated pre-provenance revision `b0aed82fb3bd` through `c2f7a6d9e801` and `d4b63ef2a9c0` with representative inserts: `SOURCE_MONITORING_MIGRATION_VALIDATION_OK`.

- Gate 2 backend review blockers addressed:
  - canonical URL identity enforced at service boundary;
  - discovered event/document canonical duplicates are de-duped before DB mutation;
  - failed preview runs roll back source catalog mutations while preserving failed `MonitorRun` audit record;
  - partial unique running-run guard prevents more than one running monitor per rule;
  - `/api/admin/sources` includes `lastRun`, last counts/status, and readable `policyLabels` for frontend display;
  - manual-run endpoint maps missing/disabled/already-running errors to HTTP-safe statuses.
- Verification after Gate 2 fixes: `51 passed, 29 skipped, 2 warnings`; live adapter temp DB smoke still `10 events / 241 docs / 0 domain rows`; migration + running guard validation `SOURCE_MONITORING_MIGRATION_AND_RUNNING_GUARD_OK`.

- canonical document identity tightened after focused data/domain re-review:
  - `SourceEventDocument` identity is now `(sourceEventId, canonical URL)`;
  - filename/category are retained as mutable metadata, not identity;
  - regression test covers same PDF URL with different filename/category metadata;
  - migration validation confirms duplicate canonical document URL is rejected.
- Verification after document identity fix: `52 passed, 29 skipped, 2 warnings`; live adapter temp DB smoke still `10 events / 241 docs / 0 domain rows`; migration validation `SOURCE_MONITORING_MIGRATION_DOCUMENT_IDENTITY_OK`.

- Frontend admin Sources page implemented:
  - `/admin/sources` displays source sites/rules, readable policy labels, manual-only/no-scheduler posture, auto-import disabled, latest monitor run counters, source events, and recent monitor runs.
  - Frontend API helpers added for source monitoring endpoints; nav link added.
  - `npm run build` passed with `/admin/sources` route present.
  - Temp DB smoke through Next rewrites passed: manual discovery preview succeeded with 10 events / 9 result-ready / 241 docs / 9 action-required, then admin APIs reflected the run.
  - Browser visual smoke was blocked because Chrome is not installed in this environment.

- Gate 3 review blockers addressed:
  - frontend now explicitly says discovery preview only catalogs source event/document links and does not import swim results;
  - ambiguous document counters renamed away from “docs added” toward “document links” / “catalog docs”;
  - success/failure banners remain visible after refresh;
  - frontend load requests use sequencing + unmount guard;
  - mobile Sources navigation added and inert mobile menu button removed;
  - startup `create_all()` is now explicit local-dev opt-in only;
  - `GET /api/admin/sources` is read-only;
  - default SG Aquatics source/rule seeding moved to Alembic migration.
- Gate 3 fix verification: backend `53 passed, 29 skipped, 2 warnings`; frontend `npx tsc --noEmit && npm run build` passed; `git diff --check` passed; release-style migration/read-only GET validation passed; release-style temp DB smoke through Next rewrites passed.

## Pending / Not Yet Done

- SG Aquatics archive CLI preview/import wiring.
- Live Sharklet/Postgres migration/deployment.
- Git commit/push of source repo changes; earlier GitHub auth was unavailable from this machine.
