# ADR-003: External/microVM sandbox in production; Docker only for local development

Status: Accepted · Date: 2026-07-14

## Context
The agent executes model-generated Python. Generated code is hostile until contained
(charter principle 4). Containers alone are not a universal security boundary, and the
API process or a shared CI runner must never share a trust boundary with generated code.

## Decision
Production/staging execute generated code in a managed microVM sandbox (E2B-class
provider) behind an executor port. Local development uses a fixed, hardened Docker
runner. Tests use a fake deterministic executor. The backend constructs a fixed sandbox
configuration; the model never selects image, flags, mounts, packages, or network.

## Alternatives considered
- **In-process execution** — rejected: unsafe by definition.
- **API-managed Docker socket in production** — rejected: Docker daemon control is
  high-privilege; socket exposure is a classic escape path.
- **Self-hosted Firecracker/Kata/gVisor from day one** — rejected for v1: justified
  later investment requiring dedicated security ownership and an escape-test program.

## Consequences
- Provider dependency and per-run cost; mitigated by the adapter seam and budgets.
- Sandbox policy (no egress, non-root, resource caps, fresh VM per attempt) is testable
  via the Phase 3 canary suite and becomes release evidence.
- Local/prod behavior differences must be covered by contract tests on the executor port.

## Revisit trigger
Volume/cost making self-hosting economical, or provider security/limit changes that
violate the required policy (see threat model T3/T4).
