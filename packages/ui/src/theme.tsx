"use client";

/*
 * Theme toggle. Persists the choice in localStorage and stamps `data-theme` on
 * <html>, which the token stylesheet honours over the OS `prefers-color-scheme`
 * in both directions. React-only — no Next dependency — so it lives in the
 * design system and works anywhere.
 *
 * The app's root layout runs a tiny inline script before first paint that
 * re-applies the stored theme, so toggling never flashes on navigation.
 */
import { useEffect, useState } from "react";

type Theme = "light" | "dark";

function systemTheme(): Theme {
  if (typeof window === "undefined") return "dark";
  return window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
}

export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme | null>(null);

  useEffect(() => {
    const stored = window.localStorage.getItem("cru-theme") as Theme | null;
    setTheme(stored ?? systemTheme());
  }, []);

  useEffect(() => {
    if (theme === null) return;
    document.documentElement.setAttribute("data-theme", theme);
    window.localStorage.setItem("cru-theme", theme);
  }, [theme]);

  const next = theme === "light" ? "dark" : "light";
  return (
    <button
      type="button"
      className="cru-btn cru-btn-ghost cru-btn-icon"
      aria-label={`Switch to ${next} theme`}
      title={`Switch to ${next} theme`}
      onClick={() => setTheme(next)}
    >
      <span aria-hidden style={{ fontSize: "0.95rem", lineHeight: 1 }}>
        {theme === "light" ? "☾" : "☀"}
      </span>
    </button>
  );
}
