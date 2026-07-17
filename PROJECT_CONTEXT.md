# Swim Analytics — Project Context

**Project:** SSA Swim Meet Results Platform
**Status:** Phase 2 (Integration) — ~85% Complete
**Last Updated:** 2026-07-04

**Workspace:** `/home/hermes/srv/hermes/workspace/swim-analytics/`

---

## REALITY CHECK (July 2026)

The previous PROJECT_CONTEXT was stale. Actual state is better than documented:

- ✅ Swimmer profile page — **BUILT** (367 lines, PBs + relays + progression charts)
- ✅ Meet detail page — **BUILT** (245 lines, events grouped, expandable)
- ✅ Next.js API proxy — **ALREADY CONFIGURED** (rewrites /api/* → backend)
- ✅ 8 REST endpoints — all implemented in main.py (1149 lines)
- ✅ PDF parser — 600+ lines, handles splits, DQs, relays, guests

The project is ~85-90% complete. Remaining work is deployment, not code.

---

## PROJECT VISION

Build a web platform for Singapore Swimming Association where coaches and swimmers can:
1. **Upload** HY-TEK Meet Manager PDF results
2. **Auto-parse** swimmer data (names, times, placements, DQs, splits)
3. **Browse** results by meet, event, or swimmer
4. **Track** personal bests and progression over time

**Problem:** Meet results live in unsearchable PDFs. Coaches manually track times in spreadsheets.

**Solution:** Upload PDF → structured database → instant insights.

---

## PROJECT STRUCTURE

```
swim-analytics/
├── frontend/              # Next.js 14 + TypeScript + Tailwind
│   ├── app/
│   │   ├── page.tsx              # Dashboard (stats, recent meets)
│   │   ├── upload/page.tsx       # PDF upload UI (drag & drop)
│   │   ├── results/page.tsx      # Results table (search, filters, pagination)
│   │   ├── swimmers/page.tsx     # Swimmers list + search
│   │   ├── swimmers/[id]/page.tsx # Swimmer profile + PBs + progression charts
│   │   ├── meets/[id]/page.tsx   # Meet detail + event groups
│   │   └── layout.tsx            # Nav header with SSA branding
│   ├── lib/
│   │   └── api.ts                # Typed API client (fetches backend)
│   ├── package.json
│   ├── next.config.js            # <-- API proxy to backend configured here
│   ├── SPEC.md                   # Full technical specification
│   └── tailwind.config.ts
│
└── backend/               # Python FastAPI + SQLAlchemy + pdfplumber
    ├── app/
    │   ├── main.py               # FastAPI app (8 endpoints, 1149 lines)
    │   ├── models.py             # SQLAlchemy models (Swimmer, Meet, Result, Relay)
    │   ├── schemas.py            # Pydantic request/response schemas
    │   ├── database.py           # PostgreSQL connection (DATABASE_URL from env)
    │   ├── api/                   # Additional API modules
    │   └── parsers/
    │       ├── base.py           # Parser dispatch
    │       └── hytek.py          # HY-TEK PDF parser (600+ lines)
    ├── alembic/                  # DB migrations
    ├── requirements.txt
    └── tests/                    # Parser tests
```

---

## WHAT'S COMPLETE

### Frontend (Next.js)
- [x] Dashboard page with SSA branding, stats cards, recent meets
- [x] Upload page with drag & drop, file validation, success/error states
- [x] Results page with search, filters (event/meet/DQ), pagination, medal badges
- [x] Navigation header (sticky, responsive, SSA logo)
- [x] Tailwind CSS with SSA color tokens (navy #0c2340, teal #00857c, gold #c4a35a)
- [x] API client (lib/api.ts) — typed fetch helpers for all endpoints

### Backend (FastAPI)
- [x] POST /api/upload — Upload & parse PDF, save to DB
- [x] GET /api/meets — List meets (paginated, searchable)
- [x] GET /api/meets/{id} — Meet detail with events grouped
- [x] GET /api/swimmers — List/search swimmers
- [x] GET /api/swimmers/{id} — Swimmer profile with PBs + recent results
- [x] GET /api/results — Query results with filters
- [x] GET /api/analytics/progression — Swimmer time progression for an event
- [x] CORS configured for localhost:3000
- [x] SQLAlchemy models match Prisma schema exactly

### PDF Parser (Python)
- [x] Uses pdfplumber for text extraction
- [x] Handles: prelims/finals, splits, reaction times, DQ codes
- [x] Handles: guest swimmers (*), tied placements, qualification markers (qMTS/MTS)
- [x] Handles: multi-page PDFs with continuation headers
- [x] Handles: all age groups, strokes, courses (LC/SC)
- [x] CLI for testing: `python app/parsers/hytek.py <pdf>`

### Database
- [x] PostgreSQL installed & running in WSL
- [x] Database: swim_analytics
- [x] Tables: Swimmer, Meet, Result (created via Prisma)
- [x] SQLAlchemy models match Prisma schema

---

## WHAT'S NOT DONE

### Integration Gaps (CRITICAL)
1. **Backend server not started** — Need to run `uvicorn app.main:app --reload`
2. **Frontend not proxying to backend** — API calls go to `/api/*` but backend runs on port 8000
3. **No E2E test completed** — Haven't uploaded real PDF and verified full flow

### Missing Features (Post-MVP)
- [ ] Swimmer profile page (frontend)
- [ ] Meet detail page (frontend)
- [ ] Progression charts (Recharts)
- [ ] Docker deployment
- [ ] Production deployment (Vercel + Railway)

---

## DATABASE SCHEMA

```prisma
model Swimmer {
  id        Int      @id @default(autoincrement())
  name      String
  age       Int?
  team      String?
  results   Result[]
  createdAt DateTime @default(now())
  updatedAt DateTime @updatedAt
}

model Meet {
  id        Int      @id @default(autoincrement())
  name      String
  date      DateTime
  location  String?
  results   Result[]
  createdAt DateTime @default(now())
  updatedAt DateTime @updatedAt
}

model Result {
  id         Int      @id @default(autoincrement())
  swimmerId  Int
  meetId     Int
  event      String
  time       String?
  seedTime   String?
  placement  Int?
  isDQ       Boolean  @default(false)
  dqCode     String?
  dqDescription String?
  isGuest    Boolean  @default(false)
  qualifier  String?
  reactionTime String?
  splits     String?  // JSON string
  swimmer    Swimmer  @relation(fields: [swimmerId], references: [id])
  meet       Meet     @relation(fields: [meetId], references: [id])
}
```

---

## DEPLOYMENT PLAN (Sharklet — KIV)

### Target Architecture
```
sharklet-apex (control-plane, NVMe)
  └─ PostgreSQL (single instance, shared across apps)
       └─ DB: swim_analytics  (user: swim_admin)

Worker node (sharklet-2 or sharklet-3)
  ├─ Backend (FastAPI, port 8000)
  └─ Frontend (Next.js, port 3000)

  swim.sharklet.lan  →  ingress-nginx  →  frontend  →  proxy  →  backend
```

### Phase 1: Infrastructure
- [ ] Install PostgreSQL on sharklet-apex
- [ ] Create database swim_analytics + user swim_admin
- [ ] Document connection string (for future migration reference)

### Phase 2: Code Fixes (Before Deployment)
- [ ] Create backend/.env — DATABASE_URL pointing to apex PG
- [ ] Update CORS origins — add swim.sharklet.lan
- [ ] Update next.config.js proxy — point to backend service name
- [ ] Fix Python 3.13 compatibility (psycopg2-binary version)

### Phase 3: Kubernetes Deployment (fleet-infra)
- [ ] Create clusters/sharklet/apps/swim-backend/  (deployment, service, ingress)
- [ ] Create clusters/sharklet/apps/swim-frontend/  (deployment, service, ingress)
- [ ] Register in clusters/sharklet/apps/kustomization.yaml
- [ ] Push → Flux reconciles → live at swim.sharklet.lan

### Phase 4: E2E Verification
- [ ] Upload test PDF → verify parsing
- [ ] Browse results, swimmers, meets
- [ ] Check progression charts and PB tracking

### Immediate Next Steps (When Ready to Execute)
```bash
# Backend
cd /home/hermes/srv/hermes/workspace/swim-analytics/backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# Frontend
cd /home/hermes/srv/hermes/workspace/swim-analytics/frontend
npm install
npm run dev -- -p 3000
```

### Known Issues To Fix
1. **CORS** — only allows localhost:3000/3001, needs swim.sharklet.lan
2. **Proxy destination** — hardcoded to localhost:8000, needs backend service name
3. **DATABASE_URL** — defaults to localhost, needs env file pointing to apex
4. **Python 3.13** — some pinned packages may need version bumps
5. **No .env** — database credentials exposed in database.py default

---

## TESTING

### Run Parser Tests
```bash
cd /home/hermes/srv/hermes/workspace/swim-analytics/backend
pytest tests/ -v
```

### Test API Endpoints
```bash
# Health check
curl http://localhost:8000/

# List meets (after upload)
curl http://localhost:8000/api/meets

# List results
curl http://localhost:8000/api/results
```

---

## TECH STACK

| Layer           | Technology                                     |
| --------------- | ---------------------------------------------- |
| Frontend        | Next.js 14, React 18, TypeScript, Tailwind CSS |
| Backend         | Python 3.11+, FastAPI, SQLAlchemy, Pydantic    |
| Database        | PostgreSQL 15                                  |
| PDF Parsing     | pdfplumber, pdfminer.six                       |
| ORM (FE)        | Prisma                                         |
| Charts (Future) | Recharts                                       |

---

## KEY FILES TO READ FIRST

1. `backend/app/main.py` — All API endpoints
2. `backend/app/parsers/hytek.py` — PDF parser logic
3. `frontend/app/page.tsx` — Dashboard UI
4. `frontend/lib/api.ts` — API client types & fetch helpers
5. `frontend/SPEC.md` — Full technical specification

---

## MVP DEFINITION

MVP is complete when:
- [ ] User can upload a HY-TEK PDF
- [ ] Results are parsed and saved to database
- [ ] Results page shows real data from DB
- [ ] Search by swimmer name works

Not required for MVP:
- Swimmer profile pages
- Progression charts
- Meet detail pages
- Authentication

---

## COMMON COMMANDS

```bash
# Backend
cd /home/hermes/srv/hermes/workspace/swim-analytics/backend
source venv/bin/activate
uvicorn app.main:app --reload --port 8000

# Frontend
cd /home/hermes/srv/hermes/workspace/swim-analytics/frontend
npm run dev -- -p 3000

# Parser test
cd backend
python app/parsers/hytek.py <pdf_path> --verbose

# Run pytest
cd backend
pytest tests/ -v
```

---

## KNOWN ISSUES / GOTCHAS

1. **API calls fail** — Backend not running or proxy not configured
2. **CORS errors** — Backend CORS only allows localhost:3000/3001 (needs updating for deployment)
3. **Database connection** — Ensure PostgreSQL running: `sudo service postgresql start`
4. **Parser edge cases** — Test with multiple PDFs, may need regex tweaks
5. **Python 3.13** — This Pi runs Python 3.13.5; some pinned package versions may need bumps

---

## CURRENT CONTEXT

- **Session date:** 2026-07-04
- **Last action:** Full codebase audit, stale references fixed, deployment plan drafted
- **Next action (KIV):** Execute Phase 1 (PostgreSQL on apex), then Phase 2 (code fixes), then Phase 3 (k8s deploy)
- **Test PDF available:** `56th-snag-seniors-2026-results-day-1-session-1.pdf`
- **Target hostname:** `swim.sharklet.lan`

---

## PROJECT MANTRA

> "Upload PDF → Structured Data → Instant Insights"
>
> Keep it simple. Make it work. Then make it pretty.
