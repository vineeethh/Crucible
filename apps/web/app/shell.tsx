"use client";

// The product shell: skip link, sticky header with the primary navigation
// (active state from the current path), and a theme toggle. Client-only so it
// can read the pathname; all data fetching stays in Server Components.
import { ThemeToggle } from "@crucible/ui";
import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

const NAV = [
  { href: "/dashboard", label: "Reliability" },
  { href: "/datasets", label: "Datasets" },
  { href: "/runs", label: "Runs" },
  { href: "/reviews", label: "Reviews" },
  { href: "/evaluations", label: "Evaluations" },
  { href: "/settings", label: "Settings" },
];

/** The Crucible mark: a vessel over a flame line — one weight, one color. */
function BrandMark() {
  return (
    <svg
      className="cru-brand-mark"
      width="18"
      height="18"
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
    >
      <path
        d="M4.5 5h15l-2.1 8.4a5.6 5.6 0 0 1-10.8 0L4.5 5Z"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinejoin="round"
      />
      <path
        d="M8.5 21h7"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
      />
    </svg>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname() ?? "";
  return (
    <>
      <a className="cru-skip" href="#main">
        Skip to content
      </a>
      <header className="cru-header">
        <div className="cru-header-inner">
          <Link className="cru-brand" href="/">
            <BrandMark />
            Crucible
          </Link>
          <nav className="cru-nav" aria-label="Primary">
            {NAV.map((item) => {
              const active =
                pathname === item.href || pathname.startsWith(`${item.href}/`);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  aria-current={active ? "page" : undefined}
                >
                  {item.label}
                </Link>
              );
            })}
          </nav>
          <ThemeToggle />
        </div>
      </header>
      <main id="main" className="cru-main">
        {children}
      </main>
    </>
  );
}
