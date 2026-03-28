# 🏊 Swim Analytics

Singapore Swimming Association - Meet Results Platform

## MVP Scope (Week 1)

- ✅ Upload PDF meet results (HY-TEK Meet Manager format)
- ✅ Parse swimmer data: name, age, team, event, time, placement, DQ
- ✅ View results in basic table format
- 🔄 Personal bests tracking (coming soon)
- 🔄 Progression curves (coming soon)

## Tech Stack

- **Framework:** Next.js 14 (App Router, TypeScript)
- **Database:** PostgreSQL with Prisma ORM
- **PDF Parsing:** pdf-parse (Node.js)
- **Charts:** Recharts (coming in Week 2)
- **Deployment:** Docker (coming in Week 3)

## Quick Start

### 1. Install Dependencies

```bash
npm install
```

### 2. Set Up Database

Create a `.env` file:

```bash
DATABASE_URL="postgresql://user:password@localhost:5432/swim_analytics"
```

Generate Prisma client and push schema:

```bash
npm run db:generate
npm run db:push
```

### 3. Run Development Server

```bash
npm run dev
```

Open [http://localhost:3000](http://localhost:3000)

## Project Structure

```
swim-analytics/
├── app/
│   ├── page.tsx              # Home page
│   ├── upload/
│   │   └── page.tsx          # Upload PDF page
│   ├── results/
│   │   └── page.tsx          # Results browser
│   └── api/
│       └── upload/
│           └── route.ts      # PDF upload API
├── prisma/
│   └── schema.prisma         # Database schema
├── package.json
└── README.md
```

## Database Schema

- **Swimmers:** name, age, team
- **Meets:** name, date, location
- **Results:** swimmer, meet, event, time, placement, DQ info

## Next Steps (Week 2-3)

1. Implement PDF parser for HY-TEK format
2. Add swimmer profile pages with personal bests
3. Build progression curve visualizations
4. Add split time analysis
5. Docker deployment

## License

Internal use - Singapore Swimming Association
