"""Agent-side errors. A model that returns unparseable output is a normal
outcome the graph handles (retry then abstain); these exceptions are for the
gateway itself being unusable — an operational fault, never blamed on the run."""

from __future__ import annotations


class AgentError(Exception):
    pass


class ModelNotConfigured(AgentError):
    pass


class ModelUnavailable(AgentError):
    pass
