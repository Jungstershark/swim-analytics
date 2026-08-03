"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import {
  displayName,
  getBrowserSwimmer,
  type BrowserSwimmerDetail,
  type BrowserIndividualRow,
  type BrowserRelayRow,
} from "@/lib/api";

export default function SwimmerProfilePage() {
  const params = useParams();
  const swimmerId = Number(params.id);
  const [detail, setDetail] = useState<BrowserSwimmerDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [openEvent, setOpenEvent] = useState<string | null>(null);

  useEffect(() => {
    if (!swimmerId) return;
    setLoading(true);
    setError("");
    getBrowserSwimmer(swimmerId)
      .then(setDetail)
      .catch((e) => setError(e.message || "Failed to load swimmer"))
      .finally(() => setLoading(false));
  }, [swimmerId]);

  if (loading) return <LoadingShell />;

  if (error || !detail) {
    return (
      <div className="min-h-screen">
        <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-12 text-center">
          <p className="text-red-600 font-medium">{error || "Swimmer not found"}</p>
          <a href="/swimmers" className="text-sm text-ssa-teal mt-4 inline-block hover:underline">&larr; Back to swimmers</a>
        </div>
      </div>
    );
  }

  const swimmer = detail.swimmer;

  return (
    <div className="min-h-screen">
      <div className="bg-white border-b border-gray-200">
        <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
          <nav className="flex items-center gap-2 text-sm mb-4">
            <a href="/" className="text-gray-500 hover:text-ssa-navy transition-colors">Dashboard</a>
            <span className="text-gray-300">/</span>
            <a href="/swimmers" className="text-gray-500 hover:text-ssa-navy transition-colors">Swimmers</a>
            <span className="text-gray-300">/</span>
            <span className="text-ssa-navy font-medium">{displayName(swimmer.name)}</span>
          </nav>

          <div className="flex flex-col lg:flex-row lg:items-end lg:justify-between gap-4">
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <h1 className="text-2xl font-bold text-ssa-navy">{displayName(swimmer.name)}</h1>
                {detail.stats.warning_count > 0 && <span className="text-xs font-semibold text-amber-800 bg-amber-100 px-2 py-0.5 rounded-full">{detail.stats.warning_count} data warning</span>}
              </div>
              <p className="text-gray-500 text-sm mt-1">
                {swimmer.team || "No team"}{swimmer.age ? ` · Age ${swimmer.age}` : ""}
              </p>
            </div>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              <Metric label="Swims" value={detail.stats.individual_result_count} />
              <Metric label="Relays" value={detail.stats.relay_result_count} />
              <Metric label="Meets" value={detail.stats.meet_count} />
              <Metric label="Events" value={detail.stats.event_count} />
            </div>
          </div>
        </div>
      </div>

      <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-8">
        {detail.warnings.length > 0 && (
          <section className="rounded-lg border border-amber-200 bg-amber-50 p-4">
            <h2 className="text-sm font-semibold text-amber-900 mb-2">Data-quality warnings</h2>
            <ul className="list-disc list-inside text-sm text-amber-800 space-y-1">
              {detail.warnings.map((warning, index) => <li key={index}>{warning.message}</li>)}
            </ul>
          </section>
        )}

        <section>
          <h2 className="text-lg font-semibold text-ssa-navy mb-4">Personal bests</h2>
          {detail.personal_bests.length === 0 ? (
            <div className="card p-6 text-sm text-gray-400 text-center">No PBs from parseable non-DQ individual times yet.</div>
          ) : (
            <div className="card overflow-hidden">
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead>
                    <tr className="bg-ssa-navy">
                      <th scope="col" className="px-4 py-3 text-left text-xs font-semibold text-gray-300 uppercase">Event</th>
                      <th scope="col" className="px-4 py-3 text-right text-xs font-semibold text-gray-300 uppercase w-28">Best</th>
                      <th scope="col" className="px-4 py-3 text-left text-xs font-semibold text-gray-300 uppercase hidden md:table-cell">Meet</th>
                      <th scope="col" className="px-4 py-3 text-right text-xs font-semibold text-gray-300 uppercase w-28">Date</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100">
                    {detail.personal_bests.map((pb) => (
                      <tr key={pb.event} className="hover:bg-ssa-teal/5">
                        <td className="px-4 py-3 text-sm font-medium text-gray-700">{pb.event}</td>
                        <td className="px-4 py-3 text-right font-mono font-bold text-ssa-navy">{pb.time}</td>
                        <td className="px-4 py-3 text-sm text-gray-500 hidden md:table-cell">{pb.meet?.name || "-"}</td>
                        <td className="px-4 py-3 text-right text-xs text-gray-400">{pb.date || "-"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </section>

        <section>
          <h2 className="text-lg font-semibold text-ssa-navy mb-4">Event history</h2>
          <div className="grid gap-3">
            {detail.event_history.map((group) => {
              const isOpen = openEvent === group.event_key;
              return (
                <div key={group.event_key} className="card overflow-hidden">
                  <button onClick={() => setOpenEvent(isOpen ? null : group.event_key)} className="w-full p-4 flex items-center justify-between text-left hover:bg-ssa-teal/5">
                    <div>
                      <h3 className="font-semibold text-ssa-navy">{group.event}</h3>
                      <p className="text-xs text-gray-400">{group.result_count} swims · derived · {group.normalization_status}</p>
                    </div>
                    <span className="text-sm text-ssa-teal">{isOpen ? "Hide" : "Show"}</span>
                  </button>
                  {isOpen && <IndividualRows rows={group.results} />}
                </div>
              );
            })}
          </div>
        </section>

        <section>
          <h2 className="text-lg font-semibold text-ssa-navy mb-4">Relay participation</h2>
          {detail.relay_history.length === 0 ? (
            <div className="card p-6 text-sm text-gray-400 text-center">No relay rows linked to this swimmer yet.</div>
          ) : (
            <div className="grid gap-3">
              {detail.relay_history.map((relay) => <RelayCard key={relay.id} relay={relay} />)}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}

function IndividualRows({ rows }: { rows: BrowserIndividualRow[] }) {
  return (
    <div className="border-t border-gray-100 overflow-x-auto">
      <table className="w-full">
        <thead>
          <tr className="bg-gray-50">
            <th scope="col" className="px-4 py-2 text-left text-xs font-semibold text-gray-500 uppercase">Meet</th>
            <th scope="col" className="px-4 py-2 text-center text-xs font-semibold text-gray-500 uppercase">Round</th>
            <th scope="col" className="px-4 py-2 text-center text-xs font-semibold text-gray-500 uppercase">Place</th>
            <th scope="col" className="px-4 py-2 text-right text-xs font-semibold text-gray-500 uppercase">Time</th>
            <th scope="col" className="px-4 py-2 text-center text-xs font-semibold text-gray-500 uppercase">Source</th>
            <th scope="col" className="px-4 py-2 text-right text-xs font-semibold text-gray-500 uppercase">Date</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100">
          {rows.map((row) => (
            <tr key={row.id} className={`hover:bg-gray-50 ${row.warnings.length > 0 ? "bg-amber-50/40" : ""}`}>
              <td className="px-4 py-3 text-sm text-gray-500">
                {row.meet ? <a href={`/meets/${row.meet.id}/events/${row.event_key}`} className="text-ssa-teal hover:underline">{row.meet.name}</a> : "-"}
                {row.warnings.length > 0 && <div className="mt-1 text-xs text-amber-700">{row.warnings.map((w) => w.message).join(" · ")}</div>}
              </td>
              <td className="px-4 py-3 text-center text-xs text-gray-500">{row.round || "-"}</td>
              <td className="px-4 py-3 text-center text-sm text-gray-600">{row.placement ?? "--"}</td>
              <td className="px-4 py-3 text-right font-mono font-bold text-ssa-navy">{row.is_dq ? "DQ" : row.time || "--"}</td>
              <td className="px-4 py-3 text-center"><SourceBadge linked={Boolean(row.source.document_sha256)} /></td>
              <td className="px-4 py-3 text-right text-xs text-gray-400">{row.swim_date || "-"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function RelayCard({ relay }: { relay: BrowserRelayRow }) {
  return (
    <a href={relay.meet ? `/meets/${relay.meet.id}/events/${relay.event_key}` : "#"} className={`card p-4 block hover:border-ssa-teal/40 hover:shadow-md transition-all ${relay.warnings.length > 0 ? "border-amber-200 bg-amber-50/30" : ""}`}>
      <div className="flex flex-col md:flex-row md:items-start md:justify-between gap-3">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="font-semibold text-ssa-navy">{relay.event_label}</h3>
            <SourceBadge linked={Boolean(relay.source.document_sha256)} />
          </div>
          <p className="text-sm text-gray-500 mt-1">{relay.team_name} {relay.relay_letter || ""} · {relay.meet?.name || "Unknown meet"}</p>
          <div className="mt-2 flex flex-wrap gap-2">
            {relay.legs.map((leg) => (
              <span key={`${relay.id}-${leg.leg_number}`} className="text-xs text-gray-600 bg-gray-100 px-2 py-1 rounded">
                {leg.leg_number}. {leg.swimmer_name}{leg.split_time ? ` (${leg.split_time})` : ""} · {leg.identity_match_confidence} via {leg.matched_by}
              </span>
            ))}
          </div>
          {relay.warnings.length > 0 && <p className="mt-2 text-xs text-amber-700">{relay.warnings.map((w) => w.message).join(" · ")}</p>}
        </div>
        <div className="text-right shrink-0">
          <div className="font-mono font-bold text-ssa-navy">{relay.is_dq ? "DQ" : relay.time || "--"}</div>
          <div className="text-xs text-gray-400">Place {relay.placement ?? "--"}</div>
        </div>
      </div>
    </a>
  );
}

function SourceBadge({ linked }: { linked: boolean }) {
  return linked ? (
    <span className="text-xs text-emerald-700 bg-emerald-50 px-2 py-0.5 rounded">source linked</span>
  ) : (
    <span className="text-xs text-amber-700 bg-amber-50 px-2 py-0.5 rounded">missing source</span>
  );
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div className="bg-ssa-navy/5 rounded-lg px-4 py-2 text-center">
      <div className="text-lg font-bold text-ssa-navy">{value.toLocaleString()}</div>
      <div className="text-xs text-gray-500">{label}</div>
    </div>
  );
}

function LoadingShell() {
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
