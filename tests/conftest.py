"""Root test configuration.

The live-stack fixtures live in `tests/support/stack.py` and are registered
here as a plugin so every suite (integration, security, and later e2e) shares
one definition of "a tenant", "a client", and "a clean database".
"""

pytest_plugins = ["tests.support.stack"]
