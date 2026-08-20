# Windows mirror of `make check` (Phase 1 Definition of Done command).
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

uv run ruff format --check .
if ($LASTEXITCODE) { exit 1 }
uv run ruff check .
if ($LASTEXITCODE) { exit 1 }
uv run mypy
if ($LASTEXITCODE) { exit 1 }
uv run lint-imports
if ($LASTEXITCODE) { exit 1 }
uv run pytest -m "not integration"
if ($LASTEXITCODE) { exit 1 }
uv run alembic -c packages/db/alembic.ini upgrade head --sql > $null
if ($LASTEXITCODE) { exit 1 }
uv run python evals/references/run_all.py > $null
if ($LASTEXITCODE) { exit 1 }
Write-Host "ALL CHECKS PASSED" -ForegroundColor Green
