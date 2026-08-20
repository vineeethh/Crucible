"""Windows event-loop compatibility.

psycopg's async driver cannot run on the ProactorEventLoop, which is Python's
default on Windows. Deployed containers are Linux and unaffected, but local
development and the local test run would otherwise fail at the first query.

Import this module before an event loop is created (i.e. at the top of an app
entry point). It is a no-op on every other platform.
"""

from __future__ import annotations

import asyncio
import sys


def install_selector_event_loop_policy() -> None:
    if sys.platform != "win32":
        return
    policy = getattr(asyncio, "WindowsSelectorEventLoopPolicy", None)
    if policy is not None:
        asyncio.set_event_loop_policy(policy())
