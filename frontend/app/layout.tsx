import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter" });

export const metadata: Metadata = {
  title: "Swim Analytics | SSA",
  description:
    "Singapore Swimming Association - Official meet results platform for tracking swimmer performance, race times, and competition analytics.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className={inter.variable}>
      <body className={`${inter.className} bg-gray-50 min-h-screen flex flex-col`}>
        {/* Navigation */}
        <header className="sticky top-0 z-50 bg-ssa-navy border-b border-ssa-navy-light">
          <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
            <div className="flex items-center justify-between h-16">
              {/* Brand */}
              <a href="/" className="flex items-center gap-3">
                <div className="w-9 h-9 rounded-lg bg-ssa-teal flex items-center justify-center">
                  <svg
                    className="w-5 h-5 text-white"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  >
                    <path d="M2 12c2-2 4-3 6-3s4 1 6 3 4 3 6 3 4-1 6-3" />
                    <path d="M2 6c2-2 4-3 6-3s4 1 6 3 4 3 6 3 4-1 6-3" />
                    <path d="M2 18c2-2 4-3 6-3s4 1 6 3 4 3 6 3 4-1 6-3" />
                  </svg>
                </div>
                <div>
                  <span className="text-white font-bold text-lg tracking-tight">
                    Swim Analytics
                  </span>
                  <span className="hidden sm:inline text-ssa-teal-light text-xs font-medium ml-2 uppercase tracking-wider">
                    SSA
                  </span>
                </div>
              </a>

              {/* Navigation Links */}
              <nav className="hidden md:flex items-center gap-1">
                <a
                  href="/"
                  className="px-3 py-2 rounded-md text-sm font-medium text-gray-300 hover:text-white hover:bg-white/10 transition-colors"
                >
                  Dashboard
                </a>
                <a
                  href="/upload"
                  className="px-3 py-2 rounded-md text-sm font-medium text-gray-300 hover:text-white hover:bg-white/10 transition-colors"
                >
                  Upload
                </a>
                <a
                  href="/results"
                  className="px-3 py-2 rounded-md text-sm font-medium text-gray-300 hover:text-white hover:bg-white/10 transition-colors"
                >
                  Results
                </a>
                <a
                  href="/analytics"
                  className="px-3 py-2 rounded-md text-sm font-medium text-gray-300 hover:text-white hover:bg-white/10 transition-colors"
                >
                  Analytics
                </a>
              </nav>

              {/* Mobile menu button */}
              <button
                className="md:hidden p-2 rounded-md text-gray-300 hover:text-white hover:bg-white/10"
                aria-label="Open navigation menu"
              >
                <svg
                  className="w-6 h-6"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  viewBox="0 0 24 24"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    d="M4 6h16M4 12h16M4 18h16"
                  />
                </svg>
              </button>
            </div>
          </div>
        </header>

        {/* Main Content */}
        <main className="flex-1">{children}</main>

        {/* Footer */}
        <footer className="bg-ssa-navy text-gray-400 border-t border-ssa-navy-light">
          <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
            <div className="flex flex-col sm:flex-row items-center justify-between gap-4">
              <div className="flex items-center gap-2 text-sm">
                <span className="text-gray-500">
                  Singapore Swimming Association
                </span>
                <span className="text-gray-600">|</span>
                <span className="text-gray-500">Swim Analytics Platform</span>
              </div>
              <div className="text-xs text-gray-500">
                &copy; {new Date().getFullYear()} SSA. All rights reserved.
              </div>
            </div>
          </div>
        </footer>
      </body>
    </html>
  );
}
