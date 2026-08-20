"use client";

// Route error boundary (App Router). Any error a page throws that is NOT a
// recoverable "setup required" state (a stale key or unreachable API are handled
// inline by the pages) lands here — so a user sees a calm, actionable panel with
// a retry, never a raw stack. Client component by contract.
import { useEffect } from "react";

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // Surface it for the operator; the message shown to the user stays generic.
    console.error(error);
  }, [error]);

  return (
    <div role="alert">
      <h1 className="cru-page-title">Something went wrong</h1>
      <p className="cru-page-lede">
        The page hit an unexpected error. This has been logged. You can retry, or
        check that the API is running and reachable.
      </p>
      <div className="cru-callout danger">
        <p className="cru-callout-body" style={{ fontFamily: "var(--font-mono)" }}>
          {error.message || "Unexpected error"}
          {error.digest ? ` (ref ${error.digest})` : ""}
        </p>
      </div>
      <div className="cru-btn-row">
        <button type="button" className="cru-btn cru-btn-primary" onClick={() => reset()}>
          Try again
        </button>
        <a className="cru-btn" href="/">
          Go home
        </a>
      </div>
    </div>
  );
}
