"use client";

import Link from "next/link";
import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { listBrowserMeets, type BrowserMeetListItem, type PaginationInfo } from "@/lib/api";

const PAGE_SIZE = 24;

type MeetSort = "date" | "name";
type SortOrder = "asc" | "desc";

export default function MeetsPage() {
  return (
    <Suspense fallback={<div className="mx-auto min-h-screen max-w-7xl px-4 py-12 text-sm text-gray-500">Loading meets...</div>}>
      <MeetsContent />
    </Suspense>
  );
}

function MeetsContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const q = searchParams.get("q") || "";
  const sort: MeetSort = searchParams.get("sort") === "name" ? "name" : "date";
  const order: SortOrder = searchParams.get("order") === "asc" ? "asc" : "desc";
  const requestedPage = Number(searchParams.get("page") || "1");
  const page = Number.isFinite(requestedPage) && requestedPage > 0 ? Math.floor(requestedPage) : 1;

  const [searchValue, setSearchValue] = useState(q);
  const [meets, setMeets] = useState<BrowserMeetListItem[]>([]);
  const [pagination, setPagination] = useState<PaginationInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);

  useEffect(() => setSearchValue(q), [q]);

  useEffect(() => {
    let active = true;

    async function fetchMeets() {
      setLoading(true);
      setError("");
      if (retry > 0) setPagination(null);
      try {
        const response = await listBrowserMeets({ page, limit: PAGE_SIZE, q: q || undefined, sort, order });
        if (!active) return;
        setMeets(response.data);
        setPagination(response.pagination);
      } catch (cause) {
        if (!active) return;
        setMeets([]);
        setPagination(null);
        setError(cause instanceof Error ? cause.message : "Could not load meets");
      } finally {
        if (active) setLoading(false);
      }
    }

    fetchMeets();
    return () => { active = false; };
  }, [page, q, sort, order, retry]);

  function hrefFor(changes: Record<string, string | number | null>) {
    const next = new URLSearchParams(searchParams.toString());
    for (const [key, value] of Object.entries(changes)) {
      if (value === null || value === "") next.delete(key);
      else next.set(key, String(value));
    }
    const query = next.toString();
    return `/meets${query ? `?${query}` : ""}`;
  }

  function update(changes: Record<string, string | number | null>) {
    router.push(hrefFor(changes));
  }

  const totalPages = pagination?.total_pages ?? 0;
  const total = pagination?.total ?? 0;

  return (
    <div className="min-h-screen min-w-0">
      <header className="border-b border-gray-200 bg-white">
        <div className="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
          <nav aria-label="Breadcrumb" className="mb-4 flex items-center gap-2 text-sm">
            <Link href="/" className="text-gray-500 hover:text-ssa-navy">Home</Link>
            <span className="text-gray-300" aria-hidden="true">/</span>
            <span className="font-medium text-ssa-navy" aria-current="page">Meets</span>
          </nav>
          <h1 className="text-2xl font-bold tracking-tight text-ssa-navy">Meets</h1>
          <p className="mt-1 max-w-2xl text-sm text-gray-600">Browse competition programmes and open event-by-event results.</p>
        </div>
      </header>

      <main className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
        <form
          role="search"
          className="grid gap-3 rounded-xl bg-white p-4 shadow-sm ring-1 ring-gray-200 sm:grid-cols-[minmax(0,1fr)_180px_160px_auto]"
          onSubmit={(event) => {
            event.preventDefault();
            update({ q: searchValue.trim() || null, page: 1 });
          }}
        >
          <label className="min-w-0">
            <span className="sr-only">Search meets</span>
            <input
              type="search"
              aria-label="Search meets"
              value={searchValue}
              onChange={(event) => setSearchValue(event.target.value)}
              placeholder="Search meet names..."
              className="min-h-11 w-full min-w-0 rounded-lg border border-gray-300 bg-gray-50 px-4 text-base text-gray-900 placeholder:text-gray-500 focus:border-ssa-teal focus:outline-none focus:ring-2 focus:ring-ssa-teal/20 sm:text-sm"
            />
          </label>
          <select aria-label="Sort meets" value={sort} onChange={(event) => update({ sort: event.target.value, page: 1 })} className="min-h-11 min-w-0 rounded-lg border border-gray-300 bg-gray-50 px-3 text-sm text-gray-700 focus:border-ssa-teal focus:outline-none focus:ring-2 focus:ring-ssa-teal/20">
            <option value="date">Sort by date</option>
            <option value="name">Sort by name</option>
          </select>
          <select aria-label="Sort direction" value={order} onChange={(event) => update({ order: event.target.value, page: 1 })} className="min-h-11 min-w-0 rounded-lg border border-gray-300 bg-gray-50 px-3 text-sm text-gray-700 focus:border-ssa-teal focus:outline-none focus:ring-2 focus:ring-ssa-teal/20">
            <option value="desc">Descending</option>
            <option value="asc">Ascending</option>
          </select>
          <button type="submit" className="btn-primary min-h-11 justify-center">Search</button>
        </form>

        <div className="mt-6 flex min-h-6 items-center justify-between gap-3">
          <p className="text-sm text-gray-600">{loading ? "Loading meets..." : `${total.toLocaleString()} meet${total === 1 ? "" : "s"}`}</p>
          {q && <Link href={hrefFor({ q: null, page: 1 })} className="text-sm font-semibold text-ssa-teal hover:text-ssa-teal-dark">Clear search</Link>}
        </div>

        {error ? (
          <section role="alert" className="mt-4 rounded-xl bg-white p-8 text-center shadow-sm ring-1 ring-red-200">
            <h2 className="font-semibold text-red-800">Could not load meets</h2>
            <p className="mt-1 text-sm text-red-700">{error}</p>
            <button type="button" onClick={() => setRetry((value) => value + 1)} className="btn-secondary mt-5 min-h-11">Try again</button>
          </section>
        ) : loading ? (
          <div className="mt-4 grid gap-3 sm:grid-cols-2" aria-label="Loading meet catalogue">
            {Array.from({ length: 6 }).map((_, index) => <div key={index} className="h-40 animate-pulse rounded-xl bg-white shadow-sm ring-1 ring-gray-200"><div className="m-5 h-5 w-2/3 rounded bg-gray-200" /></div>)}
          </div>
        ) : meets.length === 0 ? (
          <section className="mt-4 rounded-xl bg-white p-10 text-center shadow-sm ring-1 ring-gray-200">
            <h2 className="font-semibold text-ssa-navy">No meets match these filters</h2>
            <p className="mt-1 text-sm text-gray-600">Try a shorter search or clear the current filters.</p>
          </section>
        ) : (
          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            {meets.map((item) => <MeetCard key={item.id} meet={item} />)}
          </div>
        )}

        {!error && !loading && totalPages > 1 && (
          <nav aria-label="Meet catalogue pages" className="mt-7 flex items-center justify-between gap-3 text-sm">
            <Link aria-disabled={page <= 1} tabIndex={page <= 1 ? -1 : undefined} href={hrefFor({ page: Math.max(1, page - 1) })} className={`flex min-h-11 items-center rounded-lg border px-4 font-medium ${page <= 1 ? "pointer-events-none border-gray-200 text-gray-400" : "border-gray-300 bg-white text-gray-700 hover:bg-gray-50"}`}>Previous</Link>
            <span className="text-gray-600">Page {page} of {totalPages}</span>
            <Link aria-disabled={page >= totalPages} tabIndex={page >= totalPages ? -1 : undefined} href={hrefFor({ page: Math.min(totalPages, page + 1) })} className={`flex min-h-11 items-center rounded-lg border px-4 font-medium ${page >= totalPages ? "pointer-events-none border-gray-200 text-gray-400" : "border-gray-300 bg-white text-gray-700 hover:bg-gray-50"}`}>Next</Link>
          </nav>
        )}
      </main>
    </div>
  );
}

function MeetCard({ meet }: { meet: BrowserMeetListItem }) {
  const totalRows = meet.total_rows ?? meet.individual_result_count + meet.relay_result_count;
  return (
    <Link href={`/meets/${meet.id}`} className="group min-w-0 rounded-xl bg-white p-5 shadow-sm ring-1 ring-gray-200 transition hover:-translate-y-0.5 hover:shadow-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ssa-teal">
      <span className="flex min-w-0 items-start justify-between gap-4">
        <span className="min-w-0">
          <span className="block break-words text-base font-semibold text-ssa-navy group-hover:text-ssa-teal">{meet.name}</span>
          <span className="mt-1 block text-sm text-gray-600">{dateRange(meet.date, meet.end_date)}</span>
          <span className="mt-1 block break-words text-sm text-gray-500">{meet.location || "Location not listed"}</span>
        </span>
        <span className="shrink-0 rounded-lg bg-ssa-teal/10 px-2.5 py-1 text-xs font-semibold text-ssa-teal">{meet.event_group_count.toLocaleString()} events</span>
      </span>
      <span className="mt-5 grid grid-cols-3 gap-2 border-t border-gray-100 pt-4 text-center">
        <CardMetric label="Results" value={totalRows} />
        <CardMetric label="Individual" value={meet.individual_result_count} />
        <CardMetric label="Relays" value={meet.relay_result_count} />
      </span>
    </Link>
  );
}

function CardMetric({ label, value }: { label: string; value: number }) {
  return <span className="min-w-0"><span className="block text-base font-bold text-ssa-navy">{value.toLocaleString()}</span><span className="block truncate text-[11px] text-gray-500">{label}</span></span>;
}

function dateRange(start: string | null, end: string | null) {
  if (!start) return "Date unknown";
  const format = (value: string) => {
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString("en-SG", { day: "numeric", month: "short", year: "numeric" });
  };
  return end && end !== start ? `${format(start)} – ${format(end)}` : format(start);
}
