"""Model registry: the declared price book and tier map (master plan Phase 8).

Cost is computed, never guessed: `usage tokens x the registry's declared price`.
A model that is not registered (or registered without a price) yields
`cost_usd=None` — the explicit "unknown cost" marker — rather than a fabricated
zero, so cost-attribution completeness stays an honest metric.

The `fake` provider's prices are **synthetic** (flagged as such): they exist so
the whole cost-accounting pipeline — per-attempt attribution, budget settlement,
the router experiment's cost deltas — is exercised end to end offline. A report
built over synthetic prices says so.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ModelSpec:
    provider: str
    model_id: str
    tier: int  # 1 = cheap/fast, 2 = capable/reference
    input_usd_per_mtok: float | None  # None => price unknown; cost stays None
    output_usd_per_mtok: float | None
    synthetic_price: bool = False  # True => a declared test price, not a market one


_SPECS: dict[str, ModelSpec] = {}


def register(spec: ModelSpec) -> None:
    """Deployments register their real models (and real prices) at composition
    time; the registry itself ships only the offline fakes."""
    _SPECS[spec.model_id] = spec


def get(model_id: str) -> ModelSpec | None:
    return _SPECS.get(model_id)


def register_openrouter_free_model(model_id: str, *, tier: int = 2) -> None:
    """Register a genuinely $0 price for an OpenRouter `:free`-suffixed model.

    This is a real, published price (OpenRouter's free tier), not a synthetic
    placeholder — but it must be called explicitly per model id by the
    composition root that configured it. A model name alone (even one ending
    in `:free`) is not proof of price; the caller is asserting it, not this
    function inferring it.
    """
    register(
        ModelSpec(
            provider="openrouter",
            model_id=model_id,
            tier=tier,
            input_usd_per_mtok=0.0,
            output_usd_per_mtok=0.0,
            synthetic_price=False,
        )
    )


def compute_cost(model_id: str, *, tokens_in: int, tokens_out: int) -> float | None:
    """Declared price x tokens, or None when the price is unknown."""
    spec = _SPECS.get(model_id)
    if spec is None or spec.input_usd_per_mtok is None or spec.output_usd_per_mtok is None:
        return None
    cost = (tokens_in * spec.input_usd_per_mtok + tokens_out * spec.output_usd_per_mtok) / 1_000_000
    return round(cost, 8)


def estimate_tokens(text: str) -> int:
    """A deterministic, conservative token estimate (~4 chars/token) used by the
    offline fakes. Real providers report exact usage; this keeps the same
    accounting shape without a tokenizer dependency."""
    return max(1, len(text) // 4)


# ---------------------------------------------------------------- shipped specs

FAKE_LITE_ID = "fake-lite"
FAKE_TEMPLATE_ID = "fake-template"

register(
    ModelSpec(
        provider="fake",
        model_id=FAKE_LITE_ID,
        tier=1,
        input_usd_per_mtok=0.05,
        output_usd_per_mtok=0.20,
        synthetic_price=True,
    )
)
register(
    ModelSpec(
        provider="fake",
        model_id=FAKE_TEMPLATE_ID,
        tier=2,
        input_usd_per_mtok=0.50,
        output_usd_per_mtok=2.00,
        synthetic_price=True,
    )
)
