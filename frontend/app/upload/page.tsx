"use client";

import { useState } from "react";
import { uploadResults, type UploadResponse } from "@/lib/api";

export default function UploadPage() {
  const [uploading, setUploading] = useState(false);
  const [result, setResult] = useState<UploadResponse | null>(null);
  const [error, setError] = useState("");
  const [dragOver, setDragOver] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [replaceMode, setReplaceMode] = useState(false);

  async function handleUpload() {
    if (!selectedFile) return;
    setUploading(true);
    setResult(null);
    setError("");

    try {
      const res = await uploadResults(selectedFile, { replace: replaceMode });
      setResult(res);
      setSelectedFile(null);
    } catch (e: any) {
      setError(e.message || "Failed to upload file. Please try again.");
    } finally {
      setUploading(false);
    }
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
    setResult(null);
    setSelectedFile(file);
  }

  function handleDrop(e: React.DragEvent) {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files[0];
    handleFileSelect(file || null);
  }

  return (
    <div className="min-h-screen">
      {/* Page Header */}
      <div className="bg-white border-b border-gray-200">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
          <nav className="flex items-center gap-2 text-sm mb-4">
            <a href="/" className="text-gray-500 hover:text-ssa-navy transition-colors">
              Dashboard
            </a>
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

      <div className="max-w-2xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Drop zone */}
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
              <p className="text-sm font-medium text-gray-700">
                Drop your file here, or click to browse
              </p>
              <p className="text-xs text-gray-400 mt-1">
                HY-TEK Meet Manager results (.pdf) or ZIP with multiple PDFs
              </p>
            </div>
          )}
        </div>

        {/* Replace toggle */}
        <label className="flex items-center gap-3 mt-4 px-1 cursor-pointer">
          <input
            type="checkbox"
            checked={replaceMode}
            onChange={(e) => setReplaceMode(e.target.checked)}
            className="w-4 h-4 rounded border-gray-300 text-ssa-teal focus:ring-ssa-teal"
          />
          <div>
            <span className="text-sm font-medium text-gray-700">Replace existing results</span>
            <p className="text-xs text-gray-400">
              Deletes all previous results for this meet before importing. Use when re-uploading corrected files.
            </p>
          </div>
        </label>

        {/* Upload button */}
        <button
          onClick={handleUpload}
          disabled={!selectedFile || uploading}
          className={`w-full mt-4 py-3 px-4 rounded-lg font-medium text-sm transition-colors duration-200 ${
            !selectedFile || uploading
              ? "bg-gray-200 text-gray-400 cursor-not-allowed"
              : "btn-primary justify-center"
          }`}
        >
          {uploading ? (
            <span className="flex items-center justify-center gap-2">
              <svg className="animate-spin w-4 h-4" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
              {selectedFile?.name.endsWith(".zip") ? "Extracting & Parsing..." : "Parsing PDF..."}
            </span>
          ) : (
            `Upload & Parse${replaceMode ? " (Replace)" : ""}`
          )}
        </button>

        {/* Success */}
        {result && (
          <div className="card mt-6 overflow-hidden">
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
                <span className="text-gray-500">Events Parsed</span>
                <span className="font-medium text-gray-900">{result.events_count}</span>
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
                <div className="flex justify-between text-sm">
                  <span className="text-gray-500">Duplicates Skipped</span>
                  <span className="font-medium text-amber-600">{result.duplicates_skipped}</span>
                </div>
              )}
              {result.results_count === 0 && (
                <p className="text-xs text-amber-600 bg-amber-50 rounded px-3 py-2">
                  No new results were added. This file may have already been uploaded.
                </p>
              )}
            </div>
            <div className="px-6 py-4 bg-gray-50 border-t border-gray-100">
              <a href="/results" className="text-sm font-medium text-ssa-teal hover:text-ssa-teal-dark transition-colors">
                View results &rarr;
              </a>
            </div>
          </div>
        )}

        {/* Error */}
        {error && (
          <div className="card mt-6 p-4 bg-red-50 border-red-200">
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

        {/* Info box */}
        <div className="card mt-8 p-5">
          <h2 className="text-sm font-semibold text-ssa-navy mb-3">
            Supported Formats
          </h2>
          <div className="space-y-2 text-sm text-gray-600">
            <p>
              <strong>PDF:</strong> HY-TEK Meet Manager 8.0 result exports with event results,
              swimmer names, times, placements, splits, and DQ information.
            </p>
            <p>
              <strong>ZIP:</strong> A zip file containing multiple PDF result files from the same competition
              (e.g., Day 1 Session 1, Day 1 Session 2, etc.). All PDFs are parsed and grouped under one meet.
            </p>
            <p className="text-xs text-gray-400">
              Duplicate results are automatically detected and skipped. Toggle &quot;Replace existing results&quot;
              to re-import corrected files.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
