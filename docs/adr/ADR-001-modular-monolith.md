# ADR-001: Modular monolith plus workers, not microservices

Status: Accepted · Date: 2026-07-14

## Context
One developer must ship a multi-tenant platform (API, agent worker, eval runner, web)
in ~6 months. The system needs clear internal boundaries (domain / application /
adapters) but cannot afford distributed-system operational tax.

## Decision
Build a monorepo modular monolith: `apps/api`, `apps/worker`, `apps/web` composed from
`packages/*` with enforced import boundaries (`domain` imports no framework; `application`
depends on ports, not concrete adapters). Deploy API and worker as separate processes of
the same codebase.

## Alternatives considered
- **Independent microservices** — rejected: premature deployment, tracing, and schema
  complexity; no team-scaling pressure justifies it.
- **Single flat application** — rejected: boundary erosion makes the later extraction of
  the eval runner or sandbox client expensive and untestable.

## Consequences
- One deployment pipeline, one dependency graph, simple local Compose stack.
- Boundary rules must be enforced by lint/import checks, not intention.
- Later extraction of a service is possible because ports/adapters exist from Phase 1.

## Revisit trigger
Sustained multi-contributor development, or a component (e.g., eval runner) with a
demonstrably different scaling/availability profile.
