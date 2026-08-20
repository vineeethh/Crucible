"""Static advisory scan of program source.

This is defense in depth, **not** the security boundary. The boundary is the
sandbox: no network, no host access, dropped capabilities, resource caps. A
static scan of Python is trivially evadable (`getattr`, `__import__`, string
tricks), so nothing here is allowed to be the thing that keeps generated code
safe. It exists to (a) surface obvious intent for tracing/triage and (b) give
Phase 4's planner a signal it may use for bounded repair.

The executor does not block on these findings by default; the isolation does.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from enum import StrEnum

# Modules whose mere import is a strong signal of out-of-scope intent for a
# read-only data-analysis program.
_FLAGGED_IMPORTS = frozenset(
    {"socket", "subprocess", "ctypes", "requests", "urllib", "http", "ftplib", "asyncio"}
)
_FLAGGED_CALLS = frozenset({"eval", "exec", "compile", "__import__"})


class Severity(StrEnum):
    INFO = "info"
    SUSPICIOUS = "suspicious"


@dataclass(frozen=True, slots=True)
class Finding:
    severity: Severity
    code: str
    detail: str
    lineno: int


def scan_source(source: str) -> list[Finding]:
    """Return advisory findings. A syntax error is itself a finding: such a
    program would fail in the sandbox anyway, but flagging it early is cheaper."""
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return [
            Finding(Severity.INFO, "syntax_error", exc.msg or "invalid syntax", exc.lineno or 0)
        ]

    findings: list[Finding] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in _FLAGGED_IMPORTS:
                    findings.append(
                        Finding(Severity.SUSPICIOUS, "flagged_import", root, node.lineno)
                    )
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            if root in _FLAGGED_IMPORTS:
                findings.append(Finding(Severity.SUSPICIOUS, "flagged_import", root, node.lineno))
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in _FLAGGED_CALLS
        ):
            findings.append(Finding(Severity.SUSPICIOUS, "flagged_call", node.func.id, node.lineno))
    return findings
