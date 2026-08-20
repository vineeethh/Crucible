# ADR-002: PostgreSQL is the system of record; Redis is ephemeral coordination

Status: Accepted · Date: 2026-07-14

## Context
Runs, datasets, evals, reviews, releases, and audit events need transactions,
constraints, migrations, and analytics-friendly querying. Queues, rate limits, SSE
fan-out, and short-lived caches need high-churn TTL coordination.

## Decision
PostgreSQL 17+ (with pgvector for later needs) is the sole system of record. Redis 7+
holds only reconstructible state: queue, rate-limit counters, locks, short-TTL caches.
Queue recovery derives from Postgres run status, never from Redis contents.

## Alternatives considered
- **Redis as primary state** — rejected: loses auditability, transactions, and durable evidence.
- **Document DB (MongoDB)** — rejected: relational integrity and constraint checking are
  central to run/eval evidence.
- **Separate dedicated vector DB** — rejected for v1: unjustified operational surface
  before a proven scale/recall need; pgvector suffices.

## Consequences
- Loss of Redis must never lose authoritative data (tested via game day, Phase 9).
- All schema changes go through Alembic with expand→migrate→contract discipline.
- Single database simplifies backup/restore drills and tenant deletion.

## Revisit trigger
Measured vector workload (semantic cache / failure clustering) exceeding pgvector's
recall/latency envelope, or queue volume exceeding Redis+arq comfort.
