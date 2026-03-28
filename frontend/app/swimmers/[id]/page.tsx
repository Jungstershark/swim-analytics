"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { getSwimmer, type SwimmerDetail } from "@/lib/api";

export default function SwimmerProfilePage() {
  const params = useParams();
  const swimmerId = Number(params.id);

  const [swimmer, setSwimmer] = useState<SwimmerDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [expandedResult, setExpandedResult] = useState<number | null>(null);

  useEffect(() => {
    if (!swimmerId) return;
    setLoading(true);
    getSwimmer(swimmerId)
      .then(setSwimmer)
      .catch((e) => setError(e.message || "Failed to load swimmer"))
      .finally(() => setLoading(false));
  }, [swimmerId]);

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

  if (error || !swimmer) {
    return (
      <div className="min-h-screen">
        <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-12 text-center">
          <p className="text-red-600 font-medium">{error || "Swimmer not found"}</p>
          <a href="/results" className="text-sm text-ssa-teal mt-4 inline-block hover:underline">
            &larr; Back to results
          </a>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen">
      {/* Header */}
      <div className="bg-white border-b border-gray-200">
        <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
          <nav className="flex items-center gap-2 text-sm mb-4">
            <a href="/" className="text-gray-500 hover:text-ssa-navy transition-colors">
              Dashboard
            </a>
            <svg className="w-4 h-4 text-gray-300" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M8.25 4.5l7.5 7.5-7.5 7.5" />
            </svg>
            <a href="/results" className="text-gray-500 hover:text-ssa-navy transition-colors">
              Results
            </a>
            <svg className="w-4 h-4 text-gray-300" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M8.25 4.5l7.5 7.5-7.5 7.5" />
            </svg>
            <span className="text-ssa-navy font-medium">{swimmer.name}</span>
          </nav>

          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
            <div>
              <h1 className="text-2xl font-bold text-ssa-navy">{swimmer.name}</h1>
              <div className="flex items-center gap-3 mt-1 text-sm text-gray-500">
                {swimmer.age && <span>Age {swimmer.age}</span>}
                {swimmer.team && (
                  <>
                    <span className="text-gray-300">&middot;</span>
                    <span>{swimmer.team}</span>
                  </>
                )}
              </div>
            </div>

            {/* Stats pills */}
            <div className="flex gap-3">
              <div className="bg-ssa-navy/5 rounded-lg px-4 py-2 text-center">
                <div className="text-lg font-bold text-ssa-navy">{swimmer.stats.total_meets}</div>
                <div className="text-xs text-gray-500">Meets</div>
              </div>
              <div className="bg-ssa-navy/5 rounded-lg px-4 py-2 text-center">
                <div className="text-lg font-bold text-ssa-navy">{swimmer.stats.total_results}</div>
                <div className="text-xs text-gray-500">Swims</div>
              </div>
              {swimmer.stats.total_dqs > 0 && (
                <div className="bg-red-50 rounded-lg px-4 py-2 text-center">
                  <div className="text-lg font-bold text-red-600">{swimmer.stats.total_dqs}</div>
                  <div className="text-xs text-gray-500">DQs</div>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>

      <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-8">
        {/* Personal Bests */}
        {swimmer.personal_bests.length > 0 && (
          <section>
            <h2 className="text-lg font-semibold text-ssa-navy mb-4">Personal Bests</h2>
            <div className="card overflow-hidden">
              <table className="w-full">
                <thead>
                  <tr className="bg-ssa-navy">
                    <th className="px-6 py-3 text-left text-xs font-semibold text-gray-300 uppercase tracking-wider">
                      Event
                    </th>
                    <th className="px-6 py-3 text-right text-xs font-semibold text-gray-300 uppercase tracking-wider w-28">
                      Best Time
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-semibold text-gray-300 uppercase tracking-wider hidden sm:table-cell">
                      Meet
                    </th>
                    <th className="px-6 py-3 text-right text-xs font-semibold text-gray-300 uppercase tracking-wider w-28 hidden md:table-cell">
                      Date
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {swimmer.personal_bests.map((pb) => (
                    <tr key={pb.event} className="hover:bg-ssa-teal/5 transition-colors">
                      <td className="px-6 py-3">
                        <span className="text-sm font-medium text-gray-700">{pb.event}</span>
                      </td>
                      <td className="px-6 py-3 text-right">
                        <span className="text-sm font-mono font-bold text-ssa-navy">{pb.time}</span>
                      </td>
                      <td className="px-6 py-3 hidden sm:table-cell">
                        <span className="text-sm text-gray-500">{pb.meet}</span>
                      </td>
                      <td className="px-6 py-3 text-right hidden md:table-cell">
                        <span className="text-xs text-gray-400">{pb.date}</span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        )}

        {/* Recent Results */}
        {swimmer.recent_results.length > 0 && (
          <section>
            <h2 className="text-lg font-semibold text-ssa-navy mb-4">Competition History</h2>
            <div className="card overflow-hidden">
              <table className="w-full">
                <thead>
                  <tr className="bg-ssa-navy">
                    <th className="px-6 py-3 text-left text-xs font-semibold text-gray-300 uppercase tracking-wider">
                      Event
                    </th>
                    <th className="px-6 py-3 text-right text-xs font-semibold text-gray-300 uppercase tracking-wider w-28">
                      Time
                    </th>
                    <th className="px-6 py-3 text-center text-xs font-semibold text-gray-300 uppercase tracking-wider w-20">
                      Place
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-semibold text-gray-300 uppercase tracking-wider hidden md:table-cell">
                      Meet
                    </th>
                    <th className="px-6 py-3 text-center text-xs font-semibold text-gray-300 uppercase tracking-wider w-20 hidden lg:table-cell">
                      Round
                    </th>
                    <th className="px-6 py-3 text-center text-xs font-semibold text-gray-300 uppercase tracking-wider w-16">
                      Splits
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {swimmer.recent_results.map((r, index) => {
                    const hasSplits = r.splits && r.splits !== "[]";
                    const isExpanded = expandedResult === r.id;
                    let parsedSplits: { cumulative: string; split: string | null; distance: number }[] = [];
                    if (hasSplits) {
                      try { parsedSplits = JSON.parse(r.splits!); } catch {}
                    }

                    return (
                      <>
                        <tr
                          key={r.id}
                          className={`
                            ${index % 2 === 0 ? "bg-white" : "bg-gray-50/50"}
                            ${r.is_dq ? "bg-red-50/60" : ""}
                            hover:bg-ssa-teal/5 transition-colors
                          `}
                        >
                          <td className="px-6 py-3">
                            <span className="text-sm font-medium text-gray-700">{r.event}</span>
                          </td>
                          <td className="px-6 py-3 text-right">
                            {r.is_dq ? (
                              <span className="text-xs font-semibold text-red-600 bg-red-100 px-2 py-0.5 rounded-full"
                                    title={r.dq_code ? `${r.dq_code}: ${r.dq_description}` : "DQ"}>
                                DQ
                              </span>
                            ) : r.time ? (
                              <span className="text-sm font-mono font-bold text-ssa-navy">{r.time}</span>
                            ) : (
                              <span className="text-sm text-gray-400">--</span>
                            )}
                          </td>
                          <td className="px-6 py-3 text-center">
                            {r.placement && !r.is_dq ? (
                              r.placement <= 3 ? (
                                <span className={`
                                  inline-flex items-center justify-center w-6 h-6 rounded-full text-xs font-bold
                                  ${r.placement === 1 ? "bg-amber-100 text-amber-800" : ""}
                                  ${r.placement === 2 ? "bg-gray-100 text-gray-600" : ""}
                                  ${r.placement === 3 ? "bg-orange-50 text-orange-700" : ""}
                                `}>
                                  {r.placement}
                                </span>
                              ) : (
                                <span className="text-sm text-gray-500">{r.placement}</span>
                              )
                            ) : (
                              <span className="text-sm text-gray-400">--</span>
                            )}
                          </td>
                          <td className="px-6 py-3 hidden md:table-cell">
                            <span className="text-sm text-gray-500">{r.meet?.name}</span>
                          </td>
                          <td className="px-6 py-3 text-center hidden lg:table-cell">
                            <span className={`text-xs font-medium px-2 py-0.5 rounded ${
                              r.round === "Final"
                                ? "bg-ssa-navy/10 text-ssa-navy"
                                : "bg-gray-100 text-gray-500"
                            }`}>
                              {r.round || "-"}
                            </span>
                          </td>
                          <td className="px-6 py-3 text-center">
                            {hasSplits ? (
                              <button
                                onClick={() => setExpandedResult(isExpanded ? null : r.id)}
                                className="text-ssa-teal hover:text-ssa-navy transition-colors"
                              >
                                <svg className={`w-5 h-5 transition-transform ${isExpanded ? "rotate-180" : ""}`} fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
                                  <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 8.25l-7.5 7.5-7.5-7.5" />
                                </svg>
                              </button>
                            ) : (
                              <span className="text-gray-300">-</span>
                            )}
                          </td>
                        </tr>

                        {isExpanded && hasSplits && (
                          <tr key={`${r.id}-splits`} className="bg-ssa-navy/5">
                            <td colSpan={6} className="px-6 py-3">
                              <div className="flex flex-wrap gap-2 items-center">
                                <span className="text-xs font-semibold text-ssa-navy uppercase mr-2">Splits:</span>
                                {parsedSplits.map((s, i) => (
                                  <div key={i} className="text-center bg-white rounded px-2 py-1 border border-gray-200">
                                    <div className="text-[10px] text-gray-400">{s.distance}m</div>
                                    <div className="text-xs font-mono font-semibold text-ssa-navy">{s.cumulative}</div>
                                    {s.split && (
                                      <div className="text-[10px] font-mono text-gray-500">({s.split})</div>
                                    )}
                                  </div>
                                ))}
                                {r.reaction_time && (
                                  <div className="text-center bg-white rounded px-2 py-1 border border-gray-200 ml-2">
                                    <div className="text-[10px] text-gray-400">RT</div>
                                    <div className="text-xs font-mono font-semibold text-gray-600">{r.reaction_time}</div>
                                  </div>
                                )}
                              </div>
                            </td>
                          </tr>
                        )}
                      </>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </section>
        )}
      </div>
    </div>
  );
}
