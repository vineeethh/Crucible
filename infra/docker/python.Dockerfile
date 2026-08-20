# Reproducible Python image for API, worker, and migrations.
# Build is driven by uv.lock (--frozen): same inputs, same environment.
# Targets: api | worker | migrate

FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY packages ./packages
COPY apps/api ./apps/api
COPY apps/worker ./apps/worker
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.14-slim-bookworm AS runtime-base
RUN useradd --uid 10001 --create-home crucible
WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1
ARG GIT_SHA=unknown
ENV GIT_SHA=${GIT_SHA}
USER crucible

FROM runtime-base AS api
EXPOSE 8000
CMD ["uvicorn", "--factory", "crucible_api.main:create_app", "--host", "0.0.0.0", "--port", "8000"]

FROM runtime-base AS worker
CMD ["arq", "crucible_worker.main.WorkerSettings"]

FROM runtime-base AS migrate
# Migration runs are an explicit deploy step (plan §5.4), never app startup.
COPY packages/db/alembic.ini ./packages/db/alembic.ini
COPY packages/db/alembic ./packages/db/alembic
CMD ["alembic", "-c", "packages/db/alembic.ini", "upgrade", "head"]
