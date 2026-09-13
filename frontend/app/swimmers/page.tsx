"use client";

import { Suspense, useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  displayName,
  listBrowserSwimmers,
  type BrowserSwimmerListItem,
  type PaginationInfo,
} from "@/lib/api";

const PAGE_SIZE = 50;
type SwimmerSort = "name" | "team" | "result_count" | "latest_meet";
type SortOrder = "asc" | "desc";

export default function SwimmersPage() {
  return (
    <Suspense fallback={<div className="mx-auto min-h-screen max-w-7xl px-4 py-12 text-sm text-gray-500">Loading swimmers...</div>}>
      <SwimmersContent />
    </Suspense>
  );
}

function SwimmersContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const q = searchParams.get("q") || "";
  const team = searchParams.get("team") || "";
  const showWarningsOnly = searchParams.get("has_warnings") === "true";
  const requestedPage = Number(searchParams.get("page") || "1");
  const page = Number.isFinite(requestedPage) && requestedPage > 0 ? Math.floor(requestedPage) : 1;
  const requestedSort = searchParams.get("sort");
  const sort: SwimmerSort =
    requestedSort === "team" || requestedSort === "result_count" || requestedSort === "latest_meet"
      ? requestedSort
      : "name";
  const order: SortOrder = searchParams.get("order") === "desc" ? "desc" : "asc";

  const [swimmers, setSwimmers] = useState<BrowserSwimmerListItem[]>([]);
  const [pagination, setPagination] = useState<PaginationInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [searchValue, setSearchValue] = useState(q);
  const [teamValue, setTeamValue] = useState(team);
  const searchDebounceRef = useRef<ReturnType<typeof setTimeout>>();
  const teamDebounceRef = useRef<ReturnType<typeof setTimeout>>();
  const latestRequestIdRef = useRef(0);
  const observedQuery = searchParams.toString();
  const urlStateOwnerRef = useRef({
    params: new URLSearchParams(observedQuery),
    pendingQuery: null as string | null,
  });

  useEffect(() => setSearchValue(q), [q]);
  useEffect(() => setTeamValue(team), [team]);

  useEffect(() => {
    const owner = urlStateOwnerRef.current;
    if (owner.pendingQuery === null || owner.pendingQuery === observedQuery) {
      owner.params = new URLSearchParams(observedQuery);
      owner.pendingQuery = null;
    }
  }, [observedQuery]);

  useEffect(() => {
    function syncHistoryState() {
      if (searchDebounceRef.current) {
        clearTimeout(searchDebounceRef.current);
        searchDebounceRef.current = undefined;
      }
      if (teamDebounceRef.current) {
        clearTimeout(teamDebounceRef.current);
        teamDebounceRef.current = undefined;
      }
      const params = new URLSearchParams(window.location.search);
      urlStateOwnerRef.current.params = params;
      urlStateOwnerRef.current.pendingQuery = null;
      setSearchValue(params.get("q") || "");
      setTeamValue(params.get("team") || "");
    }
    window.addEventListener("popstate", syncHistoryState);
    return () => window.removeEventListener("popstate", syncHistoryState);
  }, []);

  useEffect(() => {
    const requestId = latestRequestIdRef.current + 1;
    latestRequestIdRef.current = requestId;

    async function fetchSwimmers() {
      setLoading(true);
      setError("");
      try {
        const response = await listBrowserSwimmers({
          page,
          limit: PAGE_SIZE,
          q: q || undefined,
          team: team || undefined,
          has_warnings: showWarningsOnly ? true : undefined,
          sort,
          order,
        });
        if (requestId !== latestRequestIdRef.current) return;
        setSwimmers(response.data);
        setPagination(response.pagination);
      } catch (cause) {
        if (requestId !== latestRequestIdRef.current) return;
        setSwimmers([]);
        setPagination(null);
        setError(cause instanceof Error ? cause.message : "Failed to load swimmers");
      } finally {
        if (requestId === latestRequestIdRef.current) setLoading(false);
      }
    }

    fetchSwimmers();
  }, [page, q, team, showWarningsOnly, sort, order]);

  useEffect(() => () => {
    if (searchDebounceRef.current) clearTimeout(searchDebounceRef.current);
    if (teamDebounceRef.current) clearTimeout(teamDebounceRef.current);
  }, []);

  function update(changes: Record<string, string | number | boolean | null>) {
    const next = new URLSearchParams(urlStateOwnerRef.current.params.toString());
    for (const [key, value] of Object.entries(changes)) {
      if (value === null || value === "") next.delete(key);
      else next.set(key, String(value));
    }
    const query = next.toString();
    const href = `/swimmers${query ? `?${query}` : ""}`;
    const current = `${window.location.pathname}${window.location.search}`;
    urlStateOwnerRef.current.params = next;
    urlStateOwnerRef.current.pendingQuery = href === current ? null : query;
    if (href !== current) router.push(href);
  }

  function updateTextFilter(
    key: "q" | "team",
    value: string,
    debounceRef: React.MutableRefObject<ReturnType<typeof setTimeout> | undefined>,
  ) {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => update({ [key]: value.trim() || null, page: 1 }), 300);
  }

  const totalResults = pagination?.total ?? 0;
  const totalPages = pagination?.total_pages ?? 0;
  const showingFrom = totalResults === 0 ? 0 : (page - 1) * PAGE_SIZE + 1;
  const showingTo = Math.min(page * PAGE_SIZE, totalResults);

  return (
    <div className="min-h-screen min-w-0">
      <div className="border-b border-gray-200 bg-white">
        <div className="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
          <nav className="mb-4 flex items-center gap-2 text-sm">
            <a href="/" className="text-gray-500 transition-colors hover:text-ssa-navy">Dashboard</a>
            <span className="text-gray-300">/</span>
            <span className="font-medium text-ssa-navy">Swimmers</span>
          </nav>
          <h1 className="text-2xl font-bold text-ssa-navy">Find a swimmer</h1>
          <p className="mt-1 text-sm text-gray-500">
            Search official-source swimmer histories across meets, individual swims, and relays.
          </p>
        </div>
      </div>

      <main className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
        <div className="card mb-6 p-4">
          <div className="grid grid-cols-1 gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(0,260px)_180px_160px_auto]">
            <input
              type="search"
              aria-label="Search swimmers by name"
              placeholder="Search by swimmer name..."
              value={searchValue}
              onChange={(event) => {
                setSearchValue(event.target.value);
                updateTextFilter("q", event.target.value, searchDebounceRef);
              }}
              className="min-h-11 w-full min-w-0 rounded-lg border border-gray-200 bg-gray-50 px-4 text-base focus:border-ssa-teal focus:outline-none focus:ring-2 focus:ring-ssa-teal/20 sm:text-sm"
            />
            <input
              type="text"
              aria-label="Filter swimmers by team or club"
              placeholder="Filter by team / club..."
              value={teamValue}
              onChange={(event) => {
                setTeamValue(event.target.value);
                updateTextFilter("team", event.target.value, teamDebounceRef);
              }}
              className="min-h-11 w-full min-w-0 rounded-lg border border-gray-200 bg-gray-50 px-4 text-base focus:border-ssa-teal focus:outline-none focus:ring-2 focus:ring-ssa-teal/20 sm:text-sm"
            />
            <select
              aria-label="Sort swimmers"
              value={sort}
              onChange={(event) => update({ sort: event.target.value, page: 1 })}
              className="min-h-11 min-w-0 rounded-lg border border-gray-200 bg-gray-50 px-3 text-sm text-ssa-slate focus:border-ssa-teal focus:outline-none focus:ring-2 focus:ring-ssa-teal/20"
            >
              <option value="name">Sort by name</option>
              <option value="team">Sort by team</option>
              <option value="result_count">Sort by individual swims</option>
              <option value="latest_meet">Sort by latest meet</option>
            </select>
            <select
              aria-label="Sort direction"
              value={order}
              onChange={(event) => update({ order: event.target.value, page: 1 })}
              className="min-h-11 min-w-0 rounded-lg border border-gray-200 bg-gray-50 px-3 text-sm text-ssa-slate focus:border-ssa-teal focus:outline-none focus:ring-2 focus:ring-ssa-teal/20"
            >
              <option value="asc">Ascending</option>
              <option value="desc">Descending</option>
            </select>
            <button
              type="button"
              aria-label="Toggle swimmers with data-quality warnings only"
              aria-pressed={showWarningsOnly}
              onClick={() => update({ has_warnings: showWarningsOnly ? null : true, page: 1 })}
              className={`min-h-11 rounded-lg border px-4 text-sm font-medium transition-colors ${
                showWarningsOnly
                  ? "border-amber-200 bg-amber-50 text-amber-800"
                  : "border-gray-200 bg-gray-50 text-ssa-slate hover:bg-gray-100"
              }`}
            >
              {showWarningsOnly ? "Warnings only" : "Show warnings"}
            </button>
          </div>
        </div>

        <div className="mb-4 flex items-center justify-between">
          <p className="text-sm text-gray-600">
            {loading ? "Loading..." : totalResults > 0 ? (
              <>Showing <span className="font-semibold text-ssa-navy">{showingFrom}&ndash;{showingTo}</span> of <span className="font-semibold text-ssa-navy">{totalResults.toLocaleString()}</span> swimmers</>
            ) : "No swimmers found"}
          </p>
        </div>

        {error && <div role="alert" className="card mb-6 p-8 text-center font-medium text-red-600">{error}</div>}

        {!error && (
          <div className="grid min-w-0 max-w-full gap-3">
            {loading ? Array.from({ length: 8 }).map((_, index) => (
              <div key={index} className="card animate-pulse p-4">
                <div className="mb-3 h-5 w-64 max-w-full rounded bg-gray-200" />
                <div className="h-4 w-96 max-w-full rounded bg-gray-100" />
              </div>
            )) : swimmers.map((swimmer) => (
              <a key={swimmer.id} href={`/swimmers/${swimmer.id}`} className="card block min-w-0 max-w-full p-4 transition-all hover:border-ssa-teal/40 hover:shadow-md">
                <div className="flex min-w-0 max-w-full flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
                  <div className="min-w-0 max-w-full overflow-hidden">
                    <div className="flex min-w-0 max-w-full flex-wrap items-center gap-2">
                      <h2 className="min-w-0 max-w-full break-words whitespace-normal font-semibold text-ssa-navy">{displayName(swimmer.name)}</h2>
                      {swimmer.warning_count > 0 && (
                        <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-semibold text-amber-800">
                          {swimmer.warning_count} data warning{swimmer.warning_count === 1 ? "" : "s"}
                        </span>
                      )}
                    </div>
                    <p className="mt-1 min-w-0 max-w-full truncate text-sm text-gray-500">
                      {swimmer.team || "No team"}{swimmer.age ? ` · Age ${swimmer.age}` : ""}
                    </p>
                  </div>
                  <div className="grid min-w-0 max-w-full grid-cols-2 gap-2 text-center sm:grid-cols-5 lg:min-w-[520px]">
                    <Metric label="Swims" value={swimmer.individual_result_count} />
                    <Metric label="Relays" value={swimmer.relay_result_count} />
                    <Metric label="Meets" value={swimmer.meet_count} />
                    <Metric label="Events" value={swimmer.event_count} />
                    <div className="col-span-2 rounded-lg bg-gray-50 px-3 py-2 text-left sm:col-span-1 sm:text-center">
                      <div className="text-[10px] uppercase tracking-wider text-gray-400">Latest</div>
                      <div className="truncate text-xs font-medium text-gray-700">{swimmer.latest_meet?.date || "-"}</div>
                    </div>
                  </div>
                </div>
              </a>
            ))}
          </div>
        )}

        {!error && totalPages > 1 && (
          <nav aria-label="Swimmer catalogue pages" className="mt-6 flex items-center justify-between gap-4 text-sm">
            <button
              type="button"
              onClick={() => update({ page: Math.max(1, page - 1) })}
              disabled={page <= 1}
              className="min-h-11 rounded-md border border-gray-200 bg-white px-4 disabled:cursor-not-allowed disabled:text-gray-400 hover:bg-gray-50"
            >
              Previous
            </button>
            <span className="text-center text-gray-500">Page {page} of {totalPages}</span>
            <button
              type="button"
              onClick={() => update({ page: Math.min(totalPages, page + 1) })}
              disabled={page >= totalPages}
              className="min-h-11 rounded-md border border-gray-200 bg-white px-4 disabled:cursor-not-allowed disabled:text-gray-400 hover:bg-gray-50"
            >
              Next
            </button>
          </nav>
        )}
      </main>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-lg bg-ssa-navy/5 px-3 py-2">
      <div className="text-base font-bold text-ssa-navy">{value.toLocaleString()}</div>
      <div className="text-[10px] uppercase tracking-wider text-gray-500">{label}</div>
    </div>
  );
}
