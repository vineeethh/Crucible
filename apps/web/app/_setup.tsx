import { Callout, Pre } from "@crucible/ui";

// Shown whenever a Server Component cannot reach the API because no credential
// is configured. The credential *is* the session in this deployment model: an
// org-scoped API key, validated server-side, that never reaches the browser.
export function SetupRequired({ message }: { message: string }) {
  return (
    <>
      <h1 className="cru-page-title">Setup required</h1>
      <p className="cru-page-lede">{message}</p>
      <Callout tone="info" title="Mint a credential">
        Bootstrap an organization and owner API key, then point the web app at it.
      </Callout>
      <Pre>
        {`uv run python scripts/bootstrap_org.py --slug demo
# copy the printed token, then in apps/web/.env.local:
CRUCIBLE_API_URL=http://localhost:8100
CRUCIBLE_API_KEY=ck_...`}
      </Pre>
      <p className="cru-muted" style={{ fontSize: "0.85rem" }}>
        Prefer sample data? Run <code className="cru-mono">uv run python scripts/seed_demo.py</code>{" "}
        to create a demo org, dataset, and a few runs, then use the key it prints.
      </p>
    </>
  );
}
