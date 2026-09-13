import type { Metadata, Viewport } from "next";
import Link from "next/link";
import { Inter } from "next/font/google";
import SiteNavigation from "@/components/site-navigation";
import "./globals.css";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter" });

export const metadata: Metadata = {
  title: "Swim Analytics | SSA",
  description: "Singapore Swimming Association meet results and swimmer performance analytics.",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={inter.variable} data-scroll-behavior="smooth">
      <body className={`${inter.className} flex min-h-screen min-w-0 flex-col overflow-x-clip bg-gray-50`}>
        <header className="sticky top-0 z-50 bg-ssa-navy shadow-sm">
          <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
            <div className="flex h-16 items-center justify-between">
              <Link href="/" className="flex min-h-11 min-w-0 items-center gap-3 rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ssa-teal-light">
                <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-ssa-teal" aria-hidden="true">
                  <svg className="h-5 w-5 text-white" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M2 12c2-2 4-3 6-3s4 1 6 3 4 3 6 3 4-1 6-3" />
                    <path d="M2 6c2-2 4-3 6-3s4 1 6 3 4 3 6 3 4-1 6-3" />
                    <path d="M2 18c2-2 4-3 6-3s4 1 6 3 4 3 6 3 4-1 6-3" />
                  </svg>
                </span>
                <span className="truncate text-lg font-bold tracking-tight text-white">Swim Analytics</span>
                <span className="hidden text-xs font-medium uppercase tracking-wider text-ssa-teal-light sm:inline">SSA</span>
              </Link>
              <SiteNavigation variant="desktop" />
            </div>
            <SiteNavigation variant="mobile" />
          </div>
        </header>

        <main className="min-w-0 flex-1">{children}</main>

        <footer className="border-t border-ssa-navy-light bg-ssa-navy text-gray-400">
          <div className="mx-auto flex max-w-7xl flex-col items-center justify-between gap-3 px-4 py-7 text-center sm:flex-row sm:px-6 sm:text-left lg:px-8">
            <p className="text-sm text-gray-400">Singapore Swimming Association · Swim Analytics</p>
            <p className="text-xs text-gray-500">&copy; {new Date().getFullYear()} SSA</p>
          </div>
        </footer>
      </body>
    </html>
  );
}
