"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { getMeet, displayName, type MeetDetail, type EventGroup } from "@/lib/api";

export default function MeetDetailPage() {
  const params = useParams();
  const meetId = Number(params.id);

  const [meet, setMeet] = useState<MeetDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [eventSearch, setEventSearch] = useState("");
  const [expandedEvent, setExpandedEvent] = useState<string | null>(null);

  useEffect(() => {
    if (!meetId) return;
    setLoading(true);
    getMeet(meetId)
      .then(setMeet)
      .catch((e) => setError(e.message || "Failed to load meet"))
      .finally(() => setLoading(false));
  }, [meetId]);

  if (loading) {
    return (
      <div className="min-h-screen">
        <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-12">
          <div className="animate-pulse space-y-6">
            <div className="h-8 bg-gray-200 rounded w-64" />
            <div className="h-4 bg-gray-200 rounded w-40" />
            <div className="h-64 bg-gray-200 rounded" />
          </div>
        </div>
      </div>
    );
  }

  if (error || !meet) {
    return (
      <div className="min-h-screen">
        <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-12 text-center">
          <p className="text-red-600 font-medium">{error || "Meet not found"}</p>
          <a href="/" className="text-sm text-ssa-teal mt-4 inline-block hover:underline">&larr; Back to dashboard</a>
        </div>
      </div>
    );
  }

  const totalResults = meet.events.reduce((sum, e) => sum + e.results.length, 0);
  const filteredEvents = meet.events.filter((e) =>
    !eventSearch || e.name.toLowerCase().includes(eventSearch.toLowerCase())
  );

  return (
    <div className="min-h-screen">
      {/* Header */}
      <div className="bg-white border-b border-gray-200">
        <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
          <nav className="flex items-center gap-2 text-sm mb-4">
            <a href="/" className="text-gray-500 hover:text-ssa-navy transition-colors">Dashboard</a>
            <svg className="w-4 h-4 text-gray-300" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M8.25 4.5l7.5 7.5-7.5 7.5" />
            </svg>
            <span className="text-ssa-navy font-medium">{meet.name}</span>
          </nav>

          <div className="flex flex-col sm:flex-row sm:items-end sm:justify-between gap-4">
            <div>
              <h1 className="text-2xl font-bold text-ssa-navy">{meet.name}</h1>
              <div className="flex items-center gap-3 mt-1 text-sm text-gray-500">
                <span>{new Date(meet.date).toLocaleDateString("en-SG", { day: "numeric", month: "long", year: "numeric" })}</span>
                {meet.location && (
                  <>
                    <span className="text-gray-300">&middot;</span>
                    <span>{meet.location}</span>
                  </>
                )}
              </div>
            </div>
            <div className="flex gap-3">
              <div className="bg-ssa-navy/5 rounded-lg px-4 py-2 text-center">
                <div className="text-lg font-bold text-ssa-navy">{meet.events.length}</div>
                <div className="text-xs text-gray-500">Events</div>
              </div>
              <div className="bg-ssa-navy/5 rounded-lg px-4 py-2 text-center">
                <div className="text-lg font-bold text-ssa-navy">{totalResults.toLocaleString()}</div>
                <div className="text-xs text-gray-500">Results</div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Event search */}
        <div className="card p-4 mb-6">
          <div className="relative">
            <svg className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" />
            </svg>
            <input
              type="text"
              placeholder="Search events..."
              value={eventSearch}
              onChange={(e) => setEventSearch(e.target.value)}
              className="w-full pl-10 pr-4 py-2.5 bg-gray-50 border border-gray-200 rounded-lg text-sm
                         focus:outline-none focus:ring-2 focus:ring-ssa-teal/20 focus:border-ssa-teal
                         placeholder:text-gray-400 transition-colors"
            />
          </div>
        </div>

        {/* Events list */}
        <div className="card overflow-hidden">
          <div className="divide-y divide-gray-100">
            {filteredEvents.length === 0 ? (
              <div className="p-6 text-center text-gray-400 text-sm">No events found</div>
            ) : (
              filteredEvents.map((eg) => {
                const isOpen = expandedEvent === eg.name;
                return (
                  <div key={eg.name}>
                    <button
                      onClick={() => setExpandedEvent(isOpen ? null : eg.name)}
                      className="w-full flex items-center justify-between px-6 py-4 hover:bg-ssa-teal/5 transition-colors text-left"
                    >
                      <div className="flex items-center gap-3">
                        <svg className={`w-4 h-4 text-gray-400 transition-transform ${isOpen ? "rotate-90" : ""}`} fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" d="M8.25 4.5l7.5 7.5-7.5 7.5" />
                        </svg>
                        <span className="text-sm font-medium text-gray-700">{eg.name}</span>
                      </div>
                      <div className="flex items-center gap-2">
                        {(() => {
                          const rounds = new Set(eg.results.map((r) => r.round).filter(Boolean));
                          return [...rounds].sort().reverse().map((rnd) => (
                            <span key={rnd} className={`text-xs font-medium px-2 py-0.5 rounded ${
                              rnd === "Final" ? "bg-ssa-navy/10 text-ssa-navy" : "bg-gray-100 text-gray-500"
                            }`}>{rnd}</span>
                          ));
                        })()}
                        <span className="text-xs text-gray-400">{eg.results.length} results</span>
                      </div>
                    </button>

                    {isOpen && (() => {
                      // Group results by round
                      const byRound: Record<string, typeof eg.results> = {};
                      for (const r of eg.results) {
                        const rnd = r.round || "Results";
                        if (!byRound[rnd]) byRound[rnd] = [];
                        byRound[rnd].push(r);
                      }
                      // Show Finals before Prelims
                      const roundOrder = ["Final", "Prelim", "Results"];
                      const sortedRounds = Object.keys(byRound).sort(
                        (a, b) => roundOrder.indexOf(a) - roundOrder.indexOf(b)
                      );

                      return (
                        <div className="bg-gray-50/50 border-t border-gray-100">
                          {sortedRounds.map((rnd) => (
                            <div key={rnd}>
                              {sortedRounds.length > 1 && (
                                <div className="px-6 py-2 bg-gray-100 border-b border-gray-200">
                                  <span className={`text-xs font-semibold uppercase tracking-wider ${
                                    rnd === "Final" ? "text-ssa-navy" : "text-gray-500"
                                  }`}>{rnd}</span>
                                </div>
                              )}
                              <div className="overflow-x-auto">
                                <table className="w-full">
                                  <thead>
                                    <tr className="bg-ssa-navy/80">
                                      <th className="px-4 py-2 text-center text-xs font-semibold text-gray-300 uppercase w-16">Place</th>
                                      <th className="px-4 py-2 text-left text-xs font-semibold text-gray-300 uppercase">Swimmer</th>
                                      <th className="px-4 py-2 text-center text-xs font-semibold text-gray-300 uppercase w-12">Age</th>
                                      <th className="px-4 py-2 text-left text-xs font-semibold text-gray-300 uppercase hidden md:table-cell">Team</th>
                                      <th className="px-4 py-2 text-right text-xs font-semibold text-gray-300 uppercase w-24">Time</th>
                                      <th className="px-4 py-2 text-center text-xs font-semibold text-gray-300 uppercase w-20">Status</th>
                                    </tr>
                                  </thead>
                                  <tbody className="divide-y divide-gray-100">
                                    {byRound[rnd].map((r, i) => (
                                      <tr key={r.id} className={`${i % 2 === 0 ? "bg-white" : "bg-gray-50/50"} ${r.is_dq ? "bg-red-50/60" : ""} hover:bg-ssa-teal/5 transition-colors`}>
                                        <td className="px-4 py-2 text-center">
                                          {r.is_dq || r.placement == null ? (
                                            <span className="text-sm text-gray-400">--</span>
                                          ) : r.placement <= 3 ? (
                                            <span className={`inline-flex items-center justify-center w-6 h-6 rounded-full text-xs font-bold
                                              ${r.placement === 1 ? "bg-amber-100 text-amber-800" : ""}
                                              ${r.placement === 2 ? "bg-gray-100 text-gray-600" : ""}
                                              ${r.placement === 3 ? "bg-orange-50 text-orange-700" : ""}
                                            `}>
                                              {r.placement}
                                            </span>
                                          ) : (
                                            <span className="text-sm text-gray-500">{r.placement}</span>
                                          )}
                                        </td>
                                        <td className="px-4 py-2">
                                          <a href={`/swimmers/${r.swimmer.id}`} className="text-sm font-semibold text-ssa-navy hover:text-ssa-teal transition-colors">
                                            {displayName(r.swimmer.name)}
                                          </a>
                                        </td>
                                        <td className="px-4 py-2 text-center text-sm text-gray-600">{r.swimmer.age ?? "-"}</td>
                                        <td className="px-4 py-2 text-sm text-gray-500 hidden md:table-cell">{r.swimmer.team}</td>
                                        <td className="px-4 py-2 text-right">
                                          {r.is_dq || !r.time ? (
                                            <span className="text-sm text-gray-400">--</span>
                                          ) : (
                                            <span className="text-sm font-mono font-bold text-ssa-navy">{r.time}</span>
                                          )}
                                        </td>
                                        <td className="px-4 py-2 text-center">
                                          {r.is_dq ? (
                                            <span className="text-xs font-semibold text-red-600 bg-red-100 px-2 py-0.5 rounded-full">DQ</span>
                                          ) : r.qualifier ? (
                                            <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${r.qualifier === "qMTS" ? "bg-ssa-teal/10 text-ssa-teal" : "bg-blue-50 text-blue-700"}`}>
                                              {r.qualifier}
                                            </span>
                                          ) : null}
                                        </td>
                                      </tr>
                                    ))}
                                  </tbody>
                                </table>
                              </div>
                            </div>
                          ))}
                        </div>
                      );
                    })()}
                  </div>
                );
              })
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
