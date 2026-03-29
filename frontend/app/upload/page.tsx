"use client";

import { useState } from "react";
import {
  previewUpload,
  uploadResults,
  type UploadPreviewResponse,
  type UploadResponse,
} from "@/lib/api";

type Step = "select" | "preview" | "uploading" | "done";

export default function UploadPage() {
  const [step, setStep] = useState<Step>("select");
  const [error, setError] = useState("");
  const [dragOver, setDragOver] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [replaceMode, setReplaceMode] = useState(false);
  const [preview, setPreview] = useState<UploadPreviewResponse | null>(null);
  const [result, setResult] = useState<UploadResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [expandedEvents, setExpandedEvents] = useState<Set<string>>(new Set());
  const [eventSearch, setEventSearch] = useState("");

  function toggleEvent(key: string) {
    setExpandedEvents((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  function handleFileSelect(file: File | null) {
    if (file) {
      const name = file.name.toLowerCase();
      if (!name.endsWith(".pdf") && !name.endsWith(".zip")) {
        setError("Please select a PDF or ZIP file");
        return;
      }
    }
    setError("");
    setPreview(null);
    setResult(null);
    setSelectedFile(file);
    setStep("select");
  }

  async function handlePreview() {
    if (!selectedFile) return;
    setLoading(true);
    setError("");
    setPreview(null);
    setProgress(0);

    // Animate progress bar (estimate ~3s per MB)
    const estimatedMs = Math.max(5000, (selectedFile.size / 1024 / 1024) * 3000);
    const interval = setInterval(() => {
      setProgress((p) => Math.min(p + 2, 90)); // cap at 90% until done
    }, estimatedMs / 45);

    try {
      const res = await previewUpload(selectedFile);
      setProgress(100);
      setPreview(res);
      setExpandedEvents(new Set<string>());
      setEventSearch("");
      setStep("preview");
    } catch (e: any) {
      setError(e.message || "Failed to parse file. The file may be too large or the server timed out.");
    } finally {
      clearInterval(interval);
      setLoading(false);
      setProgress(0);
    }
  }

  async function handleConfirm() {
    if (!selectedFile) return;
    setStep("uploading");
    setError("");
    setProgress(0);

    const estimatedMs = Math.max(5000, (selectedFile.size / 1024 / 1024) * 5000);
    const interval = setInterval(() => {
      setProgress((p) => Math.min(p + 2, 90));
    }, estimatedMs / 45);

    try {
      const res = await uploadResults(selectedFile, { replace: replaceMode });
      setProgress(100);
      setResult(res);
      setStep("done");
      setSelectedFile(null);
    } catch (e: any) {
      setError(e.message || "Failed to upload");
      setStep("preview");
    } finally {
      clearInterval(interval);
      setProgress(0);
    }
  }

  function handleReset() {
    setStep("select");
    setSelectedFile(null);
    setPreview(null);
    setResult(null);
    setError("");
  }

  function handleDrop(e: React.DragEvent) {
    e.preventDefault();
    setDragOver(false);
    handleFileSelect(e.dataTransfer.files[0] || null);
  }

  return (
    <div className="min-h-screen">
      {/* Page Header */}
      <div className="bg-white border-b border-gray-200">
        <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
          <nav className="flex items-center gap-2 text-sm mb-4">
            <a href="/" className="text-gray-500 hover:text-ssa-navy transition-colors">Dashboard</a>
            <svg className="w-4 h-4 text-gray-300" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M8.25 4.5l7.5 7.5-7.5 7.5" />
            </svg>
            <span className="text-ssa-navy font-medium">Upload</span>
          </nav>
          <h1 className="text-2xl font-bold text-ssa-navy">Upload Meet Results</h1>
          <p className="text-gray-500 text-sm mt-1">
            Import PDF results from HY-TEK Meet Manager
          </p>
        </div>
      </div>

      <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-8">

        {/* Step indicator */}
        <div className="flex items-center gap-2 mb-6 text-sm">
          {["Select File", "Preview", "Confirm"].map((label, i) => {
            const stepIndex = { select: 0, preview: 1, uploading: 2, done: 2 }[step];
            const isActive = i <= stepIndex;
            return (
              <div key={label} className="flex items-center gap-2">
                {i > 0 && <div className={`w-8 h-px ${isActive ? "bg-ssa-teal" : "bg-gray-200"}`} />}
                <span className={`px-3 py-1 rounded-full text-xs font-medium ${
                  isActive ? "bg-ssa-teal text-white" : "bg-gray-100 text-gray-400"
                }`}>
                  {label}
                </span>
              </div>
            );
          })}
        </div>

        {/* ============ STEP 1: SELECT FILE ============ */}
        {(step === "select" || step === "preview") && (
          <div className="max-w-2xl">
            <div
              onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
              onDragLeave={() => setDragOver(false)}
              onDrop={handleDrop}
              onClick={() => document.getElementById("file-input")?.click()}
              className={`card p-10 text-center cursor-pointer transition-all duration-200 ${
                dragOver
                  ? "border-ssa-teal border-2 bg-ssa-teal/5 shadow-lg"
                  : selectedFile
                  ? "border-ssa-teal border-2 bg-ssa-teal/5"
                  : "border-dashed border-2 border-gray-300 hover:border-ssa-teal hover:bg-gray-50"
              }`}
            >
              <input
                id="file-input"
                type="file"
                accept=".pdf,.zip"
                className="hidden"
                onChange={(e) => handleFileSelect(e.target.files?.[0] || null)}
              />
              {selectedFile ? (
                <div>
                  <div className="w-14 h-14 mx-auto mb-4 bg-ssa-teal/10 rounded-xl flex items-center justify-center">
                    <svg className="w-7 h-7 text-ssa-teal" fill="none" stroke="currentColor" strokeWidth="1.5" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
                    </svg>
                  </div>
                  <p className="text-sm font-semibold text-ssa-navy">{selectedFile.name}</p>
                  <p className="text-xs text-gray-500 mt-1">
                    {(selectedFile.size / 1024).toFixed(0)} KB &middot; Click to change
                  </p>
                </div>
              ) : (
                <div>
                  <div className="w-14 h-14 mx-auto mb-4 bg-gray-100 rounded-xl flex items-center justify-center">
                    <svg className="w-7 h-7 text-gray-400" fill="none" stroke="currentColor" strokeWidth="1.5" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5" />
                    </svg>
                  </div>
                  <p className="text-sm font-medium text-gray-700">Drop your file here, or click to browse</p>
                  <p className="text-xs text-gray-400 mt-1">HY-TEK Meet Manager results (.pdf) or ZIP with multiple PDFs</p>
                </div>
              )}
            </div>

            {step === "select" && (
              <>
                <button
                  onClick={handlePreview}
                  disabled={!selectedFile || loading}
                  className={`w-full mt-4 py-3 px-4 rounded-lg font-medium text-sm transition-colors duration-200 ${
                    !selectedFile || loading
                      ? "bg-gray-200 text-gray-400 cursor-not-allowed"
                      : "btn-primary justify-center"
                  }`}
                >
                  {loading ? "Analyzing..." : "Preview & Validate"}
                </button>
                {loading && (
                  <div className="mt-3">
                    <div className="flex items-center justify-between text-xs text-gray-500 mb-1">
                      <span>Parsing {selectedFile?.name.endsWith(".zip") ? "ZIP" : "PDF"}...</span>
                      <span>{Math.round(progress)}%</span>
                    </div>
                    <div className="w-full bg-gray-200 rounded-full h-2">
                      <div
                        className="bg-ssa-teal h-2 rounded-full transition-all duration-300"
                        style={{ width: `${progress}%` }}
                      />
                    </div>
                  </div>
                )}
              </>
            )}
          </div>
        )}

        {/* ============ STEP 2: PREVIEW ============ */}
        {step === "preview" && preview && (
          <div className="mt-6 space-y-6">
            {/* Confidence Report */}
            <div className="card overflow-hidden">
              <div className={`px-6 py-4 border-b ${
                preview.confidence_passed
                  ? "bg-ssa-teal/10 border-ssa-teal/20"
                  : "bg-red-50 border-red-200"
              }`}>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    {preview.confidence_passed ? (
                      <svg className="w-5 h-5 text-ssa-teal" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                      </svg>
                    ) : (
                      <svg className="w-5 h-5 text-red-500" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 3.75h.008v.008H12v-.008z" />
                      </svg>
                    )}
                    <h3 className="font-semibold text-ssa-navy">
                      Parse Validation — {Math.round(preview.confidence_score * 100)}%
                    </h3>
                  </div>
                  <span className="text-xs text-gray-500">Parser: {preview.parser_format}</span>
                </div>
              </div>
              <div className="px-6 py-4">
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-4">
                  {preview.confidence_checks.map((check) => (
                    <div key={check.name} className="flex items-center gap-2">
                      <span className={check.passed ? "text-ssa-teal" : "text-red-500"}>
                        {check.passed ? "✓" : "✗"}
                      </span>
                      <span className="text-xs text-gray-600">
                        {check.name.replace(/_/g, " ")}
                      </span>
                    </div>
                  ))}
                </div>
                {preview.unmatched_lines.length > 0 && (
                  <details className="mt-2">
                    <summary className="text-xs text-gray-400 cursor-pointer hover:text-gray-600">
                      {preview.unmatched_lines.length} unmatched lines (click to view)
                    </summary>
                    <div className="mt-2 bg-gray-50 rounded p-3 max-h-32 overflow-y-auto">
                      {preview.unmatched_lines.map((line, i) => (
                        <div key={i} className="text-xs font-mono text-gray-500 truncate">{line}</div>
                      ))}
                    </div>
                  </details>
                )}
              </div>
            </div>

            {/* Summary stats */}
            <div className="card p-6">
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-6">
                <div>
                  <div className="text-xs text-gray-400 uppercase">Meet</div>
                  <div className="text-sm font-semibold text-ssa-navy mt-1">{preview.meet_name}</div>
                  {preview.meet_dates && (
                    <div className="text-xs text-gray-400 mt-0.5">{preview.meet_dates}</div>
                  )}
                </div>
                <div>
                  <div className="text-xs text-gray-400 uppercase">Events</div>
                  <div className="text-2xl font-bold text-ssa-navy mt-1">{preview.events_count}</div>
                </div>
                <div>
                  <div className="text-xs text-gray-400 uppercase">Results</div>
                  <div className="text-2xl font-bold text-ssa-navy mt-1">{preview.results_count.toLocaleString()}</div>
                </div>
                <div>
                  <div className="text-xs text-gray-400 uppercase">Swimmers</div>
                  <div className="text-2xl font-bold text-ssa-navy mt-1">{preview.swimmers_count.toLocaleString()}</div>
                </div>
              </div>
            </div>

            {/* Events list with drill-down */}
            <div className="card overflow-hidden">
              <div className="px-6 py-3 bg-gray-50 border-b border-gray-200 flex flex-col sm:flex-row sm:items-center gap-3">
                <h3 className="text-sm font-semibold text-ssa-navy">
                  Parsed Events ({preview.events.length})
                </h3>
                <input
                  type="text"
                  placeholder="Filter events..."
                  value={eventSearch}
                  onChange={(e) => setEventSearch(e.target.value)}
                  className="flex-1 max-w-xs px-3 py-1.5 bg-white border border-gray-200 rounded-lg text-sm
                             focus:outline-none focus:ring-2 focus:ring-ssa-teal/20 focus:border-ssa-teal
                             placeholder:text-gray-400"
                />
              </div>
              <div className="divide-y divide-gray-100">
                {preview.events.filter((eg) =>
                  !eventSearch || eg.event.toLowerCase().includes(eventSearch.toLowerCase())
                ).map((eg) => {
                  const eventKey = `${eg.event}|${eg.round}`;
                  const isOpen = expandedEvents.has(eventKey);
                  return (
                    <div key={eventKey}>
                      {/* Event row — clickable */}
                      <button
                        onClick={() => toggleEvent(eventKey)}
                        className="w-full flex items-center justify-between px-6 py-3 hover:bg-ssa-teal/5 transition-colors text-left"
                      >
                        <div className="flex items-center gap-3">
                          <svg className={`w-4 h-4 text-gray-400 transition-transform ${isOpen ? "rotate-90" : ""}`} fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" d="M8.25 4.5l7.5 7.5-7.5 7.5" />
                          </svg>
                          <span className="text-sm font-medium text-gray-700">{eg.event}</span>
                        </div>
                        <div className="flex items-center gap-3">
                          <span className={`text-xs font-medium px-2 py-0.5 rounded ${
                            eg.round === "Final" ? "bg-ssa-navy/10 text-ssa-navy" : "bg-gray-100 text-gray-500"
                          }`}>
                            {eg.round}
                          </span>
                          <span className="text-xs text-gray-400">{eg.result_count} results</span>
                        </div>
                      </button>

                      {/* Expanded results table */}
                      {isOpen && (
                        <div className="bg-gray-50/50 border-t border-gray-100">
                          <div className="overflow-x-auto">
                            <table className="w-full">
                              <thead>
                                <tr className="bg-ssa-navy/80">
                                  <th className="px-4 py-2 text-center text-xs font-semibold text-gray-300 uppercase w-16">Place</th>
                                  <th className="px-4 py-2 text-left text-xs font-semibold text-gray-300 uppercase">Swimmer</th>
                                  <th className="px-4 py-2 text-center text-xs font-semibold text-gray-300 uppercase w-12">Age</th>
                                  <th className="px-4 py-2 text-left text-xs font-semibold text-gray-300 uppercase hidden md:table-cell">Club</th>
                                  <th className="px-4 py-2 text-right text-xs font-semibold text-gray-300 uppercase w-24">Seed</th>
                                  <th className="px-4 py-2 text-right text-xs font-semibold text-gray-300 uppercase w-24">Time</th>
                                  <th className="px-4 py-2 text-center text-xs font-semibold text-gray-300 uppercase w-20">Status</th>
                                </tr>
                              </thead>
                              <tbody className="divide-y divide-gray-100">
                                {eg.results.map((r, i) => (
                                  <tr key={i} className={`${i % 2 === 0 ? "bg-white" : "bg-gray-50/50"} ${r.is_dq ? "bg-red-50/60" : ""}`}>
                                    <td className="px-4 py-2 text-sm text-gray-500 text-center">{r.placement ?? "--"}</td>
                                    <td className="px-4 py-2 text-sm font-semibold text-gray-900">
                                      {r.is_guest && (
                                        <span className="text-xs text-amber-600 bg-amber-50 px-1 py-0.5 rounded mr-1">Guest</span>
                                      )}
                                      {r.name}
                                    </td>
                                    <td className="px-4 py-2 text-sm text-gray-600 text-center">{r.age ?? "-"}</td>
                                    <td className="px-4 py-2 text-sm text-gray-500 hidden md:table-cell">{r.team}</td>
                                    <td className="px-4 py-2 text-right text-sm font-mono text-gray-400">{r.seed_time || "--"}</td>
                                    <td className="px-4 py-2 text-right">
                                      {r.is_dq ? (
                                        <span className="text-xs font-semibold text-red-600">DQ</span>
                                      ) : (
                                        <span className="text-sm font-mono font-bold text-ssa-navy">{r.time || "--"}</span>
                                      )}
                                    </td>
                                    <td className="px-4 py-2 text-center">
                                      {r.is_dq ? (
                                        <span className="text-xs font-semibold text-red-600 bg-red-100 px-2 py-0.5 rounded-full">DQ</span>
                                      ) : r.qualifier ? (
                                        <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${
                                          r.qualifier === "qMTS" ? "bg-ssa-teal/10 text-ssa-teal" : "bg-blue-50 text-blue-700"
                                        }`}>
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
                      )}
                    </div>
                  );
                })}
              </div>
            </div>

            {/* Replace toggle + Confirm button */}
            <div className="max-w-2xl">
              <label className="flex items-center gap-3 px-1 cursor-pointer">
                <input
                  type="checkbox"
                  checked={replaceMode}
                  onChange={(e) => setReplaceMode(e.target.checked)}
                  className="w-4 h-4 rounded border-gray-300 text-ssa-teal focus:ring-ssa-teal"
                />
                <div>
                  <span className="text-sm font-medium text-gray-700">Replace existing results</span>
                  <p className="text-xs text-gray-400">
                    Deletes all previous results for this meet before importing.
                  </p>
                </div>
              </label>

              <div className="flex gap-3 mt-4">
                <button
                  onClick={handleReset}
                  className="px-6 py-3 rounded-lg font-medium text-sm border border-gray-200 text-gray-600 hover:bg-gray-50 transition-colors"
                >
                  Cancel
                </button>
                <button
                  onClick={handleConfirm}
                  disabled={!preview.confidence_passed}
                  className={`flex-1 py-3 px-4 rounded-lg font-medium text-sm transition-colors duration-200 ${
                    !preview.confidence_passed
                      ? "bg-gray-200 text-gray-400 cursor-not-allowed"
                      : "btn-primary justify-center"
                  }`}
                >
                  Confirm Upload — {preview.results_count.toLocaleString()} results
                </button>
              </div>
            </div>
          </div>
        )}

        {/* ============ UPLOADING STATE ============ */}
        {step === "uploading" && (
          <div className="max-w-2xl mt-6 card p-8">
            <p className="text-sm font-medium text-ssa-navy mb-3 text-center">Uploading and saving to database...</p>
            <div className="flex items-center justify-between text-xs text-gray-500 mb-1">
              <span>Processing...</span>
              <span>{Math.round(progress)}%</span>
            </div>
            <div className="w-full bg-gray-200 rounded-full h-2">
              <div
                className="bg-ssa-teal h-2 rounded-full transition-all duration-300"
                style={{ width: `${progress}%` }}
              />
            </div>
          </div>
        )}

        {/* ============ STEP 3: DONE ============ */}
        {step === "done" && result && (
          <div className="max-w-2xl mt-6 space-y-4">
            <div className="card overflow-hidden">
              <div className="bg-ssa-teal/10 px-6 py-4 border-b border-ssa-teal/20">
                <div className="flex items-center gap-2">
                  <svg className="w-5 h-5 text-ssa-teal" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                  </svg>
                  <h3 className="font-semibold text-ssa-navy">Upload Successful</h3>
                </div>
              </div>
              <div className="px-6 py-4 space-y-3">
                <div className="flex justify-between text-sm">
                  <span className="text-gray-500">Meet</span>
                  <span className="font-medium text-gray-900">{result.meet.name}</span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-gray-500">Results Stored</span>
                  <span className="font-medium text-gray-900">{result.results_count.toLocaleString()}</span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-gray-500">New Swimmers</span>
                  <span className="font-medium text-gray-900">{result.swimmers_count}</span>
                </div>
                {result.duplicates_skipped > 0 && (
                  <div>
                    <div className="flex justify-between text-sm">
                      <span className="text-gray-500">Duplicates Skipped</span>
                      <span className="font-medium text-amber-600">{result.duplicates_skipped}</span>
                    </div>
                    {result.duplicates.length > 0 && (
                      <details className="mt-2">
                        <summary className="text-xs text-amber-600 cursor-pointer hover:text-amber-700">
                          View {result.duplicates.length} skipped entries
                        </summary>
                        <div className="mt-2 bg-amber-50 rounded p-3 max-h-48 overflow-y-auto">
                          <table className="w-full text-xs">
                            <thead>
                              <tr className="text-left text-gray-500">
                                <th className="pb-1">Event</th>
                                <th className="pb-1">Name</th>
                                <th className="pb-1">Round</th>
                                <th className="pb-1 text-right">Time</th>
                              </tr>
                            </thead>
                            <tbody>
                              {result.duplicates.map((d, i) => (
                                <tr key={i} className="border-t border-amber-100">
                                  <td className="py-1 text-gray-600">{d.event}</td>
                                  <td className="py-1 text-gray-700 font-medium">{d.name}</td>
                                  <td className="py-1 text-gray-500">{d.round}</td>
                                  <td className="py-1 text-right font-mono text-gray-600">{d.time || "--"}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      </details>
                    )}
                  </div>
                )}
              </div>
              <div className="px-6 py-4 bg-gray-50 border-t border-gray-100 flex gap-4">
                <a href="/results" className="text-sm font-medium text-ssa-teal hover:text-ssa-navy transition-colors">
                  View results &rarr;
                </a>
                <button onClick={handleReset} className="text-sm font-medium text-gray-500 hover:text-gray-700 transition-colors">
                  Upload another
                </button>
              </div>
            </div>
          </div>
        )}

        {/* Error */}
        {error && (
          <div className="max-w-2xl card mt-6 p-4 bg-red-50 border-red-200">
            <div className="flex items-start gap-3">
              <svg className="w-5 h-5 text-red-500 mt-0.5 flex-shrink-0" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 3.75h.008v.008H12v-.008z" />
              </svg>
              <div>
                <p className="text-sm font-medium text-red-800">{error}</p>
                <p className="text-xs text-red-600 mt-1">
                  Make sure the backend is running and the file is a valid HY-TEK PDF.
                </p>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
