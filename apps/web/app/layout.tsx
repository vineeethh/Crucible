import "@crucible/ui/tokens.css";

import type { Metadata } from "next";
import type { ReactNode } from "react";

import { AppShell } from "./shell";

export const metadata: Metadata = {
  title: "Crucible",
  description: "Evaluation and reliability platform for LLM agents",
};

// Re-applies the persisted theme before first paint so a stored choice never
// flashes the opposite theme on load. Must stay tiny and synchronous.
const THEME_BOOT = `try{var t=localStorage.getItem("cru-theme");if(t==="light"||t==="dark")document.documentElement.setAttribute("data-theme",t)}catch(e){}`;

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      {/* Browser extensions (Grammarly, password managers, …) inject attributes
          onto <body> before React hydrates; suppressHydrationWarning stops that
          from being reported as a mismatch. It suppresses only this element's
          attribute diff, not its subtree. */}
      <body suppressHydrationWarning>
        <script dangerouslySetInnerHTML={{ __html: THEME_BOOT }} />
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
