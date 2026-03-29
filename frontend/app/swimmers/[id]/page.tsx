"use client";

import React, { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import {
  getSwimmer,
  getResult,
  getSwimmerRelays,
  type SwimmerDetail,
  type ResultDetail,
  type RelayResultBrief,
} from "@/lib/api";

export default function SwimmerProfilePage() {
  const params = useParams();
  const swimmerId = Number(params.id);

  const [swimmer, setSwimmer] = useState<SwimmerDetail | null>(null);
  const [relays, setRelays] = useState<RelayResultBrief[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  // Splits drill-down with cache
  const [expandedResult, setExpandedResult] = useState<number | null>(null);
  const [expandedRelay, setExpandedRelay] = useState<number | null>(null);
  const [splitsCache, setSplitsCache] = useState<Record<number, ResultDetail>>({});
  const [loadingSplits, setLoadingSplits] = useState(false);

  useEffect(() => {
    if (!swimmerId) return;
    setLoading(true);
    Promise.all([
      getSwimmer(swimmerId),
      getSwimmerRelays(swimmerId),
    ])
      .then(([s, r]) => {
        setSwimmer(s);
        setRelays(r.data);
      })
      .catch((e) => setError(e.message || "Failed to load swimmer"))
      .finally(() => setLoading(false));
  }, [swimmerId]);

  async function handleToggleSplits(resultId: number) {
    if (expandedResult === resultId) {
      setExpandedResult(null);
      return;
    }
    setExpandedResult(resultId);
    if (splitsCache[resultId]) return;
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
                    <th className="px-6 py-3 text-left text-xs font-semibold text-gray-300 uppercase tracking-wider">Event</th>
                    <th className="px-6 py-3 text-right text-xs font-semibold text-gray-300 uppercase tracking-wider w-28">Best Time</th>
                    <th className="px-6 py-3 text-left text-xs font-semibold text-gray-300 uppercase tracking-wider hidden sm:table-cell">Meet</th>
                    <th className="px-6 py-3 text-right text-xs font-semibold text-gray-300 uppercase tracking-wider w-28 hidden md:table-cell">Date</th>
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

        {/* Competition History — merged individual + relay, grouped by meet */}
        <section>
          <h2 className="text-lg font-semibold text-ssa-navy mb-4">Competition History</h2>
          {swimmer.recent_results.length === 0 && relays.length === 0 ? (
            <div className="card p-6 text-center text-gray-400 text-sm">No results yet</div>
          ) : (() => {
            // Group by meet
            type MeetGroup = { meetId: number; meetName: string; items: Array<{ type: "individual"; data: typeof swimmer.recent_results[0] } | { type: "relay"; data: RelayResultBrief }> };
            const meetMap = new Map<number, MeetGroup>();
            for (const r of swimmer.recent_results) {
              const mid = r.meet.id;
              if (!meetMap.has(mid)) meetMap.set(mid, { meetId: mid, meetName: r.meet.name, items: [] });
              meetMap.get(mid)!.items.push({ type: "individual", data: r });
            }
            for (const rr of relays) {
              const mid = rr.meet.id;
              if (!meetMap.has(mid)) meetMap.set(mid, { meetId: mid, meetName: rr.meet.name, items: [] });
              meetMap.get(mid)!.items.push({ type: "relay", data: rr });
            }
            const meetGroups = Array.from(meetMap.values());

            return meetGroups.map((mg) => (
              <div key={mg.meetId} className="card overflow-hidden mb-4">
                <div className="px-6 py-3 bg-gray-50 border-b border-gray-200">
                  <h3 className="text-sm font-semibold text-ssa-navy">{mg.meetName}</h3>
                </div>
                <table className="w-full">
                  <thead>
                    <tr className="bg-ssa-navy">
                      <th className="px-6 py-2.5 text-left text-xs font-semibold text-gray-300 uppercase">Event</th>
                      <th className="px-6 py-2.5 text-right text-xs font-semibold text-gray-300 uppercase w-28">Time</th>
                      <th className="px-6 py-2.5 text-center text-xs font-semibold text-gray-300 uppercase w-20 hidden sm:table-cell">Round</th>
                      <th className="px-6 py-2.5 text-center text-xs font-semibold text-gray-300 uppercase w-20">Place</th>
                      <th className="px-6 py-2.5 text-center text-xs font-semibold text-gray-300 uppercase w-24">Status</th>
                      <th className="px-6 py-2.5 text-center text-xs font-semibold text-gray-300 uppercase w-16">Details</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100">
                    {mg.items.map((item, index) => {
                      if (item.type === "individual") {
                        const r = item.data;
                        const isExpanded = expandedResult === r.id;
                        return (
                          <React.Fragment key={`ind-${r.id}`}>
                            <tr className={`${index % 2 === 0 ? "bg-white" : "bg-gray-50/50"} ${r.is_dq ? "bg-red-50/60" : ""} hover:bg-ssa-teal/5 transition-colors`}>
                              <td className="px-6 py-3">
                                <span className="text-sm font-medium text-gray-700">{r.event}</span>
                              </td>
                              <td className="px-6 py-3 text-right">
                                {r.is_dq || !r.time ? <span className="text-sm text-gray-400">--</span> : <span className="text-sm font-mono font-bold text-ssa-navy">{r.time}</span>}
                              </td>
                              <td className="px-6 py-3 text-center hidden sm:table-cell">
                                <span className={`text-xs font-medium px-2 py-0.5 rounded ${r.round === "Final" ? "bg-ssa-navy/10 text-ssa-navy" : "bg-gray-100 text-gray-500"}`}>{r.round || "-"}</span>
                              </td>
                              <td className="px-6 py-3 text-center">
                                {r.is_dq || r.placement == null ? <span className="text-sm text-gray-400">--</span> : r.placement <= 3 ? (
                                  <span className={`inline-flex items-center justify-center w-6 h-6 rounded-full text-xs font-bold ${r.placement === 1 ? "bg-amber-100 text-amber-800" : r.placement === 2 ? "bg-gray-100 text-gray-600" : "bg-orange-50 text-orange-700"}`}>{r.placement}</span>
                                ) : <span className="text-sm text-gray-500">{r.placement}</span>}
                              </td>
                              <td className="px-6 py-3 text-center">
                                {r.is_dq ? <span className="text-xs font-semibold text-red-600 bg-red-100 px-2 py-0.5 rounded-full">DQ</span>
                                : r.qualifier ? <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${r.qualifier === "qMTS" ? "bg-ssa-teal/10 text-ssa-teal" : "bg-blue-50 text-blue-700"}`}>{r.qualifier}</span>
                                : null}
                              </td>
                              <td className="px-6 py-3 text-center">
                                <button onClick={() => handleToggleSplits(r.id)} className="text-ssa-teal hover:text-ssa-navy transition-colors">
                                  <svg className={`w-5 h-5 transition-transform ${isExpanded ? "rotate-180" : ""}`} fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
                                    <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 8.25l-7.5 7.5-7.5-7.5" />
                                  </svg>
                                </button>
                              </td>
                            </tr>
                            {isExpanded && (
                              <tr className="bg-ssa-navy/5">
                                <td colSpan={6} className="px-6 py-3">
                                  {loadingSplits ? <div className="text-xs text-gray-400 animate-pulse">Loading splits...</div>
                                  : splitsCache[r.id]?.splits ? (
                                    <div className="flex flex-wrap gap-2 items-center">
                                      <span className="text-xs font-semibold text-ssa-navy uppercase mr-2">Splits:</span>
                                      {(() => { try { const splits: {cumulative:string;split:string|null;distance:number}[] = JSON.parse(splitsCache[r.id].splits!); return splits.map((s,i) => (
                                        <div key={i} className="text-center bg-white rounded px-2 py-1 border border-gray-200">
                                          <div className="text-[10px] text-gray-400">{s.distance}m</div>
                                          <div className="text-xs font-mono font-semibold text-ssa-navy">{s.cumulative}</div>
                                          {s.split && <div className="text-[10px] font-mono text-gray-500">({s.split})</div>}
                                        </div>
                                      )); } catch { return null; } })()}
                                      {splitsCache[r.id].reaction_time && (
                                        <div className="text-center bg-white rounded px-2 py-1 border border-gray-200 ml-2">
                                          <div className="text-[10px] text-gray-400">RT</div>
                                          <div className="text-xs font-mono font-semibold text-gray-600">{splitsCache[r.id].reaction_time}</div>
                                        </div>
                                      )}
                                    </div>
                                  ) : <div className="text-xs text-gray-400">No split data available</div>}
                                </td>
                              </tr>
                            )}
                          </React.Fragment>
                        );
                      } else {
                        const rr = item.data;
                        const isOpen = expandedRelay === rr.id;
                        const myLeg = rr.legs.find((l) => l.swimmer.id === swimmerId);
                        return (
                          <React.Fragment key={`relay-${rr.id}`}>
                            <tr className={`${index % 2 === 0 ? "bg-white" : "bg-gray-50/50"} ${rr.is_dq ? "bg-red-50/60" : ""} hover:bg-ssa-teal/5 transition-colors`}>
                              <td className="px-6 py-3">
                                <div>
                                  <span className="text-sm font-medium text-gray-700">{rr.event}</span>
                                  <div className="text-xs text-gray-400">{rr.team_name} {rr.relay_letter}</div>
                                </div>
                              </td>
                              <td className="px-6 py-3 text-right">
                                {rr.is_dq ? <span className="text-sm text-gray-400">DQ</span> : (
                                  <div>
                                    <span className="text-sm font-mono font-bold text-ssa-navy">{rr.time || "--"}</span>
                                    {myLeg?.split_time && <div className="text-xs font-mono text-gray-400">Leg: {myLeg.split_time}</div>}
                                  </div>
                                )}
                              </td>
                              <td className="px-6 py-3 text-center hidden sm:table-cell">
                                <span className={`text-xs font-medium px-2 py-0.5 rounded ${rr.round === "Final" ? "bg-ssa-navy/10 text-ssa-navy" : "bg-gray-100 text-gray-500"}`}>{rr.round || "-"}</span>
                              </td>
                              <td className="px-6 py-3 text-center">
                                {rr.placement ? (rr.placement <= 3 ? (
                                  <span className={`inline-flex items-center justify-center w-6 h-6 rounded-full text-xs font-bold ${rr.placement === 1 ? "bg-amber-100 text-amber-800" : rr.placement === 2 ? "bg-gray-100 text-gray-600" : "bg-orange-50 text-orange-700"}`}>{rr.placement}</span>
                                ) : <span className="text-sm text-gray-500">{rr.placement}</span>) : <span className="text-sm text-gray-400">--</span>}
                              </td>
                              <td className="px-6 py-3 text-center">
                                <span className="text-xs font-medium px-2 py-0.5 rounded bg-purple-50 text-purple-700">Relay</span>
                              </td>
                              <td className="px-6 py-3 text-center">
                                <button onClick={() => setExpandedRelay(isOpen ? null : rr.id)} className="text-ssa-teal hover:text-ssa-navy transition-colors">
                                  <svg className={`w-5 h-5 transition-transform ${isOpen ? "rotate-180" : ""}`} fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
                                    <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 8.25l-7.5 7.5-7.5-7.5" />
                                  </svg>
                                </button>
                              </td>
                            </tr>
                            {isOpen && (
                              <tr className="bg-ssa-navy/5">
                                <td colSpan={6} className="px-6 py-3">
                                  <div className="flex flex-wrap gap-3">
                                    {[...rr.legs].sort((a, b) => a.leg_number - b.leg_number).map((leg) => {
                                      const isMe = leg.swimmer.id === swimmerId;
                                      let legSplits: {cumulative:string;split:string|null;distance:number}[] = [];
                                      if (leg.splits) { try { legSplits = JSON.parse(leg.splits); } catch {} }
                                      return (
                                        <div key={leg.leg_number} className={`rounded-lg px-4 py-3 border min-w-[140px] ${isMe ? "bg-ssa-teal/10 border-ssa-teal/30 ring-1 ring-ssa-teal/20" : "bg-white border-gray-200"}`}>
                                          <div className="text-[10px] text-gray-400 uppercase text-center">Leg {leg.leg_number}</div>
                                          <div className={`text-sm font-semibold text-center ${isMe ? "text-ssa-teal" : "text-gray-700"}`}>{leg.swimmer.name.replace(", ", " ")}</div>
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
                      }
                    })}
                  </tbody>
                </table>
              </div>
            ));
          })()}
        </section>
      </div>
    </div>
  );
}
