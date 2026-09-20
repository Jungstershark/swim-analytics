"use client";

import React, { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  listAllResults,
  listMeets,
  listEvents,
  getResult,
  displayName,
  resultDisplayValue,
  resultStatusLabel,
  type CombinedResultItem,
  type ResultDetail,
  type PaginationInfo,
  type MeetListItem,
} from "@/lib/api";

const PAGE_SIZES = [25, 50, 100] as const;
const DEFAULT_PAGE_SIZE = 50;

export default function ResultsPage() {
  return (
    <Suspense fallback={<div className="mx-auto min-h-screen max-w-7xl px-4 py-12 text-sm text-gray-500">Loading results...</div>}>
      <ResultsContent />
    </Suspense>
  );
}

function ResultsContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const requestedRowType = searchParams.get("row_type");
  const rowType: "all" | "individual" | "relay" = requestedRowType === "individual" || requestedRowType === "relay" ? requestedRowType : "all";
  const search = searchParams.get("swimmer") ?? "";
  const eventFilter = searchParams.get("event") ?? "";
  const requestedMeetId = Number(searchParams.get("meet_id"));
  const meetId = Number.isInteger(requestedMeetId) && requestedMeetId > 0 ? requestedMeetId : undefined;
  const showDqOnly = searchParams.get("is_dq") === "true";
  const requestedPage = Number(searchParams.get("page"));
  const page = Number.isInteger(requestedPage) && requestedPage > 0 ? requestedPage : 1;
  const requestedLimit = Number(searchParams.get("limit"));
  const limit = PAGE_SIZES.includes(requestedLimit as (typeof PAGE_SIZES)[number]) ? requestedLimit : DEFAULT_PAGE_SIZE;
  // --- State ---
  const [results, setResults] = useState<CombinedResultItem[]>([]);
  const [pagination, setPagination] = useState<PaginationInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [expandedRow, setExpandedRow] = useState<string | null>(null);
  const [splitsCache, setSplitsCache] = useState<Record<string, ResultDetail>>({});
  const [loadingSplitRow, setLoadingSplitRow] = useState<string | null>(null);

  async function handleToggleSplits(resultId: number) {
    const rowKey = `individual-${resultId}`;
    if (expandedRow === rowKey) {
      setExpandedRow(null);
      return;
    }
    setExpandedRow(rowKey);
    if (splitsCache[rowKey]) return; // already cached
    setLoadingSplitRow(rowKey);
    try {
      const detail = await getResult(resultId);
      setSplitsCache((prev) => ({ ...prev, [rowKey]: detail }));
    } catch {
      // leave uncached so it retries on next click
    } finally {
      setLoadingSplitRow((current) => current === rowKey ? null : current);
    }
  }

  // Filter input drafts; committed filter values are owned by the URL.
  const [searchInput, setSearchInput] = useState(search);
  const [eventSearchInput, setEventSearchInput] = useState(eventFilter);
  const [eventDropdownOpen, setEventDropdownOpen] = useState(false);


  // Meets for dropdown
  const [meets, setMeets] = useState<MeetListItem[]>([]);

  // Unique events for dropdown (derived from loaded results + fetched)
  const [availableEvents, setAvailableEvents] = useState<string[]>([]);

  // Debounce timer ref
  const debounceRef = useRef<NodeJS.Timeout>();
  const resultsRequestRef = useRef(0);
  const observedQuery = searchParams.toString();
  const urlStateOwnerRef = useRef({
    params: new URLSearchParams(observedQuery),
    pendingQuery: null as string | null,
  });

  const updateUrl = useCallback((updates: Record<string, string | null>, resetPage = true) => {
    const next = new URLSearchParams(urlStateOwnerRef.current.params.toString());
    Object.entries(updates).forEach(([key, value]) => {
      if (value) next.set(key, value);
      else next.delete(key);
    });
    if (resetPage) next.delete("page");
    const query = next.toString();
    const href = query ? `/results?${query}` : "/results";
    const currentHref = `${window.location.pathname}${window.location.search}`;
    urlStateOwnerRef.current.params = next;
    urlStateOwnerRef.current.pendingQuery = href === currentHref ? null : query;
    if (href !== currentHref) router.push(href);
  }, [router]);

  useEffect(() => {
    const owner = urlStateOwnerRef.current;
    if (owner.pendingQuery === null || owner.pendingQuery === observedQuery) {
      owner.params = new URLSearchParams(observedQuery);
      owner.pendingQuery = null;
    }
  }, [observedQuery]);

  useEffect(() => {
    const rawLimit = searchParams.get("limit");
    if (rawLimit === null || (PAGE_SIZES.includes(Number(rawLimit) as (typeof PAGE_SIZES)[number]) && rawLimit !== String(DEFAULT_PAGE_SIZE))) return;
    const next = new URLSearchParams(searchParams.toString());
    next.delete("limit");
    const query = next.toString();
    router.replace(query ? `/results?${query}` : "/results", { scroll: false });
  }, [router, searchParams]);

  useEffect(() => {
    function syncHistoryState() {
      if (debounceRef.current) {
        clearTimeout(debounceRef.current);
        debounceRef.current = undefined;
      }
      const params = new URLSearchParams(window.location.search);
      urlStateOwnerRef.current.params = params;
      urlStateOwnerRef.current.pendingQuery = null;
      setSearchInput(params.get("swimmer") || "");
    }
    window.addEventListener("popstate", syncHistoryState);
    return () => window.removeEventListener("popstate", syncHistoryState);
  }, []);

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    setSearchInput(search);
  }, [search]);

  useEffect(() => {
    if (!eventDropdownOpen) setEventSearchInput(eventFilter);
  }, [eventDropdownOpen, eventFilter]);

  // --- Load meets for filter dropdown ---
  useEffect(() => {
    listMeets({ limit: 100 })
      .then((res) => setMeets(res.data))
      .catch(() => {});
  }, []);

  // --- Load available events for filter dropdown ---
  useEffect(() => {
    listEvents(meetId)
      .then((res) => setAvailableEvents(res.events))
      .catch(() => {});
  }, [meetId]);

  // --- Fetch results ---
  useEffect(() => {
    const requestId = ++resultsRequestRef.current;
    let active = true;
    setLoading(true);
    setError("");
    listAllResults({
        page,
        limit,
        swimmer: search || undefined,
        event: eventFilter || undefined,
        meet_id: meetId,
        is_dq: showDqOnly ? true : undefined,
        row_type: rowType,
      })
      .then((res) => {
        if (!active || resultsRequestRef.current !== requestId) return;
        setResults(res.data);
        setPagination(res.pagination);
      })
      .catch((e: any) => {
        if (!active || resultsRequestRef.current !== requestId) return;
        setError(e.message || "Failed to load results");
      })
      .finally(() => {
        if (active && resultsRequestRef.current === requestId) setLoading(false);
      });

    return () => {
      active = false;
    };
  }, [page, limit, search, eventFilter, meetId, showDqOnly, rowType]);

  function setRowType(nextRowType: "all" | "individual" | "relay") {
    updateUrl({ row_type: nextRowType });
  }

  // Debounced search handler
  function handleSearchChange(value: string) {
    setSearchInput(value);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      updateUrl({ swimmer: value || null });
    }, 300);
  }

  // --- Derived values ---
  const totalResults = pagination?.total ?? 0;
  const totalPages = pagination?.total_pages ?? 0;
  const responsePage = pagination?.page ?? page;
  const responseLimit = pagination?.limit ?? limit;
  const dqCount = results.filter((r) => r.is_dq).length;
  const showingFrom = totalResults === 0 ? 0 : (responsePage - 1) * responseLimit + 1;
  const showingTo = Math.min(responsePage * responseLimit, totalResults);

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
          <div className="flex min-w-0 flex-col gap-3 lg:flex-row">
            {/* Search */}
            <div className="relative min-w-0 flex-1">
              <svg
                className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400"
                fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24"
              >
                <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" />
              </svg>
              <input
                type="text"
                placeholder="Search by swimmer name..."
                value={searchInput}
                onChange={(e) => handleSearchChange(e.target.value)}
                className="min-h-11 w-full pl-10 pr-4 py-2.5 bg-gray-50 border border-gray-200 rounded-lg text-sm
                           focus:outline-none focus:ring-2 focus:ring-ssa-teal/20 focus:border-ssa-teal
                           placeholder:text-gray-400 transition-colors"
              />
            </div>

            {/* Event filter — searchable dropdown */}
            <div className="relative min-w-0 lg:min-w-[300px]">
              <input
                type="text"
                placeholder="All Events"
                value={eventDropdownOpen ? eventSearchInput : (eventFilter || "")}
                onChange={(e) => {
                  setEventSearchInput(e.target.value);
                  setEventDropdownOpen(true);
                }}
                onFocus={() => {
                  setEventSearchInput(eventFilter);
                  setEventDropdownOpen(true);
                }}
                onBlur={() => {
                  // Delay to allow click on dropdown item
                  setTimeout(() => setEventDropdownOpen(false), 200);
                }}
                className="min-h-11 w-full px-4 pr-12 py-2.5 bg-gray-50 border border-gray-200 rounded-lg text-sm text-gray-600
                           focus:outline-none focus:ring-2 focus:ring-ssa-teal/20 focus:border-ssa-teal
                           placeholder:text-gray-400 transition-colors"
              />
              {eventFilter && !eventDropdownOpen && (
                <button
                  type="button"
                  aria-label="Clear event filter"
                  onClick={() => { updateUrl({ event: null }); setEventSearchInput(""); }}
                  className="absolute right-0 top-1/2 flex min-h-11 min-w-11 -translate-y-1/2 items-center justify-center text-gray-400 hover:text-gray-600"
                >
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              )}
              {eventDropdownOpen && (
                <div className="absolute z-20 mt-1 w-full max-h-60 overflow-y-auto bg-white border border-gray-200 rounded-lg shadow-lg">
                  <button
                    onMouseDown={(e) => e.preventDefault()}
                    onClick={() => { updateUrl({ event: null }); setEventSearchInput(""); setEventDropdownOpen(false); }}
                    className="min-h-11 w-full px-4 py-2 text-left text-sm text-gray-500 hover:bg-gray-50"
                  >
                    All Events
                  </button>
                  {availableEvents
                    .filter((evt) => !eventSearchInput || evt.toLowerCase().includes(eventSearchInput.toLowerCase()))
                    .map((evt) => (
                      <button
                        key={evt}
                        onMouseDown={(e) => e.preventDefault()}
                        onClick={() => { updateUrl({ event: evt }); setEventSearchInput(evt); setEventDropdownOpen(false); }}
                        className={`min-h-11 w-full px-4 py-2 text-left text-sm hover:bg-ssa-teal/5 transition-colors ${
                          evt === eventFilter ? "text-ssa-teal font-medium bg-ssa-teal/5" : "text-gray-700"
                        }`}
                      >
                        {evt}
                      </button>
                    ))}
                </div>
              )}
            </div>

            {/* Meet filter */}
            <select
              aria-label="Filter by meet"
              value={meetId ?? ""}
              onChange={(e) => updateUrl({ meet_id: e.target.value || null })}
              className="min-h-11 px-4 py-2.5 bg-gray-50 border border-gray-200 rounded-lg text-sm text-gray-600
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
              type="button"
              onClick={() => updateUrl({ is_dq: showDqOnly ? null : "true" })}
              className={`min-h-11 px-4 py-2.5 rounded-lg text-sm font-medium border transition-colors whitespace-nowrap ${
                showDqOnly
                  ? "bg-red-50 border-red-200 text-red-700"
                  : "bg-gray-50 border-gray-200 text-gray-600 hover:bg-gray-100"
              }`}
            >
              {showDqOnly ? "DQ Only" : "Show DQ"}
            </button>
          </div>
          <div className="mt-3 flex flex-wrap gap-2" role="group" aria-label="Filter results by type">
            {([[
              "all", "All results"
            ], [
              "individual", "Individual results"
            ], [
              "relay", "Relay results"
            ]] as const).map(([value, label]) => (
              <button
                key={value}
                type="button"
                aria-pressed={rowType === value}
                onClick={() => setRowType(value)}
                className={`min-h-11 rounded-lg border px-4 text-sm font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ssa-teal ${rowType === value ? "border-ssa-navy bg-ssa-navy text-white" : "border-gray-200 bg-gray-50 text-gray-700 hover:bg-gray-100"}`}
              >
                {label}
              </button>
            ))}
          </div>
          <label className="mt-3 flex min-h-11 items-center gap-2 text-sm font-medium text-gray-600">
            Results per page
            <select
              aria-label="Results per page"
              value={limit}
              onChange={(event) => updateUrl({ limit: event.target.value === String(DEFAULT_PAGE_SIZE) ? null : event.target.value })}
              className="min-h-11 rounded-lg border border-gray-200 bg-gray-50 px-3 text-sm text-gray-700 focus:border-ssa-teal focus:outline-none focus:ring-2 focus:ring-ssa-teal/20"
            >
              {PAGE_SIZES.map((size) => <option key={size} value={size}>{size}</option>)}
            </select>
          </label>
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
          <div role="alert" className="card p-8 text-center mb-6">
            <p className="text-red-600 font-medium">{error}</p>
            <p className="text-gray-500 text-sm mt-1">Refresh the page or adjust the filters to try again.</p>
          </div>
        )}

        {/* Results Table */}
        {!error && (
          <div className="card overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr className="bg-ssa-navy">
                    <th scope="col" className="px-6 py-3.5 text-left text-xs font-semibold text-gray-300 uppercase tracking-wider">
                      Event
                    </th>
                    <th scope="col" className="px-6 py-3.5 text-left text-xs font-semibold text-gray-300 uppercase tracking-wider">
                      Swimmer
                    </th>
                    <th scope="col" className="px-6 py-3.5 text-center text-xs font-semibold text-gray-300 uppercase tracking-wider w-16">
                      Age
                    </th>
                    <th scope="col" className="px-6 py-3.5 text-left text-xs font-semibold text-gray-300 uppercase tracking-wider hidden md:table-cell">
                      Club
                    </th>
                    <th scope="col" className="px-6 py-3.5 text-right text-xs font-semibold text-gray-300 uppercase tracking-wider w-28">
                      Time
                    </th>
                    <th scope="col" className="px-6 py-3.5 text-center text-xs font-semibold text-gray-300 uppercase tracking-wider w-20 hidden lg:table-cell">
                      Round
                    </th>
                    <th scope="col" className="px-6 py-3.5 text-center text-xs font-semibold text-gray-300 uppercase tracking-wider w-20">
                      Place
                    </th>
                    <th scope="col" className="px-6 py-3.5 text-center text-xs font-semibold text-gray-300 uppercase tracking-wider w-24">
                      Status
                    </th>
                    <th scope="col" className="px-6 py-3.5 text-center text-xs font-semibold text-gray-300 uppercase tracking-wider w-16">
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
                        const rowKey = `${result.type}-${result.id}`;
                        const isExpanded = expandedRow === rowKey;
                        const detailsId = `result-details-${rowKey}`;
                        const statusLabel = resultStatusLabel(result.status, result.is_dq);

                        return (
                          <React.Fragment key={rowKey}>
                            <tr
                              className={`
                                ${index % 2 === 0 ? "bg-white" : "bg-gray-50/50"}
                                ${result.is_dq ? "bg-red-50/60" : ""}
                                hover:bg-ssa-teal/5 transition-colors
                              `}
                            >
                              {/* Event */}
                              <td className="px-6 py-4 whitespace-nowrap">
                                <div>
                                  <a href={`/results?meet_id=${result.meet.id}&event=${encodeURIComponent(result.event)}&row_type=${result.type}`} className="text-sm font-medium text-gray-700 hover:text-ssa-teal">{result.event}</a>
                                  <a href={`/meets/${result.meet.id}`} className="mt-1 block text-xs text-gray-400 hover:text-ssa-teal">{result.meet.name}</a>
                                  {result.type === "relay" && result.team_name && (
                                    <div className="text-xs text-gray-400">{result.team_name} {result.relay_letter}</div>
                                  )}
                                </div>
                              </td>

                              {/* Swimmer / Team */}
                              <td className="px-6 py-4 whitespace-nowrap">
                                {result.type === "individual" && result.swimmer ? (
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
                                      {displayName(result.swimmer.name)}
                                    </a>
                                  </div>
                                ) : (
                                  <span className="text-sm text-gray-600">
                                    {result.legs?.map(l => displayName(l.swimmer.name).replace(", ", " ")).join(", ") || result.team_name}
                                  </span>
                                )}
                              </td>

                              {/* Age */}
                              <td className="px-6 py-4 whitespace-nowrap text-center">
                                <span className="text-sm text-gray-600">
                                  {result.type === "individual" && result.swimmer ? (result.swimmer.age ?? "-") : "-"}
                                </span>
                              </td>

                              {/* Club */}
                              <td className="px-6 py-4 whitespace-nowrap hidden md:table-cell">
                                <span className="text-sm text-gray-600">
                                  {result.type === "individual" && result.swimmer ? result.swimmer.team : result.team_name}
                                </span>
                              </td>

                              {/* Time */}
                              <td className="px-6 py-4 whitespace-nowrap text-right">
                                <span className="text-sm font-mono font-bold text-ssa-navy">
                                  {resultDisplayValue(result.status, result.time, result.is_dq)}
                                </span>
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
                                {statusLabel ? (
                                  <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold ring-1 ${statusLabel === "DQ" ? "bg-red-100 text-red-700 ring-red-200" : "bg-amber-50 text-amber-700 ring-amber-200"}`}>
                                    {statusLabel}
                                  </span>
                                ) : result.type === "relay" ? (
                                  <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-purple-50 text-purple-700">
                                    Relay
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

                              {/* Details toggle */}
                              <td className="px-6 py-4 whitespace-nowrap text-center">
                                <button
                                  type="button"
                                  aria-label={result.type === "relay" ? "View relay legs" : "View splits"}
                                  aria-expanded={isExpanded}
                                  aria-controls={detailsId}
                                  onClick={() => result.type === "individual" ? handleToggleSplits(result.id) : setExpandedRow(isExpanded ? null : rowKey)}
                                  className="inline-flex min-h-11 min-w-11 items-center justify-center text-ssa-teal transition-colors hover:text-ssa-navy"
                                  title={result.type === "relay" ? "View relay legs" : "View splits"}
                                >
                                  <svg className={`w-5 h-5 transition-transform ${isExpanded ? "rotate-180" : ""}`} fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
                                    <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 8.25l-7.5 7.5-7.5-7.5" />
                                  </svg>
                                </button>
                              </td>
                            </tr>

                            {/* Expanded details row */}
                            {isExpanded && result.type === "individual" && (
                              <tr id={detailsId} className="bg-ssa-navy/5">
                                <td colSpan={9} className="px-6 py-3">
                                  {loadingSplitRow === rowKey ? (
                                    <div className="text-xs text-gray-400 animate-pulse">Loading splits...</div>
                                  ) : splitsCache[rowKey]?.splits ? (
                                    <div className="flex flex-wrap gap-2 items-center">
                                      <span className="text-xs font-semibold text-ssa-navy uppercase mr-2">Splits:</span>
                                      {(() => {
                                        try {
                                          const splits: { cumulative: string; split: string | null; distance: number }[] = JSON.parse(splitsCache[rowKey].splits!);
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
                                      {splitsCache[rowKey].reaction_time && (
                                        <div className="text-center bg-white rounded px-2 py-1 border border-gray-200 ml-2">
                                          <div className="text-[10px] text-gray-400">RT</div>
                                          <div className="text-xs font-mono font-semibold text-gray-600">{splitsCache[rowKey].reaction_time}</div>
                                        </div>
                                      )}
                                    </div>
                                  ) : (
                                    <div className="text-xs text-gray-400">No split data available</div>
                                  )}
                                </td>
                              </tr>
                            )}
                            {isExpanded && result.type === "relay" && result.legs && (
                              <tr id={detailsId} className="bg-ssa-navy/5">
                                <td colSpan={9} className="px-6 py-3">
                                  <div className="flex flex-wrap gap-3">
                                    {[...result.legs].sort((a, b) => a.leg_number - b.leg_number).map((leg) => {
                                      let legSplits: {cumulative:string;split:string|null;distance:number}[] = [];
                                      if (leg.splits) { try { legSplits = JSON.parse(leg.splits); } catch {} }
                                      return (
                                        <div key={leg.leg_number} className="rounded-lg px-4 py-3 border bg-white border-gray-200 min-w-[140px]">
                                          <div className="text-[10px] text-gray-400 uppercase text-center">Leg {leg.leg_number}</div>
                                          <a href={`/swimmers/${leg.swimmer.id}`} className="block text-sm font-semibold text-ssa-navy hover:text-ssa-teal transition-colors text-center">
                                            {displayName(leg.swimmer.name).replace(", ", " ")}
                                          </a>
                                          <div className="text-sm font-mono font-bold text-ssa-navy mt-1 text-center">{leg.split_time || "--"}</div>
                                          {leg.reaction_time && <div className="text-[10px] font-mono text-gray-400 text-center">RT {leg.reaction_time}</div>}
                                          {legSplits.length > 0 && (
                                            <div className="mt-2 pt-2 border-t border-gray-100 space-y-0.5">
                                              {legSplits.map((s, i) => (
                                                <div key={i} className="flex justify-between text-[10px] font-mono">
                                                  <span className="text-gray-400">{s.distance}m</span>
                                                  <span className="text-gray-600">{s.cumulative}</span>
                                                </div>
                                              ))}
                                            </div>
                                          )}
                                        </div>
                                      );
                                    })}
                                  </div>
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
                type="button"
                onClick={() => updateUrl({ page: String(Math.max(1, responsePage - 1)) }, false)}
                disabled={responsePage <= 1}
                className={`min-h-11 px-4 py-1.5 text-sm bg-white border border-gray-200 rounded-md transition-colors ${
                  responsePage <= 1
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
                } else if (responsePage <= 3) {
                  pageNum = i + 1;
                } else if (responsePage >= totalPages - 2) {
                  pageNum = totalPages - 4 + i;
                } else {
                  pageNum = responsePage - 2 + i;
                }
                return (
                  <button
                    type="button"
                    key={pageNum}
                    onClick={() => updateUrl({ page: String(pageNum) }, false)}
                    className={`min-h-11 min-w-11 px-3 py-1.5 text-sm rounded-md transition-colors ${
                      pageNum === responsePage
                        ? "font-medium text-white bg-ssa-navy"
                        : "text-gray-700 bg-white border border-gray-200 hover:bg-gray-50"
                    }`}
                  >
                    {pageNum}
                  </button>
                );
              })}

              <button
                type="button"
                onClick={() => updateUrl({ page: String(Math.min(totalPages, responsePage + 1)) }, false)}
                disabled={responsePage >= totalPages}
                className={`min-h-11 px-4 py-1.5 text-sm bg-white border border-gray-200 rounded-md transition-colors ${
                  responsePage >= totalPages
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
