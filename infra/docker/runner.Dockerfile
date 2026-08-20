# Fixed, pinned sandbox runner image (master plan §9.3).
#
# This image is a security artifact. The model never chooses it, never changes
# it, and never adds to it: the allowlisted analytical package set is baked in
# here, at build time, and there is no pip/network at run time. Every launch
# uses this exact image with a fixed configuration constructed by the host.
#
# Local development only (ADR-003); production uses a managed microVM. Digest
# pinning of the base image is a Phase 9 hardening task.
FROM python:3.14-slim-bookworm

# Preinstalled, allowlisted analytical libraries. No compilers, no build tools,
# nothing that fetches at run time. Polars is a single self-contained wheel.
# Two RUN steps deliberately: `A && B || true` in one shell command masks a
# failed A (pip install) behind the `|| true` meant only for B (cache purge),
# due to left-to-right &&/|| precedence — a transient network failure during
# `pip install` would silently produce an image with no polars in it at all.
RUN pip install --no-cache-dir --only-binary=:all: "polars==1.17.1"
RUN pip cache purge || true

# Non-root identity baked into the image; the host also passes --user as a
# second control. UID is high and fixed so it maps to no host user.
RUN groupadd --gid 10001 sandbox \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin sandbox \
    && mkdir -p /sandbox /results /opt/crucible \
    && chown sandbox:sandbox /results

COPY infra/docker/runner/harness.py /opt/crucible/harness.py

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    CRUCIBLE_RESULTS_DIR=/results \
    CRUCIBLE_PROGRAM_PATH=/sandbox/program.py

USER 10001:10001
WORKDIR /results

# The harness is the trusted entrypoint. It runs the untrusted program as a
# further-constrained subprocess and writes the authoritative manifest.
ENTRYPOINT ["python", "-I", "-B", "/opt/crucible/harness.py"]
