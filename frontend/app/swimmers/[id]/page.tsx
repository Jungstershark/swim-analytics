"use client";

import { Suspense, useEffect, useState } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import {
  displayName,
  resultDisplayValue,
  getBrowserAthlete,
  getBrowserSwimmer,
  type BrowserSwimmerDetail,
  type BrowserIndividualRow,
  type BrowserRelayRow,
} from "@/lib/api";

export default function SwimmerProfilePage() {
  return (
    <Suspense fallback={<LoadingShell />}>
      <SwimmerProfileContent />
    </Suspense>
  );
}

type Course = "LCM" | "SCM" | "Unknown";
type CourseParam = "LCM" | "SCM" | "unknown";
const COURSE_PARAMS: readonly CourseParam[] = ["LCM", "SCM", "unknown"];

function SwimmerProfileContent() {
  const params = useParams();
  const router = useRouter();
  const searchParams = useSearchParams();
  const swimmerRef = String(params.id || "");
  const athleteMatch = /^a-(\d+)$/.exec(swimmerRef);
  const athleteProfileId = athleteMatch ? Number(athleteMatch[1]) : null;
  const sourceSwimmerId = athleteMatch ? null : Number(swimmerRef);
  const [detail, setDetail] = useState<BrowserSwimmerDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [openEvent, setOpenEvent] = useState<string | null>(null);
  const requestedCourse = searchParams.get("course");
  const selectedCourse: Course | null = COURSE_PARAMS.includes(requestedCourse as CourseParam)
    ? requestedCourse === "unknown" ? "Unknown" : requestedCourse as Exclude<Course, "Unknown">
    : null;

  useEffect(() => {
    if (requestedCourse === null || COURSE_PARAMS.includes(requestedCourse as CourseParam)) return;
    router.replace(`/swimmers/${swimmerRef}`, { scroll: false });
  }, [requestedCourse, router, swimmerRef]);

  useEffect(() => {
    const validProfile = athleteProfileId !== null && Number.isInteger(athleteProfileId) && athleteProfileId > 0;
    const validLegacy = sourceSwimmerId !== null && Number.isInteger(sourceSwimmerId) && sourceSwimmerId > 0;
    if (!validProfile && !validLegacy) {
      setDetail(null);
      setError("Swimmer not found");
      setLoading(false);
      return;
    }
    setLoading(true);
    setError("");
    const request = validProfile
      ? getBrowserAthlete(athleteProfileId)
      : getBrowserSwimmer(sourceSwimmerId as number);
    request
      .then(setDetail)
      .catch((e) => setError(e.message || "Failed to load swimmer"))
      .finally(() => setLoading(false));
  }, [athleteProfileId, sourceSwimmerId]);

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
  const displayedCourses = selectedCourse
    ? detail.course_history.filter((group) => group.course === selectedCourse)
    : detail.course_history;

  function selectCourse(course: Course | null) {
    const next = new URLSearchParams(searchParams.toString());
    if (course) next.set("course", course === "Unknown" ? "unknown" : course);
    else next.delete("course");
    const query = next.toString();
    setOpenEvent(null);
    router.push(`/swimmers/${swimmerRef}${query ? `?${query}` : ""}`);
  }

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
                {swimmer.team || "No team"}{swimmer.ages.length > 0 ? ` · ${swimmer.ages.length === 1 ? "Age" : "Ages"} ${swimmer.ages.join(", ")}` : ""}
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
          <div className="flex flex-col sm:flex-row sm:items-end sm:justify-between gap-3 mb-4">
            <div>
              <h2 className="text-lg font-semibold text-ssa-navy">Recorded performance history</h2>
              <p className="text-sm text-gray-500 mt-1">Choose the pool course, then open an event to follow competition-by-competition progress.</p>
            </div>
            <div className="flex flex-wrap gap-2" aria-label="Pool course">
              <button
                type="button"
                aria-pressed={selectedCourse === null}
                onClick={() => selectCourse(null)}
                className={`min-h-11 rounded-full px-4 py-2 text-sm font-semibold transition-colors ${selectedCourse === null ? "bg-ssa-navy text-white" : "bg-white border border-gray-200 text-gray-600 hover:border-ssa-teal"}`}
              >
                All courses
              </button>
              {detail.course_history.map((group) => {
                const isSelected = selectedCourse === group.course;
                return (
                  <button
                    key={group.course}
                    type="button"
                    aria-pressed={isSelected}
                    onClick={() => selectCourse(group.course)}
                    className={`min-h-11 rounded-full px-4 py-2 text-sm font-semibold transition-colors ${isSelected ? "bg-ssa-navy text-white" : "bg-white border border-gray-200 text-gray-600 hover:border-ssa-teal"}`}
                  >
                    {group.course} <span className={isSelected ? "text-white/70" : "text-gray-400"}>{group.event_count}</span>
                  </button>
                );
              })}
            </div>
          </div>

          {displayedCourses.length === 0 ? (
            <div className="card p-6 text-sm text-gray-400 text-center">No recorded individual performances yet.</div>
          ) : (
            <div className="grid gap-6">
              {displayedCourses.map((group) => (
                <section key={group.course} aria-label={`${group.course} performance history`} className="grid gap-3">
                  {selectedCourse === null && <h2 className="text-lg font-semibold text-ssa-navy">{group.course}</h2>}
                  {group.events.map((event) => {
                    const eventIdentity = `${group.course}:${event.canonical_event_key}`;
                    const isOpen = openEvent === eventIdentity;
                    return (
                  <div key={eventIdentity} className="card overflow-hidden">
                    <button
                      type="button"
                      aria-expanded={isOpen}
                      onClick={() => setOpenEvent(isOpen ? null : eventIdentity)}
                      className="min-h-11 w-full p-4 flex items-center justify-between gap-4 text-left hover:bg-ssa-teal/5"
                    >
                      <div className="min-w-0">
                        <h3 className="font-semibold text-ssa-navy">{event.event}</h3>
                        <p className="text-xs text-gray-500 mt-1">
                          {event.performance_count} recorded {event.performance_count === 1 ? "swim" : "swims"}
                          {event.split_coverage.available > 0 ? ` · splits for ${event.split_coverage.available}` : ""}
                        </p>
                      </div>
                      <div className="flex items-center gap-4 shrink-0">
                        <div className="text-right">
                          <div className="text-[10px] uppercase tracking-wide text-gray-400">Fastest recorded</div>
                          <div className="font-mono font-bold text-ssa-navy">{event.fastest_recorded?.time || "—"}</div>
                        </div>
                        <span className="text-sm text-ssa-teal hidden sm:inline">{isOpen ? "Hide" : "View history"}</span>
                      </div>
                    </button>
                    {isOpen && <IndividualRows rows={event.performances} />}
                  </div>
                    );
                  })}
                </section>
              ))}
            </div>
          )}
        </section>

        <section>
          <h2 className="text-lg font-semibold text-ssa-navy mb-4">Relay participation</h2>
          {detail.relay_history.length === 0 ? (
            <div className="card p-6 text-sm text-gray-400 text-center">No relay performances linked to this swimmer yet.</div>
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
    <div className="border-t border-gray-100">
      <div className="sm:hidden divide-y divide-gray-100" data-testid="mobile-history-rows">
        {rows.map((row) => (
          <article key={row.id} className={`p-4 space-y-3 ${row.warnings.length > 0 ? "bg-amber-50/40" : "bg-white"}`}>
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="text-[10px] uppercase tracking-wide text-gray-400">Meet</div>
                <div className="text-sm text-gray-600 break-words">
                  {row.meet ? <a href={`/meets/${row.meet.id}/events/${row.event_key}`} className="text-ssa-teal hover:underline">{row.meet.name}</a> : "-"}
                </div>
                <div className="mt-1 text-xs text-gray-400">{row.swim_date || "Date unavailable"}</div>
              </div>
              <div className="shrink-0 text-right">
                <div className="text-[10px] uppercase tracking-wide text-gray-400">Time</div>
                <div className="font-mono font-bold text-ssa-navy">{resultDisplayValue(row.status, row.time, row.is_dq)}</div>
              </div>
            </div>
            <dl className="grid grid-cols-3 gap-2 text-center">
              <div className="rounded bg-gray-50 p-2">
                <dt className="text-[10px] uppercase tracking-wide text-gray-400">Round</dt>
                <dd className="mt-1 text-xs text-gray-600">{row.round || "-"}</dd>
              </div>
              <div className="rounded bg-gray-50 p-2">
                <dt className="text-[10px] uppercase tracking-wide text-gray-400">Place</dt>
                <dd className="mt-1 text-sm text-gray-600">{row.placement ?? "--"}</dd>
              </div>
              <div className="rounded bg-gray-50 p-2">
                <dt className="text-[10px] uppercase tracking-wide text-gray-400">Source</dt>
                <dd className="mt-1"><SourceBadge linked={Boolean(row.source.document_sha256)} /></dd>
              </div>
            </dl>
            {row.splits.length > 0 && (
              <div className="flex flex-wrap gap-1" aria-label="Official splits">
                {row.splits.map((split, index) => (
                  <span key={`${row.id}-mobile-split-${index}`} className="rounded bg-sky-50 px-2 py-0.5 text-[11px] text-sky-800">
                    {split.distance ? `${split.distance}m ` : ""}{split.cumulative || split.split || "—"}
                  </span>
                ))}
              </div>
            )}
            {row.warnings.length > 0 && <div className="text-xs text-amber-700">{row.warnings.map((w) => w.message).join(" · ")}</div>}
          </article>
        ))}
      </div>

      <div className="hidden sm:block overflow-x-auto" data-testid="desktop-history-table">
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
                  {row.splits.length > 0 && (
                    <div className="mt-2 flex flex-wrap gap-1" aria-label="Official splits">
                      {row.splits.map((split, index) => (
                        <span key={`${row.id}-split-${index}`} className="rounded bg-sky-50 px-2 py-0.5 text-[11px] text-sky-800">
                          {split.distance ? `${split.distance}m ` : ""}{split.cumulative || split.split || "—"}
                        </span>
                      ))}
                    </div>
                  )}
                  {row.warnings.length > 0 && <div className="mt-1 text-xs text-amber-700">{row.warnings.map((w) => w.message).join(" · ")}</div>}
                </td>
                <td className="px-4 py-3 text-center text-xs text-gray-500">{row.round || "-"}</td>
                <td className="px-4 py-3 text-center text-sm text-gray-600">{row.placement ?? "--"}</td>
                <td className="px-4 py-3 text-right font-mono font-bold text-ssa-navy">{resultDisplayValue(row.status, row.time, row.is_dq)}</td>
                <td className="px-4 py-3 text-center"><SourceBadge linked={Boolean(row.source.document_sha256)} /></td>
                <td className="px-4 py-3 text-right text-xs text-gray-400">{row.swim_date || "-"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
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
                {leg.leg_number}. {leg.swimmer_name}{leg.split_time ? ` (${leg.split_time})` : ""}
              </span>
            ))}
          </div>
          {relay.warnings.length > 0 && <p className="mt-2 text-xs text-amber-700">{relay.warnings.map((w) => w.message).join(" · ")}</p>}
        </div>
        <div className="text-right shrink-0">
          <div className="font-mono font-bold text-ssa-navy">{resultDisplayValue(relay.status, relay.time, relay.is_dq)}</div>
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
