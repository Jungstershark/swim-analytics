# Swim Analytics — Project Context

**Project:** SSA Swim Meet Results Platform
**Status:** Phase 2 (Integration) — ~75% Complete
**Last Updated:** 2026-03-28

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
.openclaw/workspace/Projects/swim_analytics_project/
├── frontend/              # Next.js 14 + TypeScript + Tailwind
│   ├── app/
│   │   ├── page.tsx              # Dashboard (stats, recent meets)
│   │   ├── upload/page.tsx       # PDF upload UI (drag & drop)
│   │   ├── results/page.tsx      # Results table (search, filters, pagination)
│   │   └── layout.tsx            # Nav header with SSA branding
│   ├── lib/
│   │   ├── api.ts                # Typed API client (fetches backend)
│   │   ├── db.ts                 # Prisma client singleton
│   │   └── parsers/hytek.ts      # Node.js parser (backup, not primary)
│   ├── prisma/
│   │   └── schema.prisma         # DB schema (Swimmer, Meet, Result)
│   ├── package.json
│   └── SPEC.md                   # Full technical specification
│
└── backend/               # Python FastAPI + SQLAlchemy + pdfplumber
    ├── app/
    │   ├── main.py               # FastAPI app (7 endpoints)
    │   ├── models.py             # SQLAlchemy models (matches Prisma)
    │   ├── schemas.py            # Pydantic request/response schemas
    │   ├── database.py           # PostgreSQL connection
    │   └── parsers/
    │       └── hytek.py          # PDF parser (600+ lines, production-grade)
    ├── requirements.txt
    ├── .env                      # DATABASE_URL
    └── venv/                     # Python virtual environment
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

## IMMEDIATE NEXT STEPS (MVP Completion)

### Step 1: Start Backend Server
```bash
cd /home/jungyi-test/.openclaw/workspace/Projects/swim_analytics_project/backend
source venv/bin/activate
uvicorn app.main:app --reload --port 8000
```

### Step 2: Configure Next.js API Proxy
Add to `frontend/next.config.js`:
```js
module.exports = {
  async rewrites() {
    return [
      {
        source: '/api/:path*',
        destination: 'http://localhost:8000/api/:path*',
      },
    ]
  },
}
```

### Step 3: Restart Frontend
```bash
cd /home/jungyi-test/.openclaw/workspace/Projects/swim_analytics_project/frontend
npm run dev -- -p 3001
```

### Step 4: Test End-to-End
1. Open http://localhost:3001
2. Click "Upload Results"
3. Upload: `56th-snag-seniors-2026-results-day-1-session-1.pdf`
4. Verify success message shows results count
5. Go to Results page, verify data appears
6. Search for "WU, Dylan" — should see 2:18.62 in 200 IM

### Step 5: Validate Parser Accuracy
```bash
cd backend
python app/parsers/hytek.py /path/to/56th-snag-seniors.pdf --verbose
```
Compare output to original PDF — verify all times, placements, DQs extracted correctly.

---

## TESTING

### Run Parser Tests
```bash
cd backend
pytest app/parsers/__tests__/test_hytek.py -v
```

### Test API Endpoints
```bash
# Health check
curl http://localhost:8000/api/health

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
cd backend
source venv/bin/activate
uvicorn app.main:app --reload --port 8000

# Frontend
cd frontend
npm run dev -- -p 3001

# Database
cd frontend
npm run db:studio    # Open Prisma Studio

# Parser test
cd backend
python app/parsers/hytek.py <pdf_path> --verbose

# Run pytest
cd backend
pytest app/parsers/__tests__/test_hytek.py -v
```

---

## KNOWN ISSUES / GOTCHAS

1. **API calls fail** — Backend not running or proxy not configured
2. **CORS errors** — Backend CORS only allows localhost:3000
3. **Database connection** — Ensure PostgreSQL running: `sudo service postgresql start`
4. **Parser edge cases** — Test with multiple PDFs, may need regex tweaks

---

## CURRENT CONTEXT

- **Session date:** 2026-03-28
- **Last action:** Comprehensive project review completed
- **Next action:** Start backend, configure proxy, test E2E upload flow
- **Test PDF available:** `56th-snag-seniors-2026-results-day-1-session-1.pdf`

---

## PROJECT MANTRA

> "Upload PDF → Structured Data → Instant Insights"
>
> Keep it simple. Make it work. Then make it pretty.
