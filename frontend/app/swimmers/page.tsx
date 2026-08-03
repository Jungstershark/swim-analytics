"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  displayName,
  listBrowserSwimmers,
  type BrowserSwimmerListItem,
  type PaginationInfo,
} from "@/lib/api";

export default function SwimmersPage() {
  const [swimmers, setSwimmers] = useState<BrowserSwimmerListItem[]>([]);
  const [pagination, setPagination] = useState<PaginationInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [teamFilter, setTeamFilter] = useState("");
  const [showWarningsOnly, setShowWarningsOnly] = useState(false);
  const [page, setPage] = useState(1);
  const limit = 50;
  const debounceRef = useRef<NodeJS.Timeout>();

  const fetchSwimmers = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const res = await listBrowserSwimmers({
        page,
        limit,
        q: search || undefined,
        team: teamFilter || undefined,
        has_warnings: showWarningsOnly ? true : undefined,
        sort: "name",
        order: "asc",
      });
      setSwimmers(res.data);
      setPagination(res.pagination);
    } catch (e: any) {
      setError(e.message || "Failed to load swimmers");
    } finally {
      setLoading(false);
    }
  }, [page, search, teamFilter, showWarningsOnly]);

  useEffect(() => {
    fetchSwimmers();
  }, [fetchSwimmers]);

  function handleSearchChange(value: string) {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      setSearch(value);
      setPage(1);
    }, 300);
  }

  const totalResults = pagination?.total ?? 0;
  const totalPages = pagination?.total_pages ?? 0;
  const showingFrom = totalResults === 0 ? 0 : (page - 1) * limit + 1;
  const showingTo = Math.min(page * limit, totalResults);

  return (
    <div className="min-h-screen">
      <div className="bg-white border-b border-gray-200">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
          <nav className="flex items-center gap-2 text-sm mb-4">
            <a href="/" className="text-gray-500 hover:text-ssa-navy transition-colors">Dashboard</a>
            <span className="text-gray-300">/</span>
            <span className="text-ssa-navy font-medium">Swimmers</span>
          </nav>
          <h1 className="text-2xl font-bold text-ssa-navy">Find a swimmer</h1>
          <p className="text-gray-500 text-sm mt-1">
            Search official-source swimmer histories across meets, individual swims, and relays.
          </p>
        </div>
      </div>

      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <div className="card p-4 mb-6">
          <div className="grid grid-cols-1 md:grid-cols-[1fr_260px_auto] gap-3">
            <input
              type="text"
              aria-label="Search swimmers by name"
              placeholder="Search by swimmer name..."
              defaultValue={search}
              onChange={(e) => handleSearchChange(e.target.value)}
              className="w-full px-4 py-2.5 bg-gray-50 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-ssa-teal/20 focus:border-ssa-teal"
            />
            <input
              type="text"
              aria-label="Filter swimmers by team or club"
              placeholder="Filter by team / club..."
              value={teamFilter}
              onChange={(e) => { setTeamFilter(e.target.value); setPage(1); }}
              className="w-full px-4 py-2.5 bg-gray-50 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-ssa-teal/20 focus:border-ssa-teal"
            />
            <button
              type="button"
              aria-label="Toggle swimmers with data-quality warnings only"
              aria-pressed={showWarningsOnly}
              onClick={() => { setShowWarningsOnly((v) => !v); setPage(1); }}
              className={`px-4 py-2.5 rounded-lg text-sm font-medium border transition-colors ${
                showWarningsOnly ? "bg-amber-50 border-amber-200 text-amber-800" : "bg-gray-50 border-gray-200 text-gray-600 hover:bg-gray-100"
              }`}
            >
              {showWarningsOnly ? "Warnings only" : "Show warnings"}
            </button>
          </div>
        </div>

        <div className="flex items-center justify-between mb-4">
          <p className="text-sm text-gray-600">
            {loading ? "Loading..." : totalResults > 0 ? (
              <>Showing <span className="font-semibold text-ssa-navy">{showingFrom}&ndash;{showingTo}</span> of <span className="font-semibold text-ssa-navy">{totalResults.toLocaleString()}</span> swimmers</>
            ) : "No swimmers found"}
          </p>
          <p className="hidden sm:block text-xs text-gray-400">Counts come from browser read models, not per-row UI reconstruction.</p>
        </div>

        {error && <div className="card p-8 text-center mb-6 text-red-600 font-medium">{error}</div>}

        {!error && (
          <div className="grid gap-3">
            {loading ? Array.from({ length: 8 }).map((_, i) => (
              <div key={i} className="card p-4 animate-pulse">
                <div className="h-5 bg-gray-200 rounded w-64 mb-3" />
                <div className="h-4 bg-gray-100 rounded w-96 max-w-full" />
              </div>
            )) : swimmers.map((s) => (
              <a key={s.id} href={`/swimmers/${s.id}`} className="card p-4 hover:border-ssa-teal/40 hover:shadow-md transition-all block">
                <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <h2 className="font-semibold text-ssa-navy truncate">{displayName(s.name)}</h2>
                      {s.warning_count > 0 && (
                        <span className="text-xs font-semibold text-amber-800 bg-amber-100 px-2 py-0.5 rounded-full">
                          {s.warning_count} data warning{s.warning_count === 1 ? "" : "s"}
                        </span>
                      )}
                    </div>
                    <p className="text-sm text-gray-500 mt-1">
                      {s.team || "No team"}{s.age ? ` · Age ${s.age}` : ""}
                    </p>
                  </div>
                  <div className="grid grid-cols-2 sm:grid-cols-5 gap-2 text-center lg:min-w-[520px]">
                    <Metric label="Swims" value={s.individual_result_count} />
                    <Metric label="Relays" value={s.relay_result_count} />
                    <Metric label="Meets" value={s.meet_count} />
                    <Metric label="Events" value={s.event_count} />
                    <div className="bg-gray-50 rounded-lg px-3 py-2 text-left sm:text-center col-span-2 sm:col-span-1">
                      <div className="text-[10px] uppercase tracking-wider text-gray-400">Latest</div>
                      <div className="text-xs font-medium text-gray-700 truncate">{s.latest_meet?.date || "-"}</div>
                    </div>
                  </div>
                </div>
              </a>
            ))}
          </div>
        )}

        {!error && totalPages > 1 && (
          <div className="mt-6 flex items-center justify-between gap-4 text-sm">
            <button
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page <= 1}
              className="px-3 py-1.5 bg-white border border-gray-200 rounded-md disabled:text-gray-400 disabled:cursor-not-allowed hover:bg-gray-50"
            >
              Previous
            </button>
            <span className="text-gray-500">Page {page} of {totalPages}</span>
            <button
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              disabled={page >= totalPages}
              className="px-3 py-1.5 bg-white border border-gray-200 rounded-md disabled:text-gray-400 disabled:cursor-not-allowed hover:bg-gray-50"
            >
              Next
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div className="bg-ssa-navy/5 rounded-lg px-3 py-2">
      <div className="text-base font-bold text-ssa-navy">{value.toLocaleString()}</div>
      <div className="text-[10px] uppercase tracking-wider text-gray-500">{label}</div>
    </div>
  );
}
