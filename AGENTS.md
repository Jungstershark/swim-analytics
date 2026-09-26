# AGENTS.md — swim-analytics

Applies to the whole repository. `frontend/AGENTS.md` adds Next.js-specific rules on top
of this file, and `CLAUDE.md` at the root imports this document.

---

## 1. Where you are working from — read this before anything else

This repository is built and tested in **three different places**, and they are not
interchangeable. Know which one you are in before you decide how to do a task.

**A. A developer machine (a laptop, including macOS).** This is where you are. It has the
full toolchain and no production access of any kind, by design. Everything in this repo —
the backend, the frontend, the parser, the migrations, the test suite, and the full corpus
of source PDFs — can be built, run, and exercised here. That is the point: you should be
able to do nearly all work without ever touching the cluster.

**B. Production.** A private k3s cluster on the operator's homelab, behind a tailnet. The
backend holds the live Postgres connection; that database is the product. The ingress
hostname is recorded in `PROJECT_CONTEXT.md` and in the app manifests of the separate
`fleet-infra` repository.

From a developer machine, production is **read-only**: `curl` the health endpoint and the
read-only API routes to verify behaviour. Nothing else. Do not write to it, do not
connect to its database, do not read its secret.

**C. The release path.** Deploying is *not* done from this repository. The k3s deployment
pins an exact commit SHA in `expected_sha=` inside `backend-deployment.yaml` and
`frontend-deployment.yaml`; each pod `git clone`s that commit at start-up and asserts HEAD
matches. A release therefore has two parts: merge to `main` here, then bump both pins (and
the matching `swim-analytics/source-rollout` pod-template annotation) in the `fleet-infra`
repository and let Flux reconcile. **Bumping those pins is not your job.**

**The rule that follows from all of this:** work locally, verify locally, and open a pull
request. If a task appears to require production write access, a production credential, or
a release step, stop and hand it back to the operator instead of finding a workaround.
Being unable to reach the production database from a laptop is a feature of this setup,
not an obstacle to route around.

---

## 2. The data plane — hard rules

The developer machine is on the same tailnet as production, which means production
Postgres *is* reachable from here. That reachability is exactly why these rules exist:

- **Never set `DATABASE_URL` to a production host.** Local or sandbox databases only. The
  local convention is Postgres in Docker on port **5433** (deliberately not 5432), so a
  mistake is visible in a process list.
- **Never read or handle `swim-db-secret`**, or any production credential, from a
  developer machine.
- The only sanctioned write paths into production data are (1) the in-cluster import Job,
  which refuses to run unless `current_database()` equals its declared `TARGET_DB`, and
  (2) `alembic upgrade head`, which runs inside the pod at rollout.
- Migrations are Alembic-backed and production startup is deliberately read-only. Leave
  `SWIM_ANALYTICS_CREATE_ALL_ON_STARTUP` unset.
- Anything that loads competition packages into a database is a deliberate, separate
  operation — never a side effect of a release or a test run.

---

## 3. The repository is public

`Jungstershark/swim-analytics` is public, and it has to be: production pods clone it over
anonymous HTTPS with no token. Consequences:

- Never commit real athlete-level personal data, credentials, `.env` files, database
  dumps, or anything copied out of a production secret.
- Never commit PDFs or generated artifacts (`raw-data/**/*.pdf` is gitignored; keep it
  that way).
- Treat every commit message, doc, and comment as world-readable.

---

## 4. Where the truth lives

- **`PROJECT_CONTEXT.md` is stale — history only.** It describes a mid-2026 state
  ("~85% complete", "deployment KIV", "Next.js 14", "PostgreSQL not installed on apex")
  that no longer matches reality: the app has been live for months and now runs a
  canonical competition-package ingestion pipeline. Do not make decisions from it.
- Prefer, in order: `docs/` newest-first (`ls -t docs/`) → `git log --oneline -25` → the
  `config/` curation policy → the test suite, which encodes the domain invariants better
  than any prose document.
- Commit subjects are descriptive and are prefixed `[verified]` when the author ran the
  relevant gate for that change. That prefix is a claim about verification — do not add it
  to a commit of your own unless you actually ran the gate.

---

## 5. Environment and gates

**Backend** — Python 3.13 (matches the production image):

```bash
cd backend && python3.13 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m pytest tests/ -q        # gate: 195 passed, 1 skipped, ~34s
```

The suite needs **no database**: it creates SQLite temp databases per test and even runs a
real `alembic upgrade head` against SQLite. Do not stand up Postgres to run unit tests. The
single skip is `RUN_ARCHIVE_PACKAGE_TESTS=1`-gated and parses the whole corpus. A pass
count lower than 195 means the environment is wrong — stop and report, do not proceed.

**Frontend** — Node ≥ 20.9 is mandatory (Next.js 16 dropped Node 18):

```bash
cd frontend && npm ci && npm run lint && npm run build
```

**Corpus** — every source PDF is gitignored, but every manifest is tracked and records the
`url`, `bytes`, and `sha256` of each document, so the raw library is reproducible from the
repository alone:

```bash
python scripts/restore_raw_library.py --dry-run     # plan
python scripts/restore_raw_library.py               # 273 documents, byte-verified
```

This is a replay, not a re-scrape: it never re-reads the source event page, so it produces
the same bytes the manifests were written against, and it discards any download whose size
or sha256 disagrees. A mismatch is a real signal — report it, do not paper over it.

**Running the app** (only this needs a database):

```bash
docker run -d --name swim-pg -e POSTGRES_USER=swim_admin -e POSTGRES_PASSWORD=localdev \
  -e POSTGRES_DB=swim_dev -p 5433:5432 postgres:17
export DATABASE_URL='postgresql://swim_admin:localdev@localhost:5433/swim_dev'
cd backend && alembic -c alembic.ini upgrade head && uvicorn app.main:app --reload --port 8000
```

The frontend dev server proxies `/api/*` to port 8000. Then upload a restored PDF through
the real UI — that is the actual end-to-end path, and it is the only way to know a change
to parsing or ingestion really works.

**Known macOS snag:** `frontend/playwright.config.ts` hardcodes `executablePath:
"/usr/bin/chromium"`, a Linux path. Drop that line *locally* to run e2e; do not commit the
removal, because the cluster uses that path.

---

## 6. Verification culture

This project's value is that its numbers are trustworthy. So:

- **Exercise real input.** A parser or ingestion change verified only against a
  hand-written fixture string is not verified. Parse a restored PDF and read the output. A
  change that passes tests while mis-parsing a real session is a regression, not progress.
- Ingestion asserts totals after import, and reports `MISMATCH <title> expected=… actual=…`
  rather than silently loading a partial package. Preserve that property in anything you
  add: fail loudly, never partially.
- Domain invariants — competition hierarchy, athlete identity and entity resolution,
  source provenance, page-size and course handling — are load-bearing. Read
  `docs/competition-domain-and-rebuild-architecture.md` and the relevant tests before
  changing them.
- `[verified]` in a commit subject means the gate for that change was actually run.

---

## 7. Workflow

1. Branch from up-to-date `main`: `feat/<topic>` or `fix/<topic>`.
2. Smallest change that closes the task; match surrounding style.
3. Run the gates: pytest always; `npm run lint` + `npm run build` if you touched
   `frontend/`; parse a real PDF if you touched parsing or ingestion.
4. Commit with a declarative subject, `[verified]` only if you ran the gate.
5. Push the branch and open a pull request against `main`. State what you changed, what you
   ran, and what you could **not** verify.
6. **Never push to `main`.** It is the release branch and the deployment pins assume it is
   stable. Merging and releasing happen after review, from the host side.

Definition of done: pytest green with no regression from 195 passed / 1 skipped; any
parsing change backed by a real corpus PDF; any schema change shipping an Alembic revision
with an empty database still upgrading to head; lint and build clean for frontend changes;
and nothing in the diff touching production data, credentials, or release pins.
