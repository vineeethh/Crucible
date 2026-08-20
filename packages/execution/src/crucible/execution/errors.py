"""Executor-side errors (distinct from a contained program failure).

A program that crashes, loops, or gets OOM-killed is a normal ExecutionResult
with a non-OK exit class. These exceptions are for the executor *itself* being
unable to run — misconfiguration or an unavailable backend — which is an
operational fault, never attributed to the model.
"""

from __future__ import annotations


class SandboxError(Exception):
    """Base for executor infrastructure failures."""


class ExecutorUnavailable(SandboxError):
    """The backend (Docker daemon / microVM provider) cannot be reached."""


class ExecutorNotConfigured(SandboxError):
    """The backend was selected but is missing required configuration."""
