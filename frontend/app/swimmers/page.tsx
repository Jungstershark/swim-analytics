"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  listSwimmers,
  displayName,
  type SwimmerListItem,
  type PaginationInfo,
} from "@/lib/api";

export default function SwimmersPage() {
  const [swimmers, setSwimmers] = useState<SwimmerListItem[]>([]);
  const [pagination, setPagination] = useState<PaginationInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const [search, setSearch] = useState("");
  const [teamFilter, setTeamFilter] = useState("");
  const [page, setPage] = useState(1);
  const limit = 50;

  const debounceRef = useRef<NodeJS.Timeout>();

  const fetchSwimmers = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const res = await listSwimmers({
        page,
        limit,
        search: search || undefined,
        team: teamFilter || undefined,
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
  }, [page, search, teamFilter]);

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
      {/* Page Header */}
      <div className="bg-white border-b border-gray-200">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
          <nav className="flex items-center gap-2 text-sm mb-4">
            <a href="/" className="text-gray-500 hover:text-ssa-navy transition-colors">Dashboard</a>
            <svg className="w-4 h-4 text-gray-300" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M8.25 4.5l7.5 7.5-7.5 7.5" />
            </svg>
            <span className="text-ssa-navy font-medium">Swimmers</span>
          </nav>
          <h1 className="text-2xl font-bold text-ssa-navy">Swimmers</h1>
          <p className="text-gray-500 text-sm mt-1">
            Browse and search all registered swimmers
          </p>
        </div>
      </div>

      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Search & Filters */}
        <div className="card p-4 mb-6">
          <div className="flex flex-col sm:flex-row gap-3">
            <div className="relative flex-1">
              <svg className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
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
            <input
              type="text"
              placeholder="Filter by team..."
              value={teamFilter}
              onChange={(e) => { setTeamFilter(e.target.value); setPage(1); }}
              className="px-4 py-2.5 bg-gray-50 border border-gray-200 rounded-lg text-sm text-gray-600
                         focus:outline-none focus:ring-2 focus:ring-ssa-teal/20 focus:border-ssa-teal
                         placeholder:text-gray-400 transition-colors min-w-[200px]"
            />
          </div>
        </div>

        {/* Summary */}
        <div className="flex items-center justify-between mb-4">
          <p className="text-sm text-gray-600">
            {totalResults > 0 ? (
              <>
                Showing <span className="font-semibold text-ssa-navy">{showingFrom}&ndash;{showingTo}</span> of{" "}
                <span className="font-semibold text-ssa-navy">{totalResults.toLocaleString()}</span> swimmers
              </>
            ) : loading ? "Loading..." : "No swimmers found"}
          </p>
        </div>

        {/* Error */}
        {error && (
          <div className="card p-8 text-center mb-6">
            <p className="text-red-600 font-medium">{error}</p>
          </div>
        )}

        {/* Swimmers Table */}
        {!error && (
          <div className="card overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr className="bg-ssa-navy">
                    <th className="px-6 py-3.5 text-left text-xs font-semibold text-gray-300 uppercase tracking-wider">Name</th>
                    <th className="px-6 py-3.5 text-center text-xs font-semibold text-gray-300 uppercase tracking-wider w-16">Age</th>
                    <th className="px-6 py-3.5 text-left text-xs font-semibold text-gray-300 uppercase tracking-wider">Team</th>
                    <th className="px-6 py-3.5 text-center text-xs font-semibold text-gray-300 uppercase tracking-wider w-20">Meets</th>
                    <th className="px-6 py-3.5 text-center text-xs font-semibold text-gray-300 uppercase tracking-wider w-20">Results</th>
                    <th className="px-6 py-3.5 text-right text-xs font-semibold text-gray-300 uppercase tracking-wider w-28 hidden sm:table-cell">Latest Meet</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {loading
                    ? Array.from({ length: 10 }).map((_, i) => (
                        <tr key={i} className="animate-pulse">
                          <td className="px-6 py-4"><div className="h-4 bg-gray-200 rounded w-40" /></td>
                          <td className="px-6 py-4"><div className="h-4 bg-gray-200 rounded w-8 mx-auto" /></td>
                          <td className="px-6 py-4"><div className="h-4 bg-gray-200 rounded w-48" /></td>
                          <td className="px-6 py-4"><div className="h-4 bg-gray-200 rounded w-8 mx-auto" /></td>
                          <td className="px-6 py-4"><div className="h-4 bg-gray-200 rounded w-8 mx-auto" /></td>
                          <td className="px-6 py-4 hidden sm:table-cell"><div className="h-4 bg-gray-200 rounded w-24 ml-auto" /></td>
                        </tr>
                      ))
                    : swimmers.map((s, i) => (
                        <tr key={s.id} className={`${i % 2 === 0 ? "bg-white" : "bg-gray-50/50"} hover:bg-ssa-teal/5 transition-colors`}>
                          <td className="px-6 py-4">
                            <a href={`/swimmers/${s.id}`} className="text-sm font-semibold text-ssa-navy hover:text-ssa-teal transition-colors">
                              {displayName(s.name)}
                            </a>
                          </td>
                          <td className="px-6 py-4 text-center">
                            <span className="text-sm text-gray-600">{s.age ?? "-"}</span>
                          </td>
                          <td className="px-6 py-4">
                            <span className="text-sm text-gray-600">{s.team ?? "-"}</span>
                          </td>
                          <td className="px-6 py-4 text-center">
                            <span className="text-sm font-medium text-gray-700">{s.meet_count}</span>
                          </td>
                          <td className="px-6 py-4 text-center">
                            <span className="text-sm font-medium text-gray-700">{s.result_count}</span>
                          </td>
                          <td className="px-6 py-4 text-right hidden sm:table-cell">
                            <span className="text-xs text-gray-400">{s.latest_meet}</span>
                          </td>
                        </tr>
                      ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* Pagination */}
        {!error && totalPages > 1 && (
          <div className="mt-4 flex flex-col sm:flex-row items-center justify-between gap-4 text-sm">
            <p className="text-gray-500">
              Showing {showingFrom}&ndash;{showingTo} of <span className="font-medium text-gray-700">{totalResults.toLocaleString()} swimmers</span>
            </p>
            <div className="flex items-center gap-2">
              <button
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={page <= 1}
                className={`px-3 py-1.5 text-sm bg-white border border-gray-200 rounded-md transition-colors ${page <= 1 ? "text-gray-400 cursor-not-allowed" : "text-gray-700 hover:bg-gray-50"}`}
              >
                Previous
              </button>
              {Array.from({ length: Math.min(5, totalPages) }).map((_, i) => {
                let pageNum: number;
                if (totalPages <= 5) pageNum = i + 1;
                else if (page <= 3) pageNum = i + 1;
                else if (page >= totalPages - 2) pageNum = totalPages - 4 + i;
                else pageNum = page - 2 + i;
                return (
                  <button
                    key={pageNum}
                    onClick={() => setPage(pageNum)}
                    className={`px-3 py-1.5 text-sm rounded-md transition-colors ${pageNum === page ? "font-medium text-white bg-ssa-navy" : "text-gray-700 bg-white border border-gray-200 hover:bg-gray-50"}`}
                  >
                    {pageNum}
                  </button>
                );
              })}
              <button
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                disabled={page >= totalPages}
                className={`px-3 py-1.5 text-sm bg-white border border-gray-200 rounded-md transition-colors ${page >= totalPages ? "text-gray-400 cursor-not-allowed" : "text-gray-700 hover:bg-gray-50"}`}
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
