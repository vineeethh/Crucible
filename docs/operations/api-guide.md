# API Guide (v1)

Base URL: `http://localhost:8100` locally. Interactive docs: `/docs`.

## Authentication

Two credentials, one header:

```
Authorization: Bearer ck_<prefix>_<secret>    # API key
Authorization: Bearer <oidc-jwt>              # OIDC user (when configured)
```

An API key is bound to one organization; a JWT user picks one with
`X-Organization-Id` when they belong to several. There is no self-service
signup — create the first organization and key deliberately:

```bash
uv run python scripts/bootstrap_org.py --slug demo --name "Demo Org"
# prints the token once; it is not recoverable
```

Roles, in increasing order: `viewer` → `reviewer` → `engineer` → `admin` → `owner`.
A key may carry `scopes` that **narrow** its role; scopes can never widen it, and
no one can mint a key exceeding their own permissions.

## Uploading a dataset (the API never touches the bytes)

```bash
# 1. Ask for a presigned URL. Policy (size, type, extension) is checked here,
#    before a single byte moves.
curl -X POST $API/v1/datasets/uploads -H "Authorization: Bearer $KEY" \
  -H 'Content-Type: application/json' \
  -d '{"dataset_name":"sales","filename":"sales.csv",
       "content_type":"text/csv","size_bytes":142}'
# -> { "version_id": "...", "upload_url": "https://..." }

# 2. PUT the file straight to object storage.
curl -X PUT "$UPLOAD_URL" -H 'Content-Type: text/csv' --data-binary @sales.csv

# 3. Confirm, declaring the content hash. The worker re-computes it from the
#    stored bytes; a mismatch marks the version invalid rather than trusting you.
curl -X POST $API/v1/datasets/versions/$VERSION_ID/complete \
  -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json' \
  -d "{\"content_sha256\":\"$(sha256sum sales.csv | cut -d' ' -f1)\"}"
```

The version then moves `pending_profile` → `ready` (or `invalid`, with a stable
reason). Only a `ready` version can back a run.

**Content is identity.** Re-uploading identical bytes to the same dataset
returns the existing version instead of creating a second one.

## Running

```bash
curl -X POST $API/v1/runs -H "Authorization: Bearer $KEY" \
  -H 'Content-Type: application/json' -H "Idempotency-Key: $(uuidgen)" \
  -d '{"dataset_version_id":"...","question":"What is the total by region?"}'
# 202 Accepted, Location: /v1/runs/{id}
```

Poll `GET /v1/runs/{id}`, list history with `GET /v1/runs/{id}/events`, inspect the
per-step reasoning with `GET /v1/runs/{id}/attempts`, or stream
`GET /v1/runs/{id}/stream` (SSE). `POST /v1/runs/{id}/cancel` cancels a queued run
immediately and asks a running one to stop at its next checkpoint.

Replaying an `Idempotency-Key` with the same body returns the original run (200,
not 202). Replaying it with a *different* body is a 409 — keys are never merged.

### What the agent returns (Phase 4)

A terminal run carries one of:

- **`answered`** — `answer` holds the value, a mechanically-synthesized `text`, and
  `provenance` (operation, columns used, code hash, attempt count, executor
  backend/image). `verification` shows the checks that gated the answer.
- **`abstained`** — the question is unsupported, or execution failed in a way a
  bounded repair could not fix. No fabricated value; `terminal_detail` says why.
- **`waiting_review`** — an ambiguous result (e.g. a tie) routed to a human. A
  reviewer resolves it with `POST /v1/runs/{id}/review {"approve": bool}`
  (requires `review:submit`); approve resumes to an answer, reject abstains.

The answer text is derived from the verified result, so it can never claim more
than the computed number. Generated code always runs in the sandbox (Phase 3);
the deployment's executor backend determines whether real computation is
available (`fake` returns no value and the run abstains).

## Endpoints

| Method | Path | Permission |
|---|---|---|
| GET | `/v1/me` | any authenticated |
| GET/POST | `/v1/api-keys` · DELETE `/v1/api-keys/{id}` | `apikey:manage` |
| GET | `/v1/datasets` · `/v1/datasets/{id}/versions` | `dataset:read` |
| POST | `/v1/datasets/uploads` · `/v1/datasets/versions/{id}/complete` | `dataset:write` |
| GET | `/v1/datasets/versions/{id}` | `dataset:read` |
| POST | `/v1/datasets/versions/{id}/download-url` | `dataset:download` (audited) |
| GET/POST | `/v1/runs` | `run:read` / `run:create` |
| GET | `/v1/runs/{id}` · `/events` · `/stream` | `run:read` |
| POST | `/v1/runs/{id}/cancel` | `run:cancel` |

## Errors

RFC 9457 `application/problem+json`, with the request ID echoed in the body and
the `X-Request-Id` header.

| Status | Meaning |
|---|---|
| 401 | No or bad credential. Audited. |
| 403 | Authenticated, not entitled. Audited with actor + tenant. |
| 404 | Not found **or belongs to another tenant** — deliberately indistinguishable, so IDs cannot be probed. |
| 409 | Idempotency-key reuse, dataset not ready, run already terminal. |
| 413/415/422 | Upload too large / wrong type / invalid body. |
| 429 | Rate limited (60 writes/min, 20 runs/min per principal). |
| 503 | A dependency needed to account for the work is down. Expensive routes **fail closed**. |

## Limits

50 MiB per upload, 2M rows, 512 columns, 2000-character questions. CSV and
Parquet only — the parser, not the declared content type, is the authority.
