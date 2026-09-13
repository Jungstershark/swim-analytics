"use client";

import { useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import { getBrowserMeet, type BrowserMeetDetail, type BrowserEventGroup } from "@/lib/api";

export default function MeetDetailPage() {
  const params = useParams();
  const meetId = Number(params.id);
  const [meet, setMeet] = useState<BrowserMeetDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [eventSearch, setEventSearch] = useState("");
  const [rowType, setRowType] = useState<"all" | "individual" | "relay">("all");

  useEffect(() => {
    if (!meetId) return;
    setLoading(true);
    setError("");
    getBrowserMeet(meetId)
      .then(setMeet)
      .catch((e) => setError(e.message || "Failed to load meet"))
      .finally(() => setLoading(false));
  }, [meetId]);

  const filteredEvents = useMemo(() => {
    const events = meet?.event_groups ?? [];
    return events.filter((e) => {
      const matchesSearch = !eventSearch || e.event_label.toLowerCase().includes(eventSearch.toLowerCase());
      const matchesType = rowType === "all" || (rowType === "individual" ? e.individual_count > 0 : e.relay_count > 0);
      return matchesSearch && matchesType;
    });
  }, [meet, eventSearch, rowType]);

  if (loading) {
    return <LoadingShell />;
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

  return (
    <div className="min-h-screen">
      <div className="bg-white border-b border-gray-200">
        <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
          <nav aria-label="Breadcrumb" className="flex min-w-0 items-center gap-2 text-sm mb-4">
            <a href="/" className="shrink-0 text-gray-500 hover:text-ssa-navy transition-colors">Home</a>
            <span className="text-gray-300">/</span>
            <a href="/meets" className="shrink-0 text-gray-500 hover:text-ssa-navy transition-colors">Meets</a>
            <span className="text-gray-300">/</span>
            <span className="truncate text-ssa-navy font-medium" aria-current="page">{meet.meet.name}</span>
          </nav>
          <div className="flex flex-col lg:flex-row lg:items-end lg:justify-between gap-4">
            <div>
              <h1 className="text-2xl font-bold text-ssa-navy">{meet.meet.name}</h1>
              <p className="text-gray-500 text-sm mt-1">
                {meet.meet.date ? formatDate(meet.meet.date) : "Date unknown"}
                {meet.meet.location ? ` · ${meet.meet.location}` : ""}
              </p>

            </div>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              <Metric label="Event groups" value={meet.summary.event_group_count} />
              <Metric label="Individual" value={meet.summary.individual_result_count} />
              <Metric label="Relays" value={meet.summary.relay_result_count} />
              <Metric label="Total rows" value={meet.summary.total_rows} />
            </div>
          </div>
        </div>
      </div>

      <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {meet.source_summary.missing_source_count > 0 && (
          <div className="mb-6 rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
            {meet.source_summary.missing_source_count.toLocaleString()} result rows in this meet are missing source provenance. They remain visible but should be reviewed.
          </div>
        )}

        <div className="card p-4 mb-6">
          <div className="grid grid-cols-1 md:grid-cols-[1fr_auto] gap-3">
            <input
              type="text"
              aria-label="Search event groups in this meet"
              placeholder="Search event groups..."
              value={eventSearch}
              onChange={(e) => setEventSearch(e.target.value)}
              className="w-full px-4 py-2.5 bg-gray-50 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-ssa-teal/20 focus:border-ssa-teal"
            />
            <div className="flex rounded-lg border border-gray-200 overflow-hidden bg-gray-50" role="group" aria-label="Filter event groups by row type">
              {(["all", "individual", "relay"] as const).map((value) => (
                <button
                  key={value}
                  type="button"
                  aria-pressed={rowType === value}
                  aria-label={`Show ${value} event groups`}
                  onClick={() => setRowType(value)}
                  className={`px-3 py-2 text-sm capitalize transition-colors ${rowType === value ? "bg-ssa-navy text-white" : "text-gray-600 hover:bg-gray-100"}`}
                >
                  {value}
                </button>
              ))}
            </div>
          </div>
        </div>

        <div className="grid gap-3">
          {filteredEvents.length === 0 ? (
            <div className="card p-8 text-center text-gray-400 text-sm">No event groups found</div>
          ) : filteredEvents.map((event) => (
            <EventCard key={event.event_key} meetId={meet.meet.id} event={event} />
          ))}
        </div>
      </div>
    </div>
  );
}

function EventCard({ meetId, event }: { meetId: number; event: BrowserEventGroup }) {
  return (
    <a href={`/meets/${meetId}/events/${event.event_key}`} className="card p-4 hover:border-ssa-teal/40 hover:shadow-md transition-all block">
      <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            {event.source_event_number && <span className="text-xs font-semibold text-ssa-teal bg-ssa-teal/10 px-2 py-0.5 rounded-full">Event {event.source_event_number}</span>}
            <h2 className="font-semibold text-ssa-navy">{event.event_label}</h2>
          </div>
          <div className="flex flex-wrap gap-2 mt-2">
            {event.rounds.map((round) => <span key={round} className="text-xs text-gray-600 bg-gray-100 px-2 py-0.5 rounded">{round}</span>)}
            {event.swim_dates.map((date) => <span key={date} className="text-xs text-gray-500">{date}</span>)}
          </div>
        </div>
        <div className="grid grid-cols-3 gap-2 text-center lg:min-w-[260px]">
          <SmallMetric label="Rows" value={event.total_rows} />
          <SmallMetric label="Ind" value={event.individual_count} />
          <SmallMetric label="Relay" value={event.relay_count} />
        </div>
      </div>
    </a>
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

function SmallMetric({ label, value }: { label: string; value: number }) {
  return (
    <div className="bg-gray-50 rounded-lg px-3 py-2">
      <div className="text-sm font-bold text-ssa-navy">{value.toLocaleString()}</div>
      <div className="text-[10px] uppercase tracking-wider text-gray-500">{label}</div>
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

function formatDate(dateStr: string): string {
  try {
    return new Date(dateStr).toLocaleDateString("en-SG", { day: "numeric", month: "long", year: "numeric" });
  } catch {
    return dateStr;
  }
}
