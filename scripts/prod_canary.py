"""Production canary with synthetic data (master plan Phase 10).

A post-deploy / scheduled health probe that goes beyond `/readyz`: it exercises
the authenticated path with a *synthetic* question, so a break in auth, the DB
path, or (with --drive) the agent pipeline surfaces as a red canary rather than
a user's failed run. Synthetic only — never real tenant data in a canary.

    # health canary (no worker needed): readyz + version + authed read
    python scripts/prod_canary.py --url https://staging.example --token "$KEY"

    # full canary: also create a synthetic run and wait for it to terminate
    python scripts/prod_canary.py --url ... --token "$KEY" --drive

Exit code is non-zero on any failed check, so a scheduler/alert can gate on it.
"""

from __future__ import annotations

import argparse
import sys
import time

import httpx

CANARY_QUESTION = "[canary] What is the total amount?"


def _fail(msg: str) -> None:
    print(f"[canary] FAIL: {msg}")
    raise SystemExit(1)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--url", required=True, help="API base URL")
    p.add_argument("--token", required=True, help="Bearer API key")
    p.add_argument("--drive", action="store_true", help="also create + await a synthetic run")
    p.add_argument("--timeout", type=float, default=10.0)
    p.add_argument("--run-timeout", type=float, default=120.0)
    args = p.parse_args(argv)

    auth = {"Authorization": f"Bearer {args.token}"}
    client = httpx.Client(base_url=args.url, timeout=args.timeout)

    # 1. Readiness: every dependency probe is green.
    r = client.get("/readyz")
    if r.status_code != 200:
        _fail(f"/readyz returned {r.status_code}: {r.text[:200]}")
    print("[canary] readyz ok")

    # 2. Version reports a real build (never 'unknown').
    version = client.get("/version").json()
    if not version.get("git_sha") or version["git_sha"] == "unknown":
        _fail(f"/version git_sha is {version.get('git_sha')!r}")
    print(f"[canary] version git_sha={version['git_sha']}")

    # 3. The credential authenticates and the tenant read path works.
    runs = client.get("/v1/runs?limit=1", headers=auth)
    if runs.status_code != 200:
        _fail(f"authed GET /v1/runs returned {runs.status_code}")
    print("[canary] authenticated read ok")

    if not args.drive:
        print("[canary] PASS (health)")
        return 0

    # 4. Synthetic run: pick a ready dataset version, create a run, await terminal.
    datasets = client.get("/v1/datasets", headers=auth).json()
    version_id = None
    for ds in datasets:
        versions = client.get(f"/v1/datasets/{ds['id']}/versions", headers=auth).json()
        ready = [v for v in versions if v["status"] == "ready"]
        if ready:
            version_id = ready[0]["id"]
            break
    if version_id is None:
        _fail("no ready dataset version to drive a synthetic run (seed one first)")

    created = client.post(
        "/v1/runs",
        headers=auth,
        json={"dataset_version_id": version_id, "question": CANARY_QUESTION},
    )
    if created.status_code not in (200, 202):
        _fail(f"run creation returned {created.status_code}: {created.text[:200]}")
    run_id = created.json()["id"]
    print(f"[canary] created synthetic run {run_id[:8]}; awaiting terminal…")

    terminal = {"answered", "abstained", "policy_denied", "budget_exhausted", "cancelled"}
    deadline = time.monotonic() + args.run_timeout
    while time.monotonic() < deadline:
        status = client.get(f"/v1/runs/{run_id}", headers=auth).json()["status"]
        if status in terminal:
            print(f"[canary] run reached terminal state: {status}")
            print("[canary] PASS (full)")
            return 0
        time.sleep(3)
    _fail(f"synthetic run did not terminate within {args.run_timeout}s")
    return 1  # unreachable; _fail raises


if __name__ == "__main__":
    sys.exit(main())
