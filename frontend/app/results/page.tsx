"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  listResults,
  listMeets,
  getResult,
  type ResultListItem,
  type ResultDetail,
  type PaginationInfo,
  type MeetListItem,
} from "@/lib/api";

export default function ResultsPage() {
  // --- State ---
  const [results, setResults] = useState<ResultListItem[]>([]);
  const [pagination, setPagination] = useState<PaginationInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [expandedRow, setExpandedRow] = useState<number | null>(null);
  const [splitsCache, setSplitsCache] = useState<Record<number, ResultDetail>>({});
  const [loadingSplits, setLoadingSplits] = useState(false);

  async function handleToggleSplits(resultId: number) {
    if (expandedRow === resultId) {
      setExpandedRow(null);
      return;
    }
    setExpandedRow(resultId);
    if (splitsCache[resultId]) return; // already cached
    setLoadingSplits(true);
    try {
      const detail = await getResult(resultId);
      setSplitsCache((prev) => ({ ...prev, [resultId]: detail }));
    } catch {
      // leave uncached so it retries on next click
    } finally {
      setLoadingSplits(false);
    }
  }

  // Filters
  const [search, setSearch] = useState("");
  const [eventFilter, setEventFilter] = useState("");
  const [meetId, setMeetId] = useState<number | undefined>();
  const [showDqOnly, setShowDqOnly] = useState(false);
  const [page, setPage] = useState(1);
  const limit = 50;

  // Meets for dropdown
  const [meets, setMeets] = useState<MeetListItem[]>([]);

  // Unique events for dropdown (derived from loaded results + fetched)
  const [availableEvents, setAvailableEvents] = useState<string[]>([]);

  // Debounce timer ref
  const debounceRef = useRef<NodeJS.Timeout>();

  // --- Load meets for filter dropdown ---
  useEffect(() => {
    listMeets({ limit: 100 })
      .then((res) => setMeets(res.data))
      .catch(() => {});
  }, []);

  // --- Load available events from first results load ---
  useEffect(() => {
    // Fetch a large batch to extract unique events
    listResults({ limit: 200, sort: "event", order: "asc" })
      .then((res) => {
        const events = Array.from(new Set(res.data.map((r) => r.event))).sort();
        setAvailableEvents(events);
      })
      .catch(() => {});
  }, []);

  // --- Fetch results ---
  const fetchResults = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const res = await listResults({
        page,
        limit,
        swimmer: search || undefined,
        event: eventFilter || undefined,
        meet_id: meetId,
        is_dq: showDqOnly ? true : undefined,
        sort: "placement",
        order: "asc",
      });
      setResults(res.data);
      setPagination(res.pagination);
    } catch (e: any) {
      setError(e.message || "Failed to load results");
    } finally {
      setLoading(false);
    }
  }, [page, search, eventFilter, meetId, showDqOnly]);

  // Fetch on filter change
  useEffect(() => {
    fetchResults();
  }, [fetchResults]);

  // Debounced search handler
  function handleSearchChange(value: string) {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      setSearch(value);
      setPage(1);
    }, 300);
  }

  // --- Derived values ---
  const totalResults = pagination?.total ?? 0;
  const totalPages = pagination?.total_pages ?? 0;
  const dqCount = results.filter((r) => r.is_dq).length;
  const showingFrom = totalResults === 0 ? 0 : (page - 1) * limit + 1;
  const showingTo = Math.min(page * limit, totalResults);

  return (
    <div className="min-h-screen">
      {/* Page Header */}
      <div className="bg-white border-b border-gray-200">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
          <nav className="flex items-center gap-2 text-sm mb-4">
            <a href="/" className="text-gray-500 hover:text-ssa-navy transition-colors">
              Dashboard
            </a>
            <svg className="w-4 h-4 text-gray-300" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M8.25 4.5l7.5 7.5-7.5 7.5" />
            </svg>
            <span className="text-ssa-navy font-medium">Results</span>
          </nav>

          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
            <div>
              <h1 className="text-2xl font-bold text-ssa-navy">Meet Results</h1>
              <p className="text-gray-500 text-sm mt-1">
                Browse and search swimmer results across all competitions
              </p>
            </div>
            <a href="/upload" className="btn-primary self-start">
              <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5" />
              </svg>
              Upload Results
            </a>
          </div>
        </div>
      </div>

      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Search & Filters */}
        <div className="card p-4 mb-6">
          <div className="flex flex-col sm:flex-row gap-3">
            {/* Search */}
            <div className="relative flex-1">
              <svg
                className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400"
                fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24"
              >
                <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" />
              </svg>
              <input
                type="text"
                placeholder="Search by swimmer name..."
                defaultValue={search}
                onChange={(e) => handleSearchChange(e.target.value)}
                className="w-full pl-10 pr-4 py-2.5 bg-gray-50 border border-gray-200 rounded-lg text-sm
                           focus:outline-none focus:ring-2 focus:ring-ssa-teal/20 focus:border-ssa-teal
                           placeholder:text-gray-400 transition-colors"
              />
            </div>

            {/* Event filter */}
            <select
              value={eventFilter}
              onChange={(e) => { setEventFilter(e.target.value); setPage(1); }}
              className="px-4 py-2.5 bg-gray-50 border border-gray-200 rounded-lg text-sm text-gray-600
                         focus:outline-none focus:ring-2 focus:ring-ssa-teal/20 focus:border-ssa-teal
                         transition-colors appearance-none cursor-pointer
                         bg-[url('data:image/svg+xml;charset=utf-8,%3Csvg%20xmlns%3D%22http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%22%20width%3D%2224%22%20height%3D%2224%22%20viewBox%3D%220%200%2024%2024%22%20fill%3D%22none%22%20stroke%3D%22%239ca3af%22%20stroke-width%3D%222%22%20stroke-linecap%3D%22round%22%20stroke-linejoin%3D%22round%22%3E%3Cpath%20d%3D%22m6%209%206%206%206-6%22%2F%3E%3C%2Fsvg%3E')]
                         bg-[length:16px] bg-[right_12px_center] bg-no-repeat pr-10"
            >
              <option value="">All Events</option>
              {availableEvents.map((evt) => (
                <option key={evt} value={evt}>{evt}</option>
              ))}
            </select>

            {/* Meet filter */}
            <select
              value={meetId ?? ""}
              onChange={(e) => { setMeetId(e.target.value ? Number(e.target.value) : undefined); setPage(1); }}
              className="px-4 py-2.5 bg-gray-50 border border-gray-200 rounded-lg text-sm text-gray-600
                         focus:outline-none focus:ring-2 focus:ring-ssa-teal/20 focus:border-ssa-teal
                         transition-colors appearance-none cursor-pointer
                         bg-[url('data:image/svg+xml;charset=utf-8,%3Csvg%20xmlns%3D%22http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%22%20width%3D%2224%22%20height%3D%2224%22%20viewBox%3D%220%200%2024%2024%22%20fill%3D%22none%22%20stroke%3D%22%239ca3af%22%20stroke-width%3D%222%22%20stroke-linecap%3D%22round%22%20stroke-linejoin%3D%22round%22%3E%3Cpath%20d%3D%22m6%209%206%206%206-6%22%2F%3E%3C%2Fsvg%3E')]
                         bg-[length:16px] bg-[right_12px_center] bg-no-repeat pr-10"
            >
              <option value="">All Meets</option>
              {meets.map((m) => (
                <option key={m.id} value={m.id}>{m.name}</option>
              ))}
            </select>

            {/* DQ toggle */}
            <button
              onClick={() => { setShowDqOnly(!showDqOnly); setPage(1); }}
              className={`px-4 py-2.5 rounded-lg text-sm font-medium border transition-colors whitespace-nowrap ${
                showDqOnly
                  ? "bg-red-50 border-red-200 text-red-700"
                  : "bg-gray-50 border-gray-200 text-gray-600 hover:bg-gray-100"
              }`}
            >
              {showDqOnly ? "DQ Only" : "Show DQ"}
            </button>
          </div>
        </div>

        {/* Results Summary */}
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-4">
            <p className="text-sm text-gray-600">
              {totalResults > 0 ? (
                <>
                  Showing{" "}
                  <span className="font-semibold text-ssa-navy">
                    {showingFrom}&ndash;{showingTo}
                  </span>{" "}
                  of{" "}
                  <span className="font-semibold text-ssa-navy">
                    {totalResults.toLocaleString()}
                  </span>{" "}
                  results
                </>
              ) : loading ? (
                "Loading..."
              ) : (
                "No results found"
              )}
            </p>
            {dqCount > 0 && (
              <span className="text-xs text-amber-700 bg-amber-50 border border-amber-200 px-2 py-0.5 rounded-full font-medium">
                {dqCount} DQ on page
              </span>
            )}
          </div>
        </div>

        {/* Error state */}
        {error && (
          <div className="card p-8 text-center mb-6">
            <p className="text-red-600 font-medium">{error}</p>
            <p className="text-gray-400 text-sm mt-1">
              Make sure the backend is running: <code className="bg-gray-100 px-1 rounded">uvicorn app.main:app --reload</code>
            </p>
          </div>
        )}

        {/* Results Table */}
        {!error && (
          <div className="card overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr className="bg-ssa-navy">
                    <th className="px-6 py-3.5 text-left text-xs font-semibold text-gray-300 uppercase tracking-wider">
                      Event
                    </th>
                    <th className="px-6 py-3.5 text-left text-xs font-semibold text-gray-300 uppercase tracking-wider">
                      Swimmer
                    </th>
                    <th className="px-6 py-3.5 text-center text-xs font-semibold text-gray-300 uppercase tracking-wider w-16">
                      Age
                    </th>
                    <th className="px-6 py-3.5 text-left text-xs font-semibold text-gray-300 uppercase tracking-wider hidden md:table-cell">
                      Club
                    </th>
                    <th className="px-6 py-3.5 text-right text-xs font-semibold text-gray-300 uppercase tracking-wider w-28">
                      Time
                    </th>
                    <th className="px-6 py-3.5 text-center text-xs font-semibold text-gray-300 uppercase tracking-wider w-20 hidden lg:table-cell">
                      Round
                    </th>
                    <th className="px-6 py-3.5 text-center text-xs font-semibold text-gray-300 uppercase tracking-wider w-20">
                      Place
                    </th>
                    <th className="px-6 py-3.5 text-center text-xs font-semibold text-gray-300 uppercase tracking-wider w-24">
                      Status
                    </th>
                    <th className="px-6 py-3.5 text-center text-xs font-semibold text-gray-300 uppercase tracking-wider w-16">
                      Splits
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {loading
                    ? Array.from({ length: 10 }).map((_, i) => (
                        <tr key={i} className="animate-pulse">
                          <td className="px-6 py-4"><div className="h-4 bg-gray-200 rounded w-48" /></td>
                          <td className="px-6 py-4"><div className="h-4 bg-gray-200 rounded w-40" /></td>
                          <td className="px-6 py-4"><div className="h-4 bg-gray-200 rounded w-8 mx-auto" /></td>
                          <td className="px-6 py-4 hidden md:table-cell"><div className="h-4 bg-gray-200 rounded w-32" /></td>
                          <td className="px-6 py-4"><div className="h-4 bg-gray-200 rounded w-16 ml-auto" /></td>
                          <td className="px-6 py-4 hidden lg:table-cell"><div className="h-4 bg-gray-200 rounded w-14 mx-auto" /></td>
                          <td className="px-6 py-4"><div className="h-4 bg-gray-200 rounded w-8 mx-auto" /></td>
                          <td className="px-6 py-4"><div className="h-4 bg-gray-200 rounded w-16 mx-auto" /></td>
                          <td className="px-6 py-4"><div className="h-4 bg-gray-200 rounded w-6 mx-auto" /></td>
                        </tr>
                      ))
                    : results.map((result, index) => {
                        const isExpanded = expandedRow === result.id;

                        return (
                          <React.Fragment key={result.id}>
                            <tr
                              className={`
                                ${index % 2 === 0 ? "bg-white" : "bg-gray-50/50"}
                                ${result.is_dq ? "bg-red-50/60" : ""}
                                hover:bg-ssa-teal/5 transition-colors
                              `}
                            >
                              {/* Event */}
                              <td className="px-6 py-4 whitespace-nowrap">
                                <span className="text-sm text-gray-700 font-medium">
                                  {result.event}
                                </span>
                              </td>

                              {/* Swimmer (clickable) */}
                              <td className="px-6 py-4 whitespace-nowrap">
                                <div className="flex items-center gap-1.5">
                                  {result.is_guest && (
                                    <span className="text-xs text-amber-600 bg-amber-50 px-1.5 py-0.5 rounded font-medium" title="Guest — foreign/visiting swimmer, not eligible for local placement">
                                      Guest
                                    </span>
                                  )}
                                  <a
                                    href={`/swimmers/${result.swimmer.id}`}
                                    className="text-sm font-semibold text-ssa-navy hover:text-ssa-teal transition-colors"
                                  >
                                    {result.swimmer.name}
                                  </a>
                                </div>
                              </td>

                              {/* Age */}
                              <td className="px-6 py-4 whitespace-nowrap text-center">
                                <span className="text-sm text-gray-600">
                                  {result.swimmer.age ?? "-"}
                                </span>
                              </td>

                              {/* Club */}
                              <td className="px-6 py-4 whitespace-nowrap hidden md:table-cell">
                                <span className="text-sm text-gray-600">
                                  {result.swimmer.team}
                                </span>
                              </td>

                              {/* Time */}
                              <td className="px-6 py-4 whitespace-nowrap text-right">
                                {result.is_dq || !result.time ? (
                                  <span className="text-sm text-gray-400">--</span>
                                ) : (
                                  <span className="text-sm font-mono font-bold text-ssa-navy">
                                    {result.time}
                                  </span>
                                )}
                              </td>

                              {/* Round */}
                              <td className="px-6 py-4 whitespace-nowrap text-center hidden lg:table-cell">
                                <span className={`text-xs font-medium px-2 py-0.5 rounded ${
                                  result.round === "Final"
                                    ? "bg-ssa-navy/10 text-ssa-navy"
                                    : result.round === "Prelim"
                                    ? "bg-gray-100 text-gray-500"
                                    : "bg-gray-100 text-gray-500"
                                }`}>
                                  {result.round || "-"}
                                </span>
                              </td>

                              {/* Placement */}
                              <td className="px-6 py-4 whitespace-nowrap text-center">
                                {result.is_dq || result.placement == null ? (
                                  <span className="text-sm text-gray-400">--</span>
                                ) : result.placement <= 3 ? (
                                  <span
                                    className={`
                                      inline-flex items-center justify-center w-7 h-7 rounded-full text-xs font-bold
                                      ${result.placement === 1 ? "bg-amber-100 text-amber-800 ring-1 ring-amber-300" : ""}
                                      ${result.placement === 2 ? "bg-gray-100 text-gray-600 ring-1 ring-gray-300" : ""}
                                      ${result.placement === 3 ? "bg-orange-50 text-orange-700 ring-1 ring-orange-200" : ""}
                                    `}
                                  >
                                    {result.placement}
                                  </span>
                                ) : (
                                  <span className="text-sm font-medium text-gray-500">
                                    {result.placement}
                                  </span>
                                )}
                              </td>

                              {/* Status */}
                              <td className="px-6 py-4 whitespace-nowrap text-center">
                                {result.is_dq ? (
                                  <span
                                    className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold bg-red-100 text-red-700 ring-1 ring-red-200 cursor-help"
                                    title={result.dq_code ? `${result.dq_code}: ${result.dq_description}` : "Disqualified"}
                                  >
                                    DQ
                                  </span>
                                ) : result.qualifier === "qMTS" ? (
                                  <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold bg-ssa-teal/10 text-ssa-teal ring-1 ring-ssa-teal/20">
                                    qMTS
                                  </span>
                                ) : result.qualifier === "MTS" ? (
                                  <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold bg-blue-50 text-blue-700 ring-1 ring-blue-200">
                                    MTS
                                  </span>
                                ) : null}
                              </td>

                              {/* Splits toggle */}
                              <td className="px-6 py-4 whitespace-nowrap text-center">
                                <button
                                  onClick={() => handleToggleSplits(result.id)}
                                  className="text-ssa-teal hover:text-ssa-navy transition-colors"
                                  title="View splits"
                                >
                                  <svg className={`w-5 h-5 transition-transform ${isExpanded ? "rotate-180" : ""}`} fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
                                    <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 8.25l-7.5 7.5-7.5-7.5" />
                                  </svg>
                                </button>
                              </td>
                            </tr>

                            {/* Expanded splits row */}
                            {isExpanded && (
                              <tr key={`${result.id}-splits`} className="bg-ssa-navy/5">
                                <td colSpan={9} className="px-6 py-3">
                                  {loadingSplits ? (
                                    <div className="text-xs text-gray-400 animate-pulse">Loading splits...</div>
                                  ) : splitsCache[result.id]?.splits ? (
                                    <div className="flex flex-wrap gap-2 items-center">
                                      <span className="text-xs font-semibold text-ssa-navy uppercase mr-2">Splits:</span>
                                      {(() => {
                                        try {
                                          const splits: { cumulative: string; split: string | null; distance: number }[] = JSON.parse(splitsCache[result.id].splits!);
                                          return splits.map((s, i) => (
                                            <div key={i} className="text-center bg-white rounded px-2 py-1 border border-gray-200">
                                              <div className="text-[10px] text-gray-400">{s.distance}m</div>
                                              <div className="text-xs font-mono font-semibold text-ssa-navy">{s.cumulative}</div>
                                              {s.split && (
                                                <div className="text-[10px] font-mono text-gray-500">({s.split})</div>
                                              )}
                                            </div>
                                          ));
                                        } catch { return null; }
                                      })()}
                                      {splitsCache[result.id].reaction_time && (
                                        <div className="text-center bg-white rounded px-2 py-1 border border-gray-200 ml-2">
                                          <div className="text-[10px] text-gray-400">RT</div>
                                          <div className="text-xs font-mono font-semibold text-gray-600">{splitsCache[result.id].reaction_time}</div>
                                        </div>
                                      )}
                                    </div>
                                  ) : (
                                    <div className="text-xs text-gray-400">No split data available</div>
                                  )}
                                </td>
                              </tr>
                            )}
                          </React.Fragment>
                        );
                      })}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* Pagination */}
        {!error && totalPages > 0 && (
          <div className="mt-4 flex flex-col sm:flex-row items-center justify-between gap-4 text-sm">
            <p className="text-gray-500">
              Showing {showingFrom}&ndash;{showingTo} of{" "}
              <span className="font-medium text-gray-700">
                {totalResults.toLocaleString()} results
              </span>
            </p>
            <div className="flex items-center gap-2">
              <button
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={page <= 1}
                className={`px-3 py-1.5 text-sm bg-white border border-gray-200 rounded-md transition-colors ${
                  page <= 1
                    ? "text-gray-400 cursor-not-allowed"
                    : "text-gray-700 hover:bg-gray-50"
                }`}
              >
                Previous
              </button>

              {/* Page numbers */}
              {Array.from({ length: Math.min(5, totalPages) }).map((_, i) => {
                let pageNum: number;
                if (totalPages <= 5) {
                  pageNum = i + 1;
                } else if (page <= 3) {
                  pageNum = i + 1;
                } else if (page >= totalPages - 2) {
                  pageNum = totalPages - 4 + i;
                } else {
                  pageNum = page - 2 + i;
                }
                return (
                  <button
                    key={pageNum}
                    onClick={() => setPage(pageNum)}
                    className={`px-3 py-1.5 text-sm rounded-md transition-colors ${
                      pageNum === page
                        ? "font-medium text-white bg-ssa-navy"
                        : "text-gray-700 bg-white border border-gray-200 hover:bg-gray-50"
                    }`}
                  >
                    {pageNum}
                  </button>
                );
              })}

              <button
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                disabled={page >= totalPages}
                className={`px-3 py-1.5 text-sm bg-white border border-gray-200 rounded-md transition-colors ${
                  page >= totalPages
                    ? "text-gray-400 cursor-not-allowed"
                    : "text-gray-700 hover:bg-gray-50"
                }`}
              >
                Next
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
