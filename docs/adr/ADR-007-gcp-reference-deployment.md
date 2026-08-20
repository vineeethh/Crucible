# ADR-007: GCP reference deployment with provider-neutral interfaces

Status: Accepted · Date: 2026-07-14

## Context
The platform needs a coherent, operable managed stack for staging/production that one
developer can run: serverless containers, managed Postgres/Redis, object storage,
secrets, and OIDC-based deploys — without marrying application code to one vendor.

## Decision
GCP is the reference deployment: Cloud Run (API + worker, separate service accounts),
Cloud SQL PostgreSQL, Memorystore Redis, GCS, Secret Manager, with GitHub Actions OIDC
for short-lived deploy credentials and OpenTofu for IaC. Application code reaches all
infrastructure through ports/adapters (storage, queue, secrets, model gateway), and
local development uses Compose with MinIO/Postgres/Redis to mirror the roles.

## Alternatives considered
- **Kubernetes (GKE or elsewhere)** — rejected for v1: operational surface (upgrades,
  networking, RBAC) beyond a solo developer's budget with no v1 requirement it uniquely serves.
- **PaaS-only (Vercel/Render/Fly for everything)** — rejected: weaker portability and
  less credible production-engineering evidence; Vercel remains acceptable for the
  Next.js frontend specifically.
- **AWS/Azure equivalents** — viable; GCP chosen for Cloud Run's container-first
  ergonomics and coherent IAM/OIDC story. The adapter seam keeps this reversible.

## Consequences
- IaC modules, IAM boundaries, and backup/restore drills are written against GCP
  (Phases 9–10); portability is preserved at the interface layer, not the infra layer.
- Cloud-specific features (e.g., CMEK, VPC connectors) are adopted only when the threat
  model or requirements justify them.

## Revisit trigger
A hosting requirement from a real adopter, sustained cost disadvantage, or a needed
capability (e.g., GPU workloads) with a materially better home elsewhere.
