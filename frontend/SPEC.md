# Swim Analytics Platform - Technical Specification

> SSA Swim Meet Results Parsing & Analytics Platform

**Version:** 1.0.0
**Last Updated:** 2026-03-27
**Status:** In Development (MVP Phase)

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Architecture](#2-architecture)
3. [API Endpoints](#3-api-endpoints)
4. [Database Schema](#4-database-schema)
5. [PDF Parsing](#5-pdf-parsing)
6. [Frontend Pages](#6-frontend-pages)
7. [Current Status](#7-current-status)
8. [Next Steps](#8-next-steps)

---

## 1. Project Overview

### Purpose

Swim Analytics is a web platform built for the Singapore Swimming Association (SSA) to digitise, store, and analyse swim meet results. Coaches, swimmers, and administrators upload HY-TEK Meet Manager PDF result sheets, which are automatically parsed and stored in a structured database. The platform provides browsable results, swimmer profiles with personal bests, and progression analytics over time.

### Goals

- **Digitise meet results** - Eliminate manual data entry by parsing HY-TEK PDF exports automatically.
- **Centralise swimmer data** - Maintain a single source of truth for all meet results, linked to swimmer profiles.
- **Track performance** - Surface personal bests, time progressions, and trends across meets and events.
- **Enable analysis** - Provide coaches with tools to evaluate swimmer development and compare performance.

### Scope (MVP)

| In Scope | Out of Scope (Future) |
|---|---|
| HY-TEK PDF upload & parsing | Live meet integration |
| Meet results storage & browsing | Multi-tenancy / club accounts |
| Swimmer profiles with personal bests | Relay result parsing |
| Basic progression charts | Split/lap analysis |
| Results filtering & search | Export to CSV/Excel |
| DQ/DNS/DNF handling | Authentication & authorization |

---

## 2. Architecture

### High-Level Diagram

```
┌─────────────────────────────────────────────────────────┐
│                      Frontend                           │
│              Next.js 14 (App Router)                    │
│         React 18 + TypeScript + Tailwind CSS            │
│                                                         │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────┐  │
│  │Dashboard │  │  Upload  │  │ Results  │  │Analytics│  │
│  │  Page    │  │  Page    │  │  Page    │  │  Page   │  │
│  └──────────┘  └──────────┘  └──────────┘  └────────┘  │
└────────────────────────┬────────────────────────────────┘
                         │
                    HTTP / JSON
                         │
┌────────────────────────┴────────────────────────────────┐
│                    API Layer                             │
│                                                         │
│  ┌─────────────────────────────────────────────────┐    │
│  │  Next.js API Routes (Current MVP)               │    │
│  │  POST /api/upload                               │    │
│  └─────────────────────────────────────────────────┘    │
│                                                         │
│  ┌─────────────────────────────────────────────────┐    │
│  │  Python FastAPI Backend (Planned)               │    │
│  │  Full REST API for meets, swimmers, results,    │    │
│  │  analytics                                      │    │
│  └─────────────────────────────────────────────────┘    │
└────────────────────────┬────────────────────────────────┘
                         │
                     Prisma ORM
                         │
┌────────────────────────┴────────────────────────────────┐
│                    PostgreSQL                            │
│                                                         │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐              │
│  │ Swimmer  │  │   Meet   │  │  Result  │              │
│  └──────────┘  └──────────┘  └──────────┘              │
└─────────────────────────────────────────────────────────┘
```

### Tech Stack

| Layer | Technology | Version | Purpose |
|---|---|---|---|
| **Framework** | Next.js (App Router) | 14.2.5 | SSR, routing, API routes |
| **UI** | React | 18.3.1 | Component rendering |
| **Language** | TypeScript | 5.5.3 | Type safety |
| **Styling** | Tailwind CSS | 3.4.19 | Utility-first CSS with SSA brand tokens |
| **ORM** | Prisma | 5.17.0 | Database access & migrations |
| **Database** | PostgreSQL | 15+ | Persistent storage |
| **PDF Parsing** | pdf-parse | 1.1.1 | PDF text extraction |
| **Charts** | Recharts | 2.12.7 | Progression & analytics visualisation |
| **Backend (Planned)** | Python FastAPI | TBD | Dedicated API server |

### SSA Brand Tokens

Defined in `tailwind.config.ts`:

| Token | Hex | Usage |
|---|---|---|
| `ssa-navy` | `#0c2340` | Primary backgrounds, headings |
| `ssa-navy-light` | `#1a3a5c` | Hover states, secondary backgrounds |
| `ssa-teal` | `#00857c` | Primary actions, CTAs |
| `ssa-teal-light` | `#00a89d` | Hover states for primary actions |
| `ssa-teal-dark` | `#006b63` | Active states |
| `ssa-gold` | `#c4a35a` | Accents, highlights, medals |
| `ssa-slate` | `#3d4f5f` | Body text, secondary elements |

---

## 3. API Endpoints

### Currently Implemented (Next.js API Routes)

#### `POST /api/upload`

Upload a HY-TEK PDF file, parse it, and save results to the database.

**Request:**
- Content-Type: `multipart/form-data`
- Body: `file` (PDF, max size TBD)

**Response (200):**
```json
{
  "success": true,
  "meet": {
    "id": "clxyz...",
    "name": "47th Singapore National Age Group Championships",
    "date": "2024-03-15T00:00:00.000Z"
  },
  "resultsCount": 156,
  "swimmersCount": 42
}
```

**Error Response (400/500):**
```json
{
  "error": "No file provided"
}
```

**Implementation:** `app/api/upload/route.ts`
- Extracts text from PDF via `pdf-parse`
- Parses with `parseHytekResults()` from `lib/parsers/hytek.ts`
- Creates/finds `Meet` record
- Finds or creates `Swimmer` records (matched by name + team)
- Creates `Result` records for each parsed entry

---

### Planned REST API (Full Backend)

These endpoints are required for the complete platform. They can be implemented either as Next.js API routes or as a separate Python FastAPI service.

---

#### Meets

##### `GET /api/meets`

List all meets with pagination and optional filtering.

**Query Parameters:**
| Parameter | Type | Default | Description |
|---|---|---|---|
| `page` | integer | 1 | Page number |
| `limit` | integer | 20 | Results per page (max 100) |
| `search` | string | - | Search by meet name |
| `from` | date | - | Filter meets on or after this date |
| `to` | date | - | Filter meets on or before this date |
| `sort` | string | `date` | Sort field: `date`, `name` |
| `order` | string | `desc` | Sort order: `asc`, `desc` |

**Response (200):**
```json
{
  "data": [
    {
      "id": "clxyz...",
      "name": "47th Singapore National Age Group Championships",
      "date": "2024-03-15",
      "location": "OCBC Aquatic Centre",
      "resultCount": 256,
      "swimmerCount": 84,
      "createdAt": "2024-03-20T10:30:00.000Z"
    }
  ],
  "pagination": {
    "page": 1,
    "limit": 20,
    "total": 45,
    "totalPages": 3
  }
}
```

---

##### `GET /api/meets/:id`

Get full meet details including all results.

**Path Parameters:**
| Parameter | Type | Description |
|---|---|---|
| `id` | string | Meet ID |

**Query Parameters:**
| Parameter | Type | Default | Description |
|---|---|---|---|
| `event` | string | - | Filter by event name |
| `ageGroup` | string | - | Filter by age group (e.g. `13-14`) |
| `gender` | string | - | Filter by gender: `Boys`, `Girls`, `Men`, `Women` |

**Response (200):**
```json
{
  "id": "clxyz...",
  "name": "47th Singapore National Age Group Championships",
  "date": "2024-03-15",
  "location": "OCBC Aquatic Centre",
  "events": [
    {
      "name": "Boys 13-14 200 LC Meter IM",
      "results": [
        {
          "id": "clxyz...",
          "placement": 1,
          "swimmer": {
            "id": "clxyz...",
            "name": "Tan Wei Ming",
            "age": 14,
            "team": "SSC"
          },
          "seedTime": "2:25.30",
          "time": "2:22.15",
          "isDQ": false,
          "dqCode": null
        }
      ]
    }
  ]
}
```

---

#### Swimmers

##### `GET /api/swimmers`

List and search swimmers.

**Query Parameters:**
| Parameter | Type | Default | Description |
|---|---|---|---|
| `page` | integer | 1 | Page number |
| `limit` | integer | 20 | Results per page (max 100) |
| `search` | string | - | Search by swimmer name |
| `team` | string | - | Filter by team/club code |
| `ageMin` | integer | - | Minimum age |
| `ageMax` | integer | - | Maximum age |
| `sort` | string | `name` | Sort field: `name`, `team`, `age` |
| `order` | string | `asc` | Sort order: `asc`, `desc` |

**Response (200):**
```json
{
  "data": [
    {
      "id": "clxyz...",
      "name": "Tan Wei Ming",
      "age": 14,
      "team": "SSC",
      "meetCount": 8,
      "resultCount": 32,
      "latestMeet": "2024-03-15"
    }
  ],
  "pagination": {
    "page": 1,
    "limit": 20,
    "total": 342,
    "totalPages": 18
  }
}
```

---

##### `GET /api/swimmers/:id`

Get swimmer profile with personal bests across all events.

**Path Parameters:**
| Parameter | Type | Description |
|---|---|---|
| `id` | string | Swimmer ID |

**Response (200):**
```json
{
  "id": "clxyz...",
  "name": "Tan Wei Ming",
  "age": 14,
  "team": "SSC",
  "personalBests": [
    {
      "event": "Boys 13-14 200 LC Meter IM",
      "time": "2:22.15",
      "meet": "47th Singapore National Age Group Championships",
      "date": "2024-03-15"
    },
    {
      "event": "Boys 13-14 100 LC Meter Freestyle",
      "time": "58.42",
      "meet": "SSA National Junior Championships",
      "date": "2024-06-10"
    }
  ],
  "recentResults": [
    {
      "id": "clxyz...",
      "event": "Boys 13-14 200 LC Meter IM",
      "time": "2:22.15",
      "placement": 1,
      "meet": "47th Singapore National Age Group Championships",
      "date": "2024-03-15"
    }
  ],
  "stats": {
    "totalMeets": 8,
    "totalResults": 32,
    "totalDQs": 1,
    "firstMeet": "2023-06-15",
    "latestMeet": "2024-03-15"
  }
}
```

---

#### Results

##### `GET /api/results`

Query results across all meets with flexible filtering.

**Query Parameters:**
| Parameter | Type | Default | Description |
|---|---|---|---|
| `page` | integer | 1 | Page number |
| `limit` | integer | 50 | Results per page (max 200) |
| `swimmer` | string | - | Filter by swimmer name (partial match) |
| `swimmerId` | string | - | Filter by swimmer ID |
| `meetId` | string | - | Filter by meet ID |
| `event` | string | - | Filter by event name (partial match) |
| `team` | string | - | Filter by team/club code |
| `isDQ` | boolean | - | Filter DQ results only |
| `placementMin` | integer | - | Minimum placement (e.g. 1) |
| `placementMax` | integer | - | Maximum placement (e.g. 3 for podium) |
| `from` | date | - | Results from meets on or after this date |
| `to` | date | - | Results from meets on or before this date |
| `sort` | string | `time` | Sort field: `time`, `date`, `placement`, `event` |
| `order` | string | `asc` | Sort order: `asc`, `desc` |

**Response (200):**
```json
{
  "data": [
    {
      "id": "clxyz...",
      "event": "Boys 13-14 200 LC Meter IM",
      "time": "2:22.15",
      "placement": 1,
      "isDQ": false,
      "dqCode": null,
      "swimmer": {
        "id": "clxyz...",
        "name": "Tan Wei Ming",
        "age": 14,
        "team": "SSC"
      },
      "meet": {
        "id": "clxyz...",
        "name": "47th Singapore National Age Group Championships",
        "date": "2024-03-15"
      }
    }
  ],
  "pagination": {
    "page": 1,
    "limit": 50,
    "total": 1250,
    "totalPages": 25
  }
}
```

---

#### Analytics

##### `GET /api/analytics/progression`

Get a swimmer's time progression for a specific event across meets.

**Query Parameters:**
| Parameter | Type | Required | Description |
|---|---|---|---|
| `swimmerId` | string | Yes | Swimmer ID |
| `event` | string | Yes | Event name (exact match) |
| `from` | date | No | Start date |
| `to` | date | No | End date |

**Response (200):**
```json
{
  "swimmer": {
    "id": "clxyz...",
    "name": "Tan Wei Ming"
  },
  "event": "Boys 13-14 200 LC Meter IM",
  "dataPoints": [
    {
      "date": "2023-06-15",
      "time": "2:35.80",
      "timeInSeconds": 155.80,
      "meet": "SSA Invitational 2023",
      "placement": 5
    },
    {
      "date": "2023-12-01",
      "time": "2:28.44",
      "timeInSeconds": 148.44,
      "meet": "Year-End Championships 2023",
      "placement": 3
    },
    {
      "date": "2024-03-15",
      "time": "2:22.15",
      "timeInSeconds": 142.15,
      "meet": "47th National Age Group Championships",
      "placement": 1
    }
  ],
  "summary": {
    "personalBest": "2:22.15",
    "personalBestDate": "2024-03-15",
    "totalImprovement": "13.65s",
    "improvementPercent": 8.76,
    "meetCount": 3
  }
}
```

---

## 4. Database Schema

Defined in `prisma/schema.prisma`. Uses PostgreSQL via Prisma ORM.

### Entity Relationship Diagram

```
┌──────────────────┐       ┌──────────────────┐
│     Swimmer      │       │       Meet       │
├──────────────────┤       ├──────────────────┤
│ id         String│       │ id         String│
│ name       String│◄──┐   │ name       String│
│ age        Int?  │   │   │ date     DateTime│
│ team       String│   │   │ location  String?│
│ createdAt  Date  │   │   │ createdAt   Date │
│ updatedAt  Date  │   │   │ updatedAt   Date │
└──────────────────┘   │   └──────────────────┘
                       │            ▲
                       │            │
                  ┌────┴────────────┴──┐
                  │       Result       │
                  ├────────────────────┤
                  │ id         String  │
                  │ swimmerId  String  │──► FK → Swimmer
                  │ meetId     String  │──► FK → Meet
                  │ event      String  │
                  │ time       String  │
                  │ placement  Int?    │
                  │ isDQ       Boolean │
                  │ dqCode     String? │
                  │ createdAt  Date    │
                  │ updatedAt  Date    │
                  └────────────────────┘
```

### Models

#### Swimmer

| Field | Type | Attributes | Description |
|---|---|---|---|
| `id` | String | `@id @default(cuid())` | Primary key |
| `name` | String | `@@index` | Full name |
| `age` | Int? | - | Age at last recorded meet |
| `team` | String | `@@index` | Club/team code (e.g. `SSC`, `ATS`) |
| `results` | Result[] | Relation | All results for this swimmer |
| `createdAt` | DateTime | `@default(now())` | Record created |
| `updatedAt` | DateTime | `@updatedAt` | Record last updated |

#### Meet

| Field | Type | Attributes | Description |
|---|---|---|---|
| `id` | String | `@id @default(cuid())` | Primary key |
| `name` | String | - | Meet name |
| `date` | DateTime | `@@index` | Meet date |
| `location` | String? | - | Venue name |
| `results` | Result[] | Relation | All results from this meet |
| `createdAt` | DateTime | `@default(now())` | Record created |
| `updatedAt` | DateTime | `@updatedAt` | Record last updated |

#### Result

| Field | Type | Attributes | Description |
|---|---|---|---|
| `id` | String | `@id @default(cuid())` | Primary key |
| `swimmerId` | String | FK → Swimmer | Swimmer reference |
| `meetId` | String | FK → Meet | Meet reference |
| `event` | String | `@@index` | Event name (e.g. `Boys 13-14 200 LC Meter IM`) |
| `time` | String | - | Finals time as string (e.g. `2:22.15`) |
| `placement` | Int? | - | Finishing position (null if DQ/DNS/DNF) |
| `isDQ` | Boolean | `@default(false)` | Whether the result is a DQ/DNS/DNF |
| `dqCode` | String? | - | DQ reason code if applicable |
| `createdAt` | DateTime | `@default(now())` | Record created |
| `updatedAt` | DateTime | `@updatedAt` | Record last updated |

### Schema Observations & Recommendations

The current schema is correct for MVP. Future considerations:

1. **Seed time** - The parser extracts seed times but the schema does not store them. Consider adding a `seedTime String?` field to `Result`.
2. **Course type** - Long Course (LC) vs Short Course (SC) is embedded in the event name string. A dedicated `course` enum (`LC`, `SC`) on `Result` or `Meet` would simplify filtering.
3. **Age group** - Currently derived from the event name. A structured `ageGroup` field would enable faster queries.
4. **Gender** - Same as age group; embedded in event name string. A dedicated field would help.
5. **Unique constraint** - Consider adding `@@unique([swimmerId, meetId, event])` on `Result` to prevent duplicate entries on re-upload.

---

## 5. PDF Parsing

### Supported Format

**HY-TEK Meet Manager** - The de facto standard for swim meet management in Singapore and internationally.

### Parser Implementation

**File:** `lib/parsers/hytek.ts`

The parser processes plain text extracted from HY-TEK PDFs and returns structured data:

```typescript
interface ParsedMeet {
  meetName: string;
  events: ParsedEvent[];
}

interface ParsedEvent {
  eventNumber: string;
  eventName: string;
  results: ParsedResult[];
}

interface ParsedResult {
  placement: number | null;
  name: string;
  age: number | null;
  team: string;
  seedTime: string | null;
  finalsTime: string;
  isDQ: boolean;
  dqCode: string | null;
}
```

### Parsing Strategy

1. Extract raw text from PDF using `pdf-parse`
2. Identify meet name from the first non-empty line
3. Detect event headers via regex: `Event\s+(\d+)\s+(.+)`
4. Parse individual result lines with regex matching for:
   - Placement number (or `---` for DQ)
   - Swimmer name
   - Age
   - Team code
   - Seed time
   - Finals time
5. Detect DQ/DNS/DNF status from time field or placement markers

### Test Coverage

**File:** `lib/parsers/__tests__/hytek.test.ts`

Tests cover:
- Standard result parsing (placement, name, age, team, times)
- DQ detection and code extraction
- DNS/DNF handling
- Multiple events in a single PDF
- Empty input handling
- Malformed data resilience

---

## 6. Frontend Pages

### Dashboard (`/`)

The landing page with platform overview and quick navigation.

- **Stats cards** - Total swimmers, meets, results, recent uploads (currently mock data)
- **Quick actions** - Upload results, browse results, view analytics
- **Recent activity** - Feed of latest uploads and actions

### Upload (`/upload`)

PDF upload interface.

- **File picker** - Accepts `.pdf` files only
- **Upload handler** - Posts to `POST /api/upload`, displays success/error feedback
- **Format guide** - Documents supported PDF formats

### Results (`/results`)

Browsable results table with filtering.

- **Search** - Filter by swimmer name
- **Dropdowns** - Filter by event, age group
- **Table** - Placement (with medal styling), swimmer, age, team, event, time, status
- **Pagination** - Page controls (UI present, backend pagination pending)

### Analytics (`/analytics`) - Planned

Swimmer progression charts and comparative analysis.

- **Progression curves** - Time vs date scatter/line chart per event using Recharts
- **Personal bests** - PB timeline across events
- **Comparative view** - Overlay multiple swimmers on the same chart

---

## 7. Current Status

### Completed

| Component | Status | Notes |
|---|---|---|
| Project scaffolding | Done | Next.js 14 + TypeScript + Tailwind |
| Prisma schema | Done | Swimmer, Meet, Result models |
| SSA brand tokens | Done | Navy, teal, gold, slate in Tailwind config |
| Global styles & components | Done | btn-primary, btn-secondary, card classes |
| Root layout with nav | Done | Sticky header, footer, Inter font |
| HY-TEK PDF parser | Done | Comprehensive with DQ/DNS/DNF handling |
| Parser unit tests | Done | Covers standard, edge, and error cases |
| Upload API route | Done | `POST /api/upload` with DB persistence |
| Upload page UI | Done | File picker, upload flow, feedback |
| Dashboard page UI | Done | Stats cards, quick actions (mock data) |
| Results page UI | Done | Table with filters and pagination UI (mock data) |
| Prisma client singleton | Done | Connection pooling safe |

### Not Yet Started

| Component | Status | Notes |
|---|---|---|
| PostgreSQL database setup | Pending | Need `.env` with `DATABASE_URL` |
| Prisma migration run | Pending | `npx prisma db push` |
| Results page - live data | Pending | Replace mock data with API calls |
| Dashboard - live stats | Pending | Replace mock data with DB queries |
| `GET /api/meets` endpoint | Pending | List meets with pagination |
| `GET /api/meets/:id` endpoint | Pending | Meet detail with results |
| `GET /api/swimmers` endpoint | Pending | Search/list swimmers |
| `GET /api/swimmers/:id` endpoint | Pending | Swimmer profile with PBs |
| `GET /api/results` endpoint | Pending | Filtered results query |
| `GET /api/analytics/progression` | Pending | Time progression data |
| Analytics page UI | Pending | Recharts integration |
| Swimmer profile page | Pending | Individual swimmer view |
| Mobile responsive nav | Pending | Hamburger menu functional |
| Error handling & validation | Pending | Input sanitisation, error boundaries |
| Docker deployment | Pending | Containerised setup |

---

## 8. Next Steps

### Phase 1: Database & Data Flow (Immediate Priority)

1. **Set up PostgreSQL** - Provision database, configure `DATABASE_URL` in `.env`
2. **Run Prisma migrations** - `npm run db:push` to create tables
3. **Test upload flow end-to-end** - Upload a real HY-TEK PDF and verify DB persistence
4. **Wire results page to DB** - Replace mock data with `GET /api/results` endpoint
5. **Wire dashboard stats** - Query actual counts from the database

### Phase 2: Read API Endpoints

6. **Implement `GET /api/meets`** - Paginated meet listing
7. **Implement `GET /api/meets/:id`** - Meet detail with grouped event results
8. **Implement `GET /api/swimmers`** - Swimmer search and listing
9. **Implement `GET /api/swimmers/:id`** - Swimmer profile with computed personal bests
10. **Implement `GET /api/results`** - Flexible result querying with filters

### Phase 3: Analytics & Visualisation

11. **Implement `GET /api/analytics/progression`** - Time series data for progression charts
12. **Build analytics page** - Recharts line/scatter charts for time progression
13. **Build swimmer profile page** - PB table, recent results, progression preview

### Phase 4: Polish & Deployment

14. **Mobile responsive navigation** - Functional hamburger menu
15. **Error boundaries & loading states** - Skeleton loaders, error recovery
16. **Input validation** - File size limits, format verification on upload
17. **Add `seedTime` to schema** - Persist seed times from parsed results
18. **Dockerise** - `Dockerfile` + `docker-compose.yml` with PostgreSQL
19. **CI/CD pipeline** - Automated tests and deployment

---

## Appendix: Development Setup

```bash
# Install dependencies
npm install

# Configure database
cp .env.example .env  # Set DATABASE_URL

# Set up database
npm run db:generate   # Generate Prisma client
npm run db:push       # Push schema to database

# Start development server
npm run dev           # http://localhost:3000

# Open database GUI
npm run db:studio     # Prisma Studio
```

### Environment Variables

| Variable | Required | Description |
|---|---|---|
| `DATABASE_URL` | Yes | PostgreSQL connection string |

**Format:** `postgresql://USER:PASSWORD@HOST:PORT/DATABASE?schema=public`
