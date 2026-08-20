# @crucible/ui

The Crucible design system (Phase 7): theme tokens and reusable product
components, consumed by `apps/web`.

- **Source-only.** Ships as TypeScript/TSX with no build step; Next transpiles it
  via `transpilePackages`. It is framework-agnostic React (no Next dependency) so
  the components render in Server Components and are trivial to test.
- **Tokens** (`src/tokens.css`): colour/space/radius/type as CSS custom
  properties, themed for light and dark via `prefers-color-scheme` with a
  `data-theme` override (set by `ThemeToggle`) that wins in both directions.
- **Components** (`src/index.ts`): `StatusBadge`, `SeverityTag`, `GateBadge`,
  `DataTable`, `Panel`, `MetricCard` / `MetricGrid`, `Callout`, `KeyValue`,
  `Mono`, `Tag`, `Pre`, and the observability views `Trace` and `ConfigView`.

Accessibility is built in: status is never conveyed by colour alone (a dot plus a
text label), focus is always visible, and layouts are responsive.

See [docs/architecture/web-frontend.md](../../docs/architecture/web-frontend.md).
