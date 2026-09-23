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
  const labels: Record<string, string> = {
    results_available: "Result PDFs found · ready to review",
    documents_available_no_results: "Information found · no result PDF yet",
    pending_no_documents: "Competition page found · documents not uploaded yet",
    no_documents_found: "No documents found on this page",
  };
  const classes: Record<string, string> = {
    results_available: "bg-ssa-teal/10 text-ssa-teal ring-ssa-teal/20",
    documents_available_no_results: "bg-amber-50 text-amber-700 ring-amber-200",
    pending_no_documents: "bg-blue-50 text-blue-700 ring-blue-200",
    no_documents_found: "bg-gray-50 text-gray-600 ring-gray-200",
  };
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${classes[status] || classes.no_documents_found}`}>
      {labels[status] || labels.no_documents_found}
    </span>
  );
}

function processingPill(status: AdminSourceEvent["processingStatus"]) {
  const labels: Record<string, string> = {
    results_not_imported: "Results ready · not imported",
    waiting_for_results: "Waiting for official results",
    source_changed_since_import: "Source changed since import",
    imported_since_tracking: "Imported · unchanged since tracking",
    imported_links_unchanged_bytes_unchecked: "Imported · links unchanged; PDF bytes unchecked",
    imported_current: "Imported · matches source",
    imported_without_manifest_baseline: "Imported · tracking baseline needed",
    import_link_conflict: "Import link needs attention",
  };
  const classes: Record<string, string> = {
    results_not_imported: "bg-ssa-teal/10 text-ssa-teal ring-ssa-teal/20",
    waiting_for_results: "bg-blue-50 text-blue-700 ring-blue-200",
    source_changed_since_import: "bg-amber-50 text-amber-700 ring-amber-200",
    imported_since_tracking: "bg-emerald-50 text-emerald-700 ring-emerald-200",
    imported_links_unchanged_bytes_unchecked: "bg-emerald-50 text-emerald-700 ring-emerald-200",
    imported_current: "bg-emerald-50 text-emerald-700 ring-emerald-200",
    imported_without_manifest_baseline: "bg-amber-50 text-amber-700 ring-amber-200",
    import_link_conflict: "bg-red-50 text-red-700 ring-red-200",
  };
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${classes[status] || classes.waiting_for_results}`}>
      {labels[status] || labels.waiting_for_results}
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

  const importedEvents = useMemo(
    () => events.filter((event) => ["imported_since_tracking", "imported_links_unchanged_bytes_unchecked", "imported_current", "imported_without_manifest_baseline"].includes(event.processingStatus)),
    [events],
  );
  const reviewEvents = useMemo(
    () => events.filter((event) => !["imported_since_tracking", "imported_links_unchanged_bytes_unchecked", "imported_current", "imported_without_manifest_baseline"].includes(event.processingStatus)),
    [events],
  );

  const totals = useMemo(() => {
    return {
      events: events.length,
      reviewEvents: reviewEvents.length,
      importedEvents: importedEvents.length,
      documents: events.reduce((sum, event) => sum + event.documentCount, 0),
    };
  }, [events, importedEvents, reviewEvents]);

  async function handleRun(ruleId: number) {
    setRunningRuleId(ruleId);
    setError("");
    setSuccessMessage("");
    try {
      const result = await runSourceDiscoveryPreview(ruleId);
      setSuccessMessage(
        `Catalogue check complete: ${result.data.eventsDiscovered.toLocaleString()} competition pages were checked and ${result.data.addedDocuments.toLocaleString()} newly found official links were added to the review list. No results were imported.`
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
                <span className="text-ssa-teal text-sm font-semibold uppercase tracking-wider">Official results</span>
              </div>
              <h1 className="text-2xl font-bold text-ssa-navy">Check official competition pages</h1>
              <p className="text-gray-500 text-sm mt-1 max-w-3xl">
                Review competition pages found on SG Aquatics and see which ones have possible result PDFs.
                Checking the catalogue only saves official links for review—it never creates a meet, swimmer, time, or result by itself.
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

        {state !== "loading" && (
          <section className="rounded-2xl border border-ssa-teal/20 bg-gradient-to-br from-ssa-teal/10 to-white p-5 sm:p-6">
            <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
              <div>
                <p className="text-sm font-semibold text-ssa-teal">Official catalogue coverage</p>
                <h2 className="mt-1 text-xl font-bold text-ssa-navy">
                  {totals.reviewEvents.toLocaleString()} competition {totals.reviewEvents === 1 ? "page needs" : "pages need"} review
                </h2>
                <p className="mt-1 max-w-2xl text-sm text-gray-600">
                  Pages with results not yet imported, pages waiting for official files, and source changes stay visible here. Imported history is kept below for audit; when freshness was tracked, its current state is shown there. Catalogue checks never import results automatically.
                </p>
              </div>
              <div className="grid grid-cols-3 gap-3 text-center sm:min-w-[300px]">
                {[
                  ["Competition pages", totals.events],
                  ["Official links", totals.documents],
                  ["Last check", runs[0] ? formatDate(runs[0].finishedAt || runs[0].startedAt) : "Never"],
                ].map(([label, value]) => (
                  <div key={label} className="rounded-xl border border-white bg-white/80 px-3 py-3 shadow-sm">
                    <p className="text-xs font-medium text-gray-500">{label}</p>
                    <p className="mt-1 text-sm font-semibold text-ssa-navy">{value}</p>
                  </div>
                ))}
              </div>
            </div>
            {runs.length === 1 && totals.events > 0 && (
              <p className="mt-4 border-t border-ssa-teal/15 pt-3 text-xs text-gray-600">
                This was the first saved catalogue check, so every page currently appears as newly found. Future checks will distinguish genuinely new or changed pages.
              </p>
            )}
          </section>
        )}

        {state === "loading" && (
          <div className="card p-8 text-center text-gray-500">Loading official competition pages...</div>
        )}

        {state !== "loading" && sources.map((site) => (
          <section key={site.id} className="card overflow-hidden">
            <div className="border-b border-gray-100 px-6 py-5 bg-white">
              <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                <div>
                  <div className="flex items-center gap-3">
                    <h2 className="text-lg font-semibold text-ssa-navy">{site.name}</h2>
                    <span className="rounded-full bg-gray-100 px-2.5 py-1 text-xs font-medium text-gray-600">{site.adapterType}</span>
                    <span className={`rounded-full px-2.5 py-1 text-xs font-medium ${site.isEnabled ? "bg-emerald-50 text-emerald-700" : "bg-gray-100 text-ssa-navy"}`}>
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
                        <h3 className="font-semibold text-gray-900">SG Aquatics competition catalogue</h3>
                        {statusPill(rule.lastStatus)}
                      </div>
                      <p className="mt-1 max-w-2xl text-sm text-gray-600">
                        Last checked {formatDate(rule.lastFinishedAt)}. We found {rule.eventsDiscovered.toLocaleString()} competition pages; {rule.eventsWithResults.toLocaleString()} have possible result PDFs to review.
                      </p>
                    </div>
                    <button
                      onClick={() => handleRun(rule.id)}
                      disabled={runningRuleId === rule.id || !rule.enabled}
                      className={`btn-primary justify-center ${runningRuleId === rule.id || !rule.enabled ? "opacity-60 cursor-not-allowed" : ""}`}
                    >
                      {runningRuleId === rule.id ? "Checking SG Aquatics..." : "Check for newly listed competitions"}
                    </button>
                  </div>

                  <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                    <div className="rounded-xl border border-ssa-teal/15 bg-ssa-teal/5 px-4 py-3">
                      <p className="text-xs font-medium text-gray-500">Competition pages with result PDFs</p>
                      <p className="mt-1 text-xl font-bold text-ssa-navy">{rule.eventsWithResults.toLocaleString()}</p>
                    </div>
                    <div className="rounded-xl border border-gray-100 bg-gray-50 px-4 py-3">
                      <p className="text-xs font-medium text-gray-500">Competition pages checked</p>
                      <p className="mt-1 text-xl font-bold text-ssa-navy">{rule.eventsDiscovered.toLocaleString()}</p>
                    </div>
                    <div className="rounded-xl border border-gray-100 bg-gray-50 px-4 py-3">
                      <p className="text-xs font-medium text-gray-500">What happens next</p>
                      <p className="mt-1 text-sm font-semibold text-gray-900">Review the official page before any import</p>
                    </div>
                  </div>

                  <p className="text-sm text-gray-600">
                    Checking only updates this review list. It does not create a new competition or import results.
                  </p>

                  <details className="rounded-xl border border-gray-100 bg-gray-50 px-4 py-3">
                    <summary className="cursor-pointer text-sm font-medium text-gray-700 hover:text-ssa-navy">
                      Advanced source settings and latest check details
                    </summary>
                    <div className="mt-4 space-y-4 border-t border-gray-200 pt-4">
                      <a href={rule.indexUrl} target="_blank" rel="noreferrer" className="block break-all text-sm text-ssa-teal hover:text-ssa-teal-dark">
                        Official catalogue: {rule.indexUrl}
                      </a>
                      <div className="flex flex-wrap gap-2">
                        {rule.policyLabels.map((label) => (
                          <span key={label} className="rounded-full bg-white px-3 py-1 text-xs text-gray-700 ring-1 ring-gray-200">
                            {label}
                          </span>
                        ))}
                      </div>
                      {rule.lastRun && (
                        <div>
                          <p className="text-sm font-semibold text-gray-900">Latest technical check</p>
                          <div className="mt-2 grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
                            {[
                              ["New catalogue pages", rule.lastRun.addedEvents],
                              ["Changed pages", rule.lastRun.updatedEvents],
                              ["New official links", rule.lastRun.addedDocuments],
                              ["Needs review", rule.lastRun.actionRequiredCount],
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
                  </details>
                </div>
              ))}
            </div>
          </section>
        ))}

        <section className="grid grid-cols-1 gap-8 xl:grid-cols-3">
          <div className="space-y-5 xl:col-span-2">
            <div className="card overflow-hidden">
              <div className="border-b border-gray-100 px-6 py-4">
                <h2 className="font-semibold text-ssa-navy">Needs review</h2>
                <p className="mt-1 text-sm text-gray-500">New results, pages awaiting official files, and source pages changed since their last acknowledged import.</p>
              </div>
              <div className="overflow-x-auto">
                <table className="min-w-full divide-y divide-gray-100 text-sm">
                  <thead className="bg-gray-50 text-left text-xs uppercase tracking-wide text-gray-500">
                    <tr>
                      <th scope="col" className="px-4 py-3">Competition</th>
                      <th scope="col" className="px-4 py-3">Import status</th>
                      <th scope="col" className="px-4 py-3">What we found</th>
                      <th scope="col" className="px-4 py-3">Official documents</th>
                      <th scope="col" className="px-4 py-3">Last checked</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100 bg-white">
                    {reviewEvents.map((event) => (
                      <tr key={event.id}>
                        <td className="px-4 py-3 align-top">
                          <a href={event.url} target="_blank" rel="noreferrer" className="font-medium text-ssa-navy hover:text-ssa-teal">{event.title}</a>
                          <div className="mt-1 flex flex-wrap gap-2 text-xs text-gray-500">
                            {event.sourceYear && <span>{event.sourceYear}</span>}
                            <span>{event.isCurrentlyListed ? "Listed on SG Aquatics" : "Kept from an older catalogue page"}</span>
                            <a href={event.url} target="_blank" rel="noreferrer" className="font-medium text-ssa-teal hover:text-ssa-teal-dark">Open official page ↗</a>
                          </div>
                        </td>
                        <td className="px-4 py-3 align-top">{processingPill(event.processingStatus)}</td>
                        <td className="px-4 py-3 align-top">{readinessPill(event.readinessStatus)}</td>
                        <td className="px-4 py-3 align-top text-gray-700">
                          {event.documentCount} official document {event.documentCount === 1 ? "link" : "links"}<br />
                          <span className="text-xs text-gray-500">{event.resultPdfCount > 0 ? `${event.resultPdfCount} result PDF${event.resultPdfCount === 1 ? "" : "s"}` : "No result PDF found"}</span>
                        </td>
                        <td className="px-4 py-3 align-top text-gray-500">{formatDate(event.lastCheckedAt)}</td>
                      </tr>
                    ))}
                    {reviewEvents.length === 0 && (
                      <tr><td colSpan={5} className="px-4 py-8 text-center text-gray-500">Nothing currently needs review.</td></tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>

            {importedEvents.length > 0 && (
              <details className="overflow-hidden rounded-xl border border-gray-200 bg-white">
                <summary className="cursor-pointer px-6 py-4 text-sm font-semibold text-ssa-navy hover:bg-gray-50">
                  Imported competitions ({importedEvents.length})
                  <span className="ml-2 font-normal text-gray-500">Expand for history and tracked freshness</span>
                </summary>
                <div className="border-t border-gray-100 overflow-x-auto">
                  <table className="min-w-full divide-y divide-gray-100 text-sm">
                    <thead className="bg-gray-50 text-left text-xs uppercase tracking-wide text-gray-500">
                      <tr>
                        <th scope="col" className="px-4 py-3">Competition</th>
                        <th scope="col" className="px-4 py-3">Import status</th>
                        <th scope="col" className="px-4 py-3">Official documents</th>
                        <th scope="col" className="px-4 py-3">Last checked</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-100 bg-white">
                      {importedEvents.map((event) => (
                        <tr key={event.id}>
                          <td className="px-4 py-3 align-top">
                            <a href={event.url} target="_blank" rel="noreferrer" className="font-medium text-ssa-navy hover:text-ssa-teal">{event.title}</a>
                            <p className="mt-1 text-xs text-gray-500">{event.isCurrentlyListed ? "Listed on SG Aquatics" : "Kept from an older catalogue page"}</p>
                          </td>
                          <td className="px-4 py-3 align-top">{processingPill(event.processingStatus)}</td>
                          <td className="px-4 py-3 align-top text-gray-700">{event.documentCount} official document {event.documentCount === 1 ? "link" : "links"}</td>
                          <td className="px-4 py-3 align-top text-gray-500">{formatDate(event.lastCheckedAt)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </details>
            )}
          </div>

          <div className="card overflow-hidden">
            <div className="border-b border-gray-100 px-6 py-4">
              <h2 className="font-semibold text-ssa-navy">Previous catalogue checks</h2>
              <p className="text-sm text-gray-500 mt-1">A check discovers official pages and links only. It never imports results automatically.</p>
            </div>
            <div className="divide-y divide-gray-100">
              {runs.slice(0, 8).map((run) => (
                <div key={run.id} className="p-4">
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <p className="text-sm font-medium text-gray-900">Catalogue check</p>
                      <p className="text-xs text-gray-500">{formatDate(run.finishedAt || run.startedAt)}</p>
                    </div>
                    {statusPill(run.status)}
                  </div>
                  <div className="mt-3 grid grid-cols-3 gap-2 text-xs text-gray-600">
                    <span>{run.eventsDiscovered} competition pages</span>
                    <span>{run.addedDocuments} new official links</span>
                    <span>{run.eventsWithResults} with result PDFs</span>
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
