# Crucible developer commands (thin wrappers; no business logic — plan §3).
# Windows without make: use scripts/check.ps1 or run the uv/docker commands directly.

.PHONY: bootstrap check fmt lint type imports test test-int evals up down migrate lock

bootstrap:            ## Install toolchain deps and git hooks
	uv sync --dev
	uv run pre-commit install

check: ## The one command a fresh clone must pass (Phase 1 DoD)
	uv run ruff format --check .
	uv run ruff check .
	uv run mypy
	uv run lint-imports
	uv run pytest -m "not integration"
	uv run alembic -c packages/db/alembic.ini upgrade head --sql > /dev/null
	uv run python evals/references/run_all.py > /dev/null
	@echo "ALL CHECKS PASSED"

fmt:
	uv run ruff format .
	uv run ruff check --fix .

lint:
	uv run ruff check .

type:
	uv run mypy

imports:
	uv run lint-imports

test:
	uv run pytest -m "not integration"

test-int:             ## Requires the compose stack (make up)
	uv run pytest -m integration

sandbox-image:        ## Build the hardened sandbox runner image
	docker build -f infra/docker/runner.Dockerfile -t crucible-sandbox-runner:local .

sandbox:              ## Run the sandbox containment canaries (needs the image)
	uv run pytest -m sandbox

evals:                ## Seed-suite reference calculators
	uv run python evals/references/run_all.py

eval-run:             ## Run the core suite vs the frozen baseline and gate (needs the runner image)
	uv run python -m crucible.evaluation run --suite evals/suites/core-v1.1.0.yaml \
		--baseline evals/baseline.json --executor docker --out evals/reports

eval-run-retail:      ## Run the retail breadth suite vs its baseline
	uv run python -m crucible.evaluation run --suite evals/suites/retail-v1.0.0.yaml \
		--baseline evals/baseline-retail.json --executor docker --out evals/reports

eval-run-adversarial: ## Run the adversarial robustness suite vs its baseline
	uv run python -m crucible.evaluation run --suite evals/suites/adversarial-v1.0.0.yaml \
		--baseline evals/baseline-adversarial.json --executor docker --out evals/reports

eval-run-all: eval-run eval-run-retail eval-run-adversarial  ## All three suites

eval-baseline:        ## Regenerate the frozen baseline (reviewed change only)
	uv run python -m crucible.evaluation baseline --suite evals/suites/core-v1.1.0.yaml \
		--executor docker --out evals/baseline.json --approved-by "$(USER)"

eval-baseline-retail: ## Regenerate the retail baseline (reviewed change only)
	uv run python -m crucible.evaluation baseline --suite evals/suites/retail-v1.0.0.yaml \
		--executor docker --out evals/baseline-retail.json --approved-by "$(USER)"

eval-baseline-adversarial: ## Regenerate the adversarial baseline (reviewed change only)
	uv run python -m crucible.evaluation baseline --suite evals/suites/adversarial-v1.0.0.yaml \
		--executor docker --out evals/baseline-adversarial.json --approved-by "$(USER)"

load:                 ## Load/soak + resilience game-day drills (needs the stack)
	uv run pytest -m load

dr-drill:             ## Non-destructive backup→restore drill; writes evidence
	bash scripts/dr_drill.sh

iac-check:            ## Format-check + validate the OpenTofu (needs tofu)
	cd infra/opentofu && tofu fmt -recursive -check && \
		for e in environments/*/; do (cd "$$e" && tofu init -backend=false && tofu validate); done

workflow-audit:       ## Audit GitHub Actions workflows for security (zizmor)
	uvx zizmor --persona=regular .github/workflows

up:                   ## Local stack (add --profile full for web)
	docker compose up -d

down:
	docker compose down

migrate:              ## Explicit migration step — never runs on app startup
	uv run alembic -c packages/db/alembic.ini upgrade head

lock:
	uv lock
