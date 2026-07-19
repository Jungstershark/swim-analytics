"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  listAdminMonitorRuns,
  listAdminSourceEvents,
  listAdminSources,
  runSourceDiscoveryPreview,
  type AdminMonitorRun,
  type AdminSourceEvent,
  type AdminSourceSite,
} from "@/lib/api";

type LoadState = "loading" | "ready" | "error";

function formatDate(value: string | null): string {
  if (!value) return "Never";
  try {
    return new Date(value).toLocaleString("en-SG", {
      day: "2-digit",
      month: "short",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return value;
  }
}

function statusPill(status: string | null) {
  const normalized = status || "not_run";
  const classes: Record<string, string> = {
    succeeded: "bg-emerald-50 text-emerald-700 ring-emerald-200",
    failed: "bg-red-50 text-red-700 ring-red-200",
    partial_failed: "bg-amber-50 text-amber-700 ring-amber-200",
    running: "bg-blue-50 text-blue-700 ring-blue-200",
    not_run: "bg-gray-50 text-gray-600 ring-gray-200",
  };
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-1 text-xs font-medium ring-1 ring-inset ${classes[normalized] || classes.not_run}`}>
      {normalized.replace("_", " ")}
    </span>
  );
}

function readinessPill(status: string) {
  const classes: Record<string, string> = {
    results_available: "bg-ssa-teal/10 text-ssa-teal ring-ssa-teal/20",
    documents_available_no_results: "bg-amber-50 text-amber-700 ring-amber-200",
    pending_no_documents: "bg-blue-50 text-blue-700 ring-blue-200",
    no_documents_found: "bg-gray-50 text-gray-600 ring-gray-200",
  };
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${classes[status] || classes.no_documents_found}`}>
      {status.replaceAll("_", " ")}
    </span>
  );
}

export default function AdminSourcesPage() {
  const [state, setState] = useState<LoadState>("loading");
  const [sources, setSources] = useState<AdminSourceSite[]>([]);
  const [events, setEvents] = useState<AdminSourceEvent[]>([]);
  const [runs, setRuns] = useState<AdminMonitorRun[]>([]);
  const [error, setError] = useState("");
  const [successMessage, setSuccessMessage] = useState("");
  const [runningRuleId, setRunningRuleId] = useState<number | null>(null);
  const loadSequence = useRef(0);
  const mounted = useRef(false);

  async function load(options: { clearMessages?: boolean } = {}) {
    const sequence = ++loadSequence.current;
    if (options.clearMessages ?? true) {
      setError("");
      setSuccessMessage("");
    }
    setState("loading");
    try {
      const [sourcesRes, eventsRes, runsRes] = await Promise.all([
        listAdminSources(),
        listAdminSourceEvents(),
        listAdminMonitorRuns(),
      ]);
      if (!mounted.current || sequence !== loadSequence.current) return;
      setSources(sourcesRes.data);
      setEvents(eventsRes.data);
      setRuns(runsRes.data);
      setState("ready");
    } catch (e: any) {
      if (!mounted.current || sequence !== loadSequence.current) return;
      setError(e.message || "Failed to load source monitoring state");
      setState("error");
    }
  }

  useEffect(() => {
    mounted.current = true;
    load();
    return () => {
      mounted.current = false;
      loadSequence.current += 1;
    };
  }, []);

  const totals = useMemo(() => {
    return {
      sources: sources.length,
      rules: sources.reduce((sum, site) => sum + site.rules.length, 0),
      events: events.length,
      resultReadyEvents: events.filter((event) => event.readinessStatus === "results_available").length,
      documents: events.reduce((sum, event) => sum + event.documentCount, 0),
      actionRequired: sources.reduce(
        (sum, site) => sum + site.rules.reduce((inner, rule) => inner + rule.actionRequiredCount, 0),
        0
      ),
    };
  }, [sources, events]);

  async function handleRun(ruleId: number) {
    setRunningRuleId(ruleId);
    setError("");
    setSuccessMessage("");
    try {
      const result = await runSourceDiscoveryPreview(ruleId);
      setSuccessMessage(
        `Discovery preview completed: ${result.data.eventsDiscovered.toLocaleString()} source events and ${result.data.addedDocuments.toLocaleString()} new document links were cataloged. Swim results were not imported.`
      );
      await load({ clearMessages: false });
    } catch (e: any) {
      setError(e.message || "Discovery preview failed");
      await load({ clearMessages: false }).catch(() => undefined);
    } finally {
      setRunningRuleId(null);
    }
  }

  return (
    <div className="min-h-screen">
      <div className="bg-white border-b border-gray-200">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
          <nav className="flex items-center gap-2 text-sm mb-4">
            <a href="/" className="text-gray-500 hover:text-ssa-navy transition-colors">Dashboard</a>
            <svg aria-hidden="true" className="w-4 h-4 text-gray-300" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M8.25 4.5l7.5 7.5-7.5 7.5" />
            </svg>
            <span className="text-ssa-navy font-medium">Admin Sources</span>
          </nav>
          <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
            <div>
              <div className="flex items-center gap-2 mb-2">
                <div className="h-1 w-10 bg-ssa-teal rounded-full" />
                <span className="text-ssa-teal text-sm font-semibold uppercase tracking-wider">Source Monitoring</span>
              </div>
              <h1 className="text-2xl font-bold text-ssa-navy">Official Source Rules</h1>
              <p className="text-gray-500 text-sm mt-1 max-w-3xl">
                Visible configuration for official result sources. This page shows what sites are monitored,
                how discovery is triggered, which document categories are cataloged for preview, and what changed in the latest run.
                Auto-import is disabled: discovery preview only catalogs source event/document links and does not import swim results.
              </p>
            </div>
            <button onClick={() => load()} className="btn-outline justify-center">
              Refresh
            </button>
          </div>
        </div>
      </div>

      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-8">
        {error && (
          <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">
            {error}
          </div>
        )}

        {successMessage && (
          <div className="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800" role="status">
            {successMessage}
          </div>
        )}

        <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
          <strong>Discovery preview only.</strong> Auto-import is disabled. Running discovery updates source event and document-link catalog metadata only; it does not create meets, swimmers, times, relay rows, or imported results.
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-6 gap-4">
          {[
            ["Sources", totals.sources],
            ["Rules", totals.rules],
            ["Known Events", totals.events],
            ["Result Ready", totals.resultReadyEvents],
            ["Document Links", totals.documents],
            ["Action Required", totals.actionRequired],
          ].map(([label, value]) => (
            <div key={label} className="card p-4">
              <p className="text-xs font-medium uppercase tracking-wide text-gray-500">{label}</p>
              <p className="mt-2 text-2xl font-bold text-ssa-navy">{value}</p>
            </div>
          ))}
        </div>

        {state === "loading" && (
          <div className="card p-8 text-center text-gray-500">Loading source monitoring state...</div>
        )}

        {state !== "loading" && sources.map((site) => (
          <section key={site.id} className="card overflow-hidden">
            <div className="border-b border-gray-100 px-6 py-5 bg-white">
              <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                <div>
                  <div className="flex items-center gap-3">
                    <h2 className="text-lg font-semibold text-ssa-navy">{site.name}</h2>
                    <span className="rounded-full bg-gray-100 px-2.5 py-1 text-xs font-medium text-gray-600">{site.adapterType}</span>
                    <span className={`rounded-full px-2.5 py-1 text-xs font-medium ${site.isEnabled ? "bg-emerald-50 text-emerald-700" : "bg-gray-100 text-gray-500"}`}>
                      {site.isEnabled ? "Enabled" : "Disabled"}
                    </span>
                  </div>
                  <a href={site.baseUrl} target="_blank" rel="noreferrer" className="mt-1 block text-sm text-ssa-teal hover:text-ssa-teal-dark break-all">
                    {site.baseUrl}
                  </a>
                </div>
              </div>
            </div>

            <div className="divide-y divide-gray-100">
              {site.rules.map((rule) => (
                <div key={rule.id} className="p-6 space-y-5">
                  <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <h3 className="font-semibold text-gray-900">{rule.name}</h3>
                        {statusPill(rule.lastStatus)}
                        <span className="rounded-full bg-blue-50 px-2.5 py-1 text-xs font-medium text-blue-700 ring-1 ring-blue-200">
                          {rule.scheduleLabel}
                        </span>
                        <span className="rounded-full bg-amber-50 px-2.5 py-1 text-xs font-medium text-amber-700 ring-1 ring-amber-200">
                          {rule.autoImportLabel}
                        </span>
                      </div>
                      <a href={rule.indexUrl} target="_blank" rel="noreferrer" className="mt-1 block text-sm text-ssa-teal hover:text-ssa-teal-dark break-all">
                        {rule.indexUrl}
                      </a>
                    </div>
                    <button
                      onClick={() => handleRun(rule.id)}
                      disabled={runningRuleId === rule.id || !rule.enabled}
                      className={`btn-primary justify-center ${runningRuleId === rule.id || !rule.enabled ? "opacity-60 cursor-not-allowed" : ""}`}
                    >
                      {runningRuleId === rule.id ? "Running discovery..." : "Run discovery preview"}
                    </button>
                  </div>

                  <div className="grid grid-cols-2 lg:grid-cols-5 gap-3">
                    {[
                      ["Last finished", formatDate(rule.lastFinishedAt)],
                      ["Events discovered", rule.eventsDiscovered.toLocaleString()],
                      ["With results", rule.eventsWithResults.toLocaleString()],
                      ["Action required", rule.actionRequiredCount.toLocaleString()],
                      ["Last trigger", rule.lastTriggerLabel],
                    ].map(([label, value]) => (
                      <div key={label} className="rounded-lg bg-gray-50 px-3 py-3">
                        <p className="text-xs text-gray-500">{label}</p>
                        <p className="mt-1 text-sm font-semibold text-gray-900">{value}</p>
                      </div>
                    ))}
                  </div>

                  <div>
                    <h4 className="text-sm font-semibold text-gray-900 mb-2">Readable platform rules</h4>
                    <div className="flex flex-wrap gap-2">
                      {rule.policyLabels.map((label) => (
                        <span key={label} className="rounded-full bg-gray-50 px-3 py-1 text-xs text-gray-700 ring-1 ring-gray-200">
                          {label}
                        </span>
                      ))}
                    </div>
                  </div>

                  {rule.lastRun && (
                    <div className="rounded-xl border border-gray-100 bg-gray-50 p-4">
                      <div className="flex flex-wrap items-center gap-2 mb-3">
                        <h4 className="text-sm font-semibold text-gray-900">Latest monitor run</h4>
                        {statusPill(rule.lastRun.status)}
                      </div>
                      <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-8 gap-3 text-sm">
                        {[
                          ["Added events", rule.lastRun.addedEvents],
                          ["Updated events", rule.lastRun.updatedEvents],
                          ["Unchanged events", rule.lastRun.unchangedEvents],
                          ["Absent events", rule.lastRun.absentFromIndexEvents],
                          ["Added document links", rule.lastRun.addedDocuments],
                          ["Updated catalog docs", rule.lastRun.updatedDocuments],
                          ["Unchanged catalog docs", rule.lastRun.unchangedDocuments],
                          ["Action required", rule.lastRun.actionRequiredCount],
                        ].map(([label, value]) => (
                          <div key={label}>
                            <p className="text-xs text-gray-500">{label}</p>
                            <p className="font-semibold text-ssa-navy">{Number(value).toLocaleString()}</p>
                          </div>
                        ))}
                      </div>
                      {rule.lastRun.errorMessage && (
                        <p className="mt-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{rule.lastRun.errorMessage}</p>
                      )}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </section>
        ))}

        <section className="grid grid-cols-1 xl:grid-cols-3 gap-8">
          <div className="xl:col-span-2 card overflow-hidden">
            <div className="border-b border-gray-100 px-6 py-4">
              <h2 className="font-semibold text-ssa-navy">Discovered source events</h2>
              <p className="text-sm text-gray-500 mt-1">Persistent catalog survives SG Aquatics year-end page rollover.</p>
            </div>
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-gray-100 text-sm">
                <thead className="bg-gray-50 text-left text-xs uppercase tracking-wide text-gray-500">
                  <tr>
                    <th scope="col" className="px-4 py-3">Event</th>
                    <th scope="col" className="px-4 py-3">Status</th>
                    <th scope="col" className="px-4 py-3">Document Links</th>
                    <th scope="col" className="px-4 py-3">Last seen</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100 bg-white">
                  {events.slice(0, 12).map((event) => (
                    <tr key={event.id}>
                      <td className="px-4 py-3 align-top">
                        <a href={event.url} target="_blank" rel="noreferrer" className="font-medium text-ssa-navy hover:text-ssa-teal">
                          {event.title}
                        </a>
                        <div className="mt-1 flex flex-wrap gap-2 text-xs text-gray-500">
                          {event.sourceYear && <span>{event.sourceYear}</span>}
                          <span>{event.isCurrentlyListed ? "Currently listed" : "Retained from older index"}</span>
                        </div>
                      </td>
                      <td className="px-4 py-3 align-top">{readinessPill(event.readinessStatus)}</td>
                      <td className="px-4 py-3 align-top text-gray-700">
                        {event.documentCount} document links<br />
                        <span className="text-xs text-gray-500">{event.resultPdfCount} result PDFs</span>
                      </td>
                      <td className="px-4 py-3 align-top text-gray-500">{formatDate(event.lastSeenInIndexAt)}</td>
                    </tr>
                  ))}
                  {events.length === 0 && (
                    <tr>
                      <td colSpan={4} className="px-4 py-8 text-center text-gray-500">No source events discovered yet.</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>

          <div className="card overflow-hidden">
            <div className="border-b border-gray-100 px-6 py-4">
              <h2 className="font-semibold text-ssa-navy">Recent monitor runs</h2>
              <p className="text-sm text-gray-500 mt-1">Manual-only in this slice. No hidden scheduler.</p>
            </div>
            <div className="divide-y divide-gray-100">
              {runs.slice(0, 8).map((run) => (
                <div key={run.id} className="p-4">
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <p className="text-sm font-medium text-gray-900">Run #{run.id}</p>
                      <p className="text-xs text-gray-500">{formatDate(run.finishedAt || run.startedAt)}</p>
                    </div>
                    {statusPill(run.status)}
                  </div>
                  <div className="mt-3 grid grid-cols-3 gap-2 text-xs text-gray-600">
                    <span>{run.eventsDiscovered} events</span>
                    <span>{run.addedDocuments} link adds</span>
                    <span>{run.actionRequiredCount} actions</span>
                  </div>
                  {run.errorMessage && <p className="mt-2 text-xs text-red-600">{run.errorMessage}</p>}
                </div>
              ))}
              {runs.length === 0 && <div className="p-6 text-center text-sm text-gray-500">No monitor runs yet.</div>}
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
