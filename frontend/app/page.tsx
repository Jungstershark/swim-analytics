"use client";

import Link from "next/link";
import { useEffect, useState, type ReactNode } from "react";
import { getBrowserOverview, type BrowserOverview } from "@/lib/api";

const icons = {
  swimmers: <path strokeLinecap="round" strokeLinejoin="round" d="M15 19.1a9.4 9.4 0 002.6.4 9.3 9.3 0 004.1-1 4.1 4.1 0 00-7.5-2.4M15 19.1A12.3 12.3 0 018.6 21c-2.3 0-4.5-.6-6.4-1.8a6.4 6.4 0 0112-3.1M12 6.4a3.4 3.4 0 11-6.8 0 3.4 3.4 0 016.8 0z" />,
  meets: <path strokeLinecap="round" strokeLinejoin="round" d="M6.8 3v2.3M17.3 3v2.3M3 9h18M5.3 5.3h13.5A2.3 2.3 0 0121 7.5v11.3a2.3 2.3 0 01-2.3 2.2H5.3A2.3 2.3 0 013 18.8V7.5a2.3 2.3 0 012.3-2.2z" />,
  results: <path strokeLinecap="round" strokeLinejoin="round" d="M4 19V9m5 10V5m5 14v-7m5 7V3" />,
  relays: <path strokeLinecap="round" strokeLinejoin="round" d="M4 7h11m0 0l-3-3m3 3l-3 3M20 17H9m0 0l3 3m-3-3l3-3" />,
};

export default function Home() {
  const [overview, setOverview] = useState<BrowserOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    getBrowserOverview()
      .then(setOverview)
      .catch((e) => setError(e.message || "Could not load the dashboard"))
      .finally(() => setLoading(false));
  }, []);

  const combinedResults = overview
    ? overview.counts.individual_results + overview.counts.relay_results
    : null;

  return (
    <div className="min-h-screen min-w-0">
      <section className="bg-ssa-navy">
        <div className="mx-auto max-w-7xl px-4 py-12 sm:px-6 sm:py-16 lg:px-8">
          <div className="max-w-3xl">
            <h1 className="max-w-2xl text-3xl font-bold leading-tight tracking-tight text-white sm:text-5xl">
              Singapore swim results, ready to explore
            </h1>
            <p className="mt-4 max-w-2xl text-base leading-relaxed text-slate-300 sm:text-lg">
              Browse meets, find swimmers, and follow individual and relay performances from official results.
            </p>
            <div className="mt-7 flex flex-wrap gap-3">
              <Link href="/results" className="btn-primary min-h-11">Browse results</Link>
              <Link href="/upload" className="btn-outline min-h-11 border-slate-400 text-white hover:border-white hover:bg-white/10">Upload results</Link>
            </div>
          </div>
        </div>
      </section>

      <section className="relative z-10 mx-auto -mt-5 max-w-7xl px-4 sm:px-6 lg:px-8" aria-label="Platform totals">
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <MetricLink label="Swimmers" value={overview?.counts.swimmers} href="/swimmers" icon={icons.swimmers} loading={loading} />
          <MetricLink label="Meets" value={overview?.counts.meets} href="/meets" icon={icons.meets} loading={loading} />
          <MetricLink label="Results" value={combinedResults} href="/results?row_type=all" icon={icons.results} loading={loading} />
          <MetricLink label="Relay results" value={overview?.counts.relay_results} href="/results?row_type=relay" icon={icons.relays} loading={loading} />
        </div>
      </section>

      <section className="mx-auto max-w-7xl px-4 py-10 sm:px-6 sm:py-12 lg:px-8">
        <div className="flex items-center justify-between gap-4">
          <h2 className="text-xl font-semibold text-ssa-navy">Recent meets</h2>
          <Link href="/meets" className="flex min-h-11 items-center text-sm font-semibold text-ssa-teal hover:text-ssa-teal-dark focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ssa-teal">View all</Link>
        </div>

        <div className="mt-3 overflow-hidden rounded-xl bg-white shadow-sm ring-1 ring-gray-200">
          {loading ? (
            <div className="space-y-px bg-gray-100" aria-label="Loading recent meets">
              {[1, 2, 3].map((item) => <div key={item} className="h-20 animate-pulse bg-white p-4"><div className="h-4 w-2/3 rounded bg-gray-200" /></div>)}
            </div>
          ) : error ? (
            <div role="alert" className="p-8 text-center">
              <p className="font-medium text-red-700">Could not load dashboard data</p>
              <p className="mt-1 text-sm text-gray-500">Refresh the page to try again.</p>
            </div>
          ) : overview && overview.latest_meets.length > 0 ? (
            <div className="divide-y divide-gray-100">
              {overview.latest_meets.map((item) => (
                <Link key={item.id} href={`/meets/${item.id}`} className="flex min-h-20 min-w-0 items-center gap-3 p-4 transition-colors hover:bg-ssa-teal/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ssa-teal">
                  <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-ssa-navy/5 text-ssa-navy" aria-hidden="true">
                    <svg className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="1.7" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" d="M6.8 3v2.3M17.3 3v2.3M3 9h18M5.3 5.3h13.5A2.3 2.3 0 0121 7.5v11.3a2.3 2.3 0 01-2.3 2.2H5.3A2.3 2.3 0 013 18.8V7.5a2.3 2.3 0 012.3-2.2z" /></svg>
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-semibold text-gray-900">{item.name}</span>
                    <span className="mt-1 block truncate text-xs text-gray-500">{item.location || "Location not listed"}</span>
                  </span>
                  <time className="shrink-0 text-xs font-medium text-gray-500">{formatDate(item.date)}</time>
                </Link>
              ))}
            </div>
          ) : (
            <div className="p-8 text-center">
              <p className="text-sm text-gray-600">No meets are available yet.</p>
              <Link href="/upload" className="mt-2 inline-flex min-h-11 items-center font-semibold text-ssa-teal">Upload results</Link>
            </div>
          )}
        </div>
      </section>
    </div>
  );
}

function MetricLink({ label, value, href, icon, loading }: { label: string; value: number | null | undefined; href: string; icon: ReactNode; loading: boolean }) {
  return (
    <Link href={href} className="group min-w-0 rounded-xl bg-white p-4 shadow-sm ring-1 ring-gray-200 transition hover:-translate-y-0.5 hover:shadow-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ssa-teal sm:p-5">
      <span className="flex items-start justify-between gap-2">
        <span className="min-w-0">
          <span className="block text-xs font-semibold text-gray-600 sm:text-sm">{label}</span>
          {loading ? <span className="mt-2 block h-7 w-16 animate-pulse rounded bg-gray-200" /> : <span className="mt-1 block text-2xl font-bold tracking-tight text-ssa-navy sm:text-3xl">{value == null ? "—" : value.toLocaleString()}</span>}
        </span>
        <span className="hidden rounded-lg bg-ssa-teal/10 p-2 text-ssa-teal sm:block" aria-hidden="true">
          <svg className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="1.7" viewBox="0 0 24 24">{icon}</svg>
        </span>
      </span>
    </Link>
  );
}

function formatDate(value: string | null) {
  if (!value) return "Date unknown";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString("en-SG", { day: "numeric", month: "short", year: "numeric" });
}
