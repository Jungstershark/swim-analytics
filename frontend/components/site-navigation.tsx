"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const primaryLinks = [
  { label: "Home", href: "/" },
  { label: "Meets", href: "/meets" },
  { label: "Swimmers", href: "/swimmers" },
  { label: "Results", href: "/results" },
];

const actionLinks = [
  { label: "Upload", href: "/upload" },
  { label: "Sources", href: "/admin/sources" },
];

function isCurrent(pathname: string, href: string) {
  return href === "/" ? pathname === "/" : pathname === href || pathname.startsWith(`${href}/`);
}

function NavLink({ label, href, pathname, mobile = false }: { label: string; href: string; pathname: string; mobile?: boolean }) {
  const current = isCurrent(pathname, href);
  return (
    <Link
      href={href}
      aria-current={current ? "page" : undefined}
      className={mobile
        ? `flex min-h-11 min-w-0 items-center justify-center px-1 text-xs font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ssa-teal-light ${current ? "bg-white/12 text-white" : "text-slate-300 hover:bg-white/10 hover:text-white"}`
        : `rounded-md px-3 py-2 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ssa-teal-light ${current ? "bg-white/12 text-white" : "text-gray-300 hover:bg-white/10 hover:text-white"}`}
    >
      {label}
    </Link>
  );
}

export default function SiteNavigation({ variant }: { variant: "desktop" | "mobile" }) {
  const pathname = usePathname();
  const actionCurrent = actionLinks.some(({ href }) => isCurrent(pathname, href));

  if (variant === "desktop") {
    return (
      <nav className="hidden items-center gap-1 md:flex" aria-label="Desktop">
        {primaryLinks.map((link) => <NavLink key={link.href} {...link} pathname={pathname} />)}
        {actionLinks.map((link) => <NavLink key={link.href} {...link} pathname={pathname} />)}
      </nav>
    );
  }

  return (
      <nav className="grid grid-cols-5 border-t border-ssa-navy-light md:hidden" aria-label="Primary">
        {primaryLinks.map((link) => <NavLink key={link.href} {...link} pathname={pathname} mobile />)}
        <details className="group relative min-w-0" open={actionCurrent || undefined}>
          <summary role="button" aria-label="Actions" aria-current={actionCurrent ? "page" : undefined} className={`flex min-h-11 cursor-pointer list-none items-center justify-center px-1 text-xs font-semibold transition-colors hover:bg-white/10 hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ssa-teal-light [&::-webkit-details-marker]:hidden ${actionCurrent ? "bg-white/12 text-white" : "text-slate-300"}`}>
            Actions
          </summary>
          <div className="absolute right-1 top-full z-50 mt-2 w-36 overflow-hidden rounded-xl bg-white py-1 shadow-lg ring-1 ring-black/10">
            {actionLinks.map(({ label, href }) => (
              <Link
                key={href}
                href={href}
                aria-current={isCurrent(pathname, href) ? "page" : undefined}
                className="flex min-h-11 items-center px-4 text-sm font-medium text-ssa-navy hover:bg-ssa-teal/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ssa-teal"
              >
                {label}
              </Link>
            ))}
          </div>
        </details>
      </nav>
  );
}
