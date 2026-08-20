// Settings: the authenticated identity behind this session (the org-scoped API
// key, validated server-side), the effective permissions, and the org's API
// keys. This is where a reviewer confirms *who they are* and *what they can do*
// — the UI mirrors the API's authorization, it does not invent its own.
import { Callout, DataTable, KeyValue, Mono, Panel, StatusBadge, Tag } from "@crucible/ui";

import { getBudget, getMe, listApiKeys, setupMessage } from "@/lib/api";

import { SetupRequired } from "../_setup";
import { BudgetForm } from "./budget-form";

export const dynamic = "force-dynamic";

export default async function SettingsPage() {
  let me, keys, budget;
  try {
    me = await getMe();
    keys = await listApiKeys();
    budget = await getBudget();
  } catch (error) {
    const setup = setupMessage(error);
    if (setup) return <SetupRequired message={setup} />;
    throw error;
  }

  return (
    <>
      <h1 className="cru-page-title">Settings</h1>
      <p className="cru-page-lede">
        The identity and authority behind this session. Authorization is enforced by the API on
        every request; the UI only reflects it.
      </p>

      <Panel title="Identity">
        <KeyValue
          items={[
            ["organization", <Mono key="o">{me.organization_id}</Mono>],
            ["actor type", <StatusBadge key="t" status={me.actor_type} />],
            ["actor id", <Mono key="a">{me.actor_id}</Mono>],
            ["role", <Tag key="r">{me.role}</Tag>],
          ]}
        />
      </Panel>

      <Panel title={`Permissions (${me.permissions.length})`} pad>
        <div className="cru-cluster">
          {me.permissions.map((p) => (
            <Tag key={p}>{p}</Tag>
          ))}
        </div>
      </Panel>

      <Panel title="Monthly budget" pad>
        <p className="cru-muted" style={{ margin: "0 0 var(--space-4)", fontSize: "0.9rem" }}>
          {budget.monthly_limit_usd === null
            ? "No budget is configured — run admission is unenforced."
            : `Limit $${budget.monthly_limit_usd} · spent $${budget.month_spend_usd.toFixed(4)} this month · remaining $${budget.remaining_usd?.toFixed(4)}.`}
        </p>
        <BudgetForm currentLimit={budget.monthly_limit_usd} />
      </Panel>

      <Panel title="API keys">
        <DataTable
          headers={["Name", "Prefix", "Role", "Scopes", "Status"]}
          empty="No API keys in this organization."
          rows={keys.map((k) => [
            k.name,
            <Mono key="p">{k.prefix}</Mono>,
            <Tag key="r">{k.role}</Tag>,
            k.scopes ? k.scopes.length : <span className="cru-muted">full role</span>,
            <StatusBadge
              key="s"
              status={k.revoked_at ? "invalid" : k.expires_at ? "waiting_review" : "ready"}
            />,
          ])}
        />
      </Panel>

      <Callout tone="info" title="Managing keys">
        Keys are minted and revoked through the API (<Mono>POST/DELETE /v1/api-keys</Mono>) or{" "}
        <Mono>scripts/bootstrap_org.py</Mono>. A key can never exceed its creator&rsquo;s role — the
        privilege-escalation guard lives in the API, not here.
      </Callout>
    </>
  );
}
