"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams, useSearchParams } from "next/navigation";
import {
  displayName,
  resultDisplayValue,
  getBrowserEvent,
  type BrowserEventDetail,
  type BrowserEventRow,
} from "@/lib/api";

export default function MeetEventPage() {
  const params = useParams();
  const searchParams = useSearchParams();
  const meetId = Number(params.id);
  const eventKey = String(params.eventKey || "");
  const [detail, setDetail] = useState<BrowserEventDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const page = Number(searchParams.get("page") || "1");
  const limit = Math.min(Number(searchParams.get("limit") || "50"), 200);
  const round = searchParams.get("round") || undefined;
  const rowType = (searchParams.get("row_type") || "all") as "all" | "individual" | "relay";
  const order = (searchParams.get("order") || "place") as "place" | "time" | "name";

  const fetchEvent = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const res = await getBrowserEvent({ meet_id: meetId, event_key: eventKey, page, limit, round, row_type: rowType, order });
      setDetail(res);
    } catch (e: any) {
      setError(e.message || "Failed to load event");
    } finally {
      setLoading(false);
    }
  }, [meetId, eventKey, page, limit, round, rowType, order]);

  useEffect(() => {
    if (meetId && eventKey) fetchEvent();
  }, [fetchEvent, meetId, eventKey]);

  const rounds = detail?.event_group?.rounds ?? [];
  const totalPages = detail?.pagination.total_pages ?? 0;

  function hrefFor(next: Partial<{ page: number; round: string | null; row_type: string; order: string }>) {
    const q = new URLSearchParams(searchParams.toString());
    if (next.page !== undefined) q.set("page", String(next.page));
    if (next.round !== undefined) {
      if (next.round) q.set("round", next.round);
      else q.delete("round");
      q.set("page", "1");
    }
    if (next.row_type) { q.set("row_type", next.row_type); q.set("page", "1"); }
    if (next.order) { q.set("order", next.order); q.set("page", "1"); }
    const qs = q.toString();
    return `/meets/${meetId}/events/${eventKey}${qs ? `?${qs}` : ""}`;
  }

  return (
    <div className="min-h-screen">
      <div className="bg-white border-b border-gray-200">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
          <nav aria-label="Breadcrumb" className="flex min-w-0 items-center gap-2 text-sm mb-4">
            <a href="/" className="shrink-0 text-gray-500 hover:text-ssa-navy transition-colors">Home</a>
            <span className="text-gray-300">/</span>
            <a href="/meets" className="shrink-0 text-gray-500 hover:text-ssa-navy transition-colors">Meets</a>
            <span className="text-gray-300">/</span>
            <a href={`/meets/${meetId}`} className="shrink-0 text-gray-500 hover:text-ssa-navy transition-colors">Meet</a>
            <span className="text-gray-300">/</span>
            <span className="truncate text-ssa-navy font-medium" aria-current="page">Event</span>
          </nav>
          <h1 className="text-2xl font-bold text-ssa-navy">
            {loading ? "Loading event..." : detail?.event_group?.event_label || "Event not found"}
          </h1>
          {detail?.event_group && (
            <p className="text-sm text-gray-500 mt-1">
              {detail.event_group.source_event_number ? `Event ${detail.event_group.source_event_number} · ` : ""}
              {detail.event_group.total_rows.toLocaleString()} results
            </p>
          )}
        </div>
      </div>

      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {error ? (
          <StateCard message={error} tone="error" backHref={`/meets/${meetId}`} />
        ) : loading ? (
          <div className="card p-8 animate-pulse text-gray-400">Loading results...</div>
        ) : !detail?.event_group ? (
          <StateCard message="This event was not found for the meet." backHref={`/meets/${meetId}`} />
        ) : (
          <>
            <div className="card p-4 mb-6">
              <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-3">
                <div className="flex flex-wrap gap-2">
                  <FilterPill href={hrefFor({ round: null })} active={!round}>All rounds</FilterPill>
                  {rounds.map((r) => <FilterPill key={r} href={hrefFor({ round: r })} active={round === r}>{r}</FilterPill>)}
                </div>
                <div className="flex flex-wrap gap-2">
                  {(["all", "individual", "relay"] as const).map((type) => <FilterPill key={type} href={hrefFor({ row_type: type })} active={rowType === type}>{type}</FilterPill>)}
                  {(["place", "time", "name"] as const).map((o) => <FilterPill key={o} href={hrefFor({ order: o })} active={order === o}>Sort: {o}</FilterPill>)}
                </div>
              </div>
            </div>

            <div className="card overflow-hidden">
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead>
                    <tr className="bg-ssa-navy">
                      <th scope="col" className="px-4 py-3 text-left text-xs font-semibold text-gray-300 uppercase">Entry</th>
                      <th scope="col" className="px-4 py-3 text-center text-xs font-semibold text-gray-300 uppercase w-20">Round</th>
                      <th scope="col" className="px-4 py-3 text-center text-xs font-semibold text-gray-300 uppercase w-20">Place</th>
                      <th scope="col" className="px-4 py-3 text-right text-xs font-semibold text-gray-300 uppercase w-24">Time</th>
                      <th scope="col" className="px-4 py-3 text-center text-xs font-semibold text-gray-300 uppercase w-32">Source</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100">
                    {detail.data.map((row, index) => <ResultRow key={`${row.row_type}-${row.id}`} row={row} index={index} meetId={meetId} />)}
                  </tbody>
                </table>
              </div>
              {detail.data.length === 0 && <div className="p-8 text-center text-gray-400 text-sm">No results match these filters.</div>}
            </div>

            {totalPages > 1 && (
              <div className="mt-6 flex items-center justify-between text-sm">
                <a className={`px-3 py-1.5 bg-white border border-gray-200 rounded-md ${page <= 1 ? "pointer-events-none text-gray-400" : "text-gray-700 hover:bg-gray-50"}`} href={hrefFor({ page: Math.max(1, page - 1) })}>Previous</a>
                <span className="text-gray-500">Page {page} of {totalPages}</span>
                <a className={`px-3 py-1.5 bg-white border border-gray-200 rounded-md ${page >= totalPages ? "pointer-events-none text-gray-400" : "text-gray-700 hover:bg-gray-50"}`} href={hrefFor({ page: Math.min(totalPages, page + 1) })}>Next</a>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function ResultRow({ row, index, meetId }: { row: BrowserEventRow; index: number; meetId: number }) {
  const hasWarnings = row.warnings.length > 0;
  const resultsHref = `/results?meet_id=${meetId}&event=${encodeURIComponent(row.event_label)}&row_type=${row.row_type}`;
  return (
    <tr className={`${index % 2 === 0 ? "bg-white" : "bg-gray-50/50"} ${hasWarnings ? "bg-amber-50/40" : ""} hover:bg-ssa-teal/5 transition-colors`}>
      <td className="px-4 py-3">
        {row.row_type === "individual" ? (
          <div>
            {row.swimmer ? <a href={`/swimmers/${row.swimmer.id}`} className="text-sm font-semibold text-ssa-navy hover:text-ssa-teal">{displayName(row.swimmer.name)}</a> : <span className="text-sm text-gray-500">Unknown swimmer</span>}
            <div className="text-xs text-gray-400">{row.swimmer?.team || "No team"}{row.is_guest ? " · Guest" : ""}</div>
          </div>
        ) : (
          <div>
            <div className="text-sm font-semibold text-ssa-navy">{row.team_name} {row.relay_letter}</div>
            <div className="text-xs text-gray-400">Relay · {row.legs.map((l) => l.swimmer_name).join(", ")}</div>
          </div>
        )}
        {hasWarnings && <div className="mt-1 text-xs text-amber-700">{row.warnings.length} data warning{row.warnings.length === 1 ? "" : "s"}</div>}
      </td>
      <td className="px-4 py-3 text-center"><span className="text-xs bg-gray-100 text-gray-600 px-2 py-0.5 rounded">{row.round || "-"}</span></td>
      <td className="px-4 py-3 text-center text-sm text-gray-600">{row.placement ?? "--"}</td>
      <td className="px-4 py-3 text-right font-mono font-bold text-ssa-navy">{resultDisplayValue(row.status, row.time, row.is_dq)}</td>
      <td className="px-4 py-3 text-center">
        {row.source.document_sha256 ? <span className="text-xs text-emerald-700 bg-emerald-50 px-2 py-0.5 rounded">source linked</span> : <span className="text-xs text-amber-700 bg-amber-50 px-2 py-0.5 rounded">missing source</span>}
        <a href={resultsHref} className="mt-2 block min-h-11 text-xs font-semibold leading-[2.75rem] text-ssa-teal hover:text-ssa-navy">Open in Results</a>
      </td>
    </tr>
  );
}

function FilterPill({ href, active, children }: { href: string; active: boolean; children: React.ReactNode }) {
  return <a href={href} className={`px-3 py-1.5 rounded-full text-xs font-medium border transition-colors ${active ? "bg-ssa-navy text-white border-ssa-navy" : "bg-white text-gray-600 border-gray-200 hover:bg-gray-50"}`}>{children}</a>;
}

function StateCard({ message, backHref, tone = "default" }: { message: string; backHref: string; tone?: "default" | "error" }) {
  return (
    <div className="card p-8 text-center">
      <p className={`font-medium ${tone === "error" ? "text-red-600" : "text-gray-600"}`}>{message}</p>
      <a href={backHref} className="text-sm text-ssa-teal mt-4 inline-block hover:underline">&larr; Back to meet</a>
    </div>
  );
}
