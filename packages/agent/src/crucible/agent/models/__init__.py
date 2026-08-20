from crucible.agent.models.fake import FakeLiteModel, FakeModel
from crucible.agent.models.judge import (
    JUDGE_RUBRIC_VERSION,
    FakeJudge,
    Judge,
    OpenAICompatJudge,
)
from crucible.agent.models.openai_compat import OpenAICompatModel
from crucible.agent.models.registry import (
    ModelSpec,
    compute_cost,
    register,
    register_openrouter_free_model,
)

__all__ = [
    "JUDGE_RUBRIC_VERSION",
    "FakeJudge",
    "FakeLiteModel",
    "FakeModel",
    "Judge",
    "ModelSpec",
    "OpenAICompatJudge",
    "OpenAICompatModel",
    "compute_cost",
    "register",
    "register_openrouter_free_model",
]
