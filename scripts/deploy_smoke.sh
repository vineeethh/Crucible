#!/usr/bin/env bash
# Post-deploy verification: liveness, readiness (dependencies wired), and a
# version check. Used by the staging deploy and production promotion workflows
# as the gate before a deploy is considered good; a non-zero exit triggers the
# workflow's automatic rollback.
#
# Usage: deploy_smoke.sh <api_base_url>
set -euo pipefail

API_URL="${1:?usage: deploy_smoke.sh <api_base_url>}"
RETRIES="${SMOKE_RETRIES:-20}"
SLEEP="${SMOKE_SLEEP:-3}"

log() { printf '[smoke] %s\n' "$*"; }

# 1. Liveness: the process is up.
log "healthz $API_URL/healthz"
for i in $(seq 1 "$RETRIES"); do
  if curl -fsS --max-time 5 "$API_URL/healthz" >/dev/null; then
    log "alive"
    break
  fi
  if [ "$i" = "$RETRIES" ]; then
    log "FAILED: never became alive"
    exit 1
  fi
  sleep "$SLEEP"
done

# 2. Readiness: dependencies (DB, Redis, object storage) are reachable. A 200
#    means every probe is up; 503 means degraded — fail the deploy.
log "readyz $API_URL/readyz"
code=$(curl -s -o /tmp/readyz.json -w '%{http_code}' --max-time 10 "$API_URL/readyz" || echo 000)
if [ "$code" != "200" ]; then
  log "FAILED: readyz returned $code"
  cat /tmp/readyz.json 2>/dev/null || true
  exit 1
fi
log "ready"

# 3. Version: the deployed build reports a real git SHA (never 'unknown').
sha=$(curl -fsS --max-time 5 "$API_URL/version" | sed -n 's/.*"git_sha"[: ]*"\([^"]*\)".*/\1/p')
if [ -z "$sha" ] || [ "$sha" = "unknown" ]; then
  log "FAILED: /version git_sha is '$sha'"
  exit 1
fi
log "version git_sha=$sha"

log "SMOKE PASSED"
