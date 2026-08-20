"""OpenAI-compatible model gateway — the real-model contract.

Works against any OpenAI-compatible chat-completions endpoint (a hosted provider
or a local open-weight server). It is deny-by-default: without a base URL and
model it raises ModelNotConfigured rather than silently degrading.

A provider failure (timeout, connection error, 429, 5xx) is retried a bounded
number of times with backoff — honoring a `Retry-After` header on 429 when the
provider sends one — then raised as ModelUnavailable: an operational fault, not
a run outcome. `RouterPolicy.fallback_on_error` (crucible.agent.router) catches
this to fall back to a secondary gateway; the graph's own repair loop is
untouched by it (a model that never answers is not the same failure as a model
that answers wrong).
"""

from __future__ import annotations

import asyncio
import json
import random
from typing import Any

import httpx

from crucible.agent import prompts
from crucible.agent.errors import ModelNotConfigured, ModelUnavailable
from crucible.agent.models import registry
from crucible.agent.ports import ModelRole, ModelUsage
from crucible.agent.schemas import AnalysisPlan, GeneratedCode
from crucible.agent.state import ColumnView

_DEFAULT_TIMEOUT_SECONDS = 30.0
_DEFAULT_MAX_ATTEMPTS = 3
_DEFAULT_BACKOFF_BASE_SECONDS = 1.0
# A provider's Retry-After can legitimately be a daily-quota reset, hours
# away. Waiting that out here would also block a configured router from
# falling back to a secondary provider for the whole duration, so the wait
# this gateway will actually honor is capped.
_DEFAULT_MAX_RETRY_AFTER_SECONDS = 30.0
_RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})


def parse_plan(content: str) -> AnalysisPlan:
    """Validate a model response into an AnalysisPlan. Untrusted until it fits
    the schema — a hallucinated shape raises and the graph retries then abstains."""
    return AnalysisPlan.model_validate(_loads(content))


def parse_code(content: str) -> GeneratedCode:
    return GeneratedCode.model_validate(_loads(content))


def _loads(content: str) -> dict[str, Any]:
    data = json.loads(content)
    if not isinstance(data, dict):
        raise ValueError("model response is not a JSON object")
    return data


class OpenAICompatModel:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        provider: str = "openai-compatible",
        temperature: float = 0.0,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
        max_attempts: int = _DEFAULT_MAX_ATTEMPTS,
        backoff_base_seconds: float = _DEFAULT_BACKOFF_BASE_SECONDS,
        max_retry_after_seconds: float = _DEFAULT_MAX_RETRY_AFTER_SECONDS,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url
        self._api_key = api_key
        self._model = model
        self._provider = provider
        self._temperature = temperature
        self._timeout_seconds = timeout_seconds
        self._max_attempts = max_attempts
        self._backoff_base_seconds = backoff_base_seconds
        self._max_retry_after_seconds = max_retry_after_seconds
        # Injectable only for tests (httpx.MockTransport); None uses the real
        # network transport in production.
        self._transport = transport

    @property
    def configured(self) -> bool:
        return bool(self._base_url and self._model)

    def manifest(self) -> dict[str, dict[str, Any]]:
        cfg = {
            "provider": self._provider,
            "model_id": self._model or "unconfigured",
            "prompt_version": prompts.PLANNER_PROMPT_VERSION,
            "policy_version": "static@1",
            "params": {"temperature": self._temperature},
        }
        return {
            role.value: dict(cfg) for role in (ModelRole.PLANNER, ModelRole.CODER, ModelRole.REPAIR)
        }

    async def plan(
        self, *, question: str, profile: list[ColumnView]
    ) -> tuple[AnalysisPlan, ModelUsage]:
        content, usage = await self._complete(prompts.render_planner(question, profile))
        return parse_plan(content), usage

    async def code(
        self, *, plan: AnalysisPlan, profile: list[ColumnView]
    ) -> tuple[GeneratedCode, ModelUsage]:
        prompt = prompts.render_coder(plan.model_dump_json(), profile)
        content, usage = await self._complete(prompt)
        return parse_code(content), usage

    async def repair(
        self, *, plan: AnalysisPlan, profile: list[ColumnView], prior_code: str, error: str
    ) -> tuple[GeneratedCode, ModelUsage]:
        content, usage = await self._complete(prompts.render_repair(prior_code, error))
        return parse_code(content), usage

    # ------------------------------------------------------------------- HTTP

    async def _complete(self, prompt: str) -> tuple[str, ModelUsage]:
        if not self.configured:
            raise ModelNotConfigured(
                "the OpenAI-compatible model requires base_url and model; no silent fallback"
            )
        body = await self._request_with_retry(prompt)

        choices = body.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ModelUnavailable(f"{self._provider} response had no choices")
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str):
            raise ModelUnavailable(f"{self._provider} response had no message content")

        return content, self._usage_from_response(prompt, content, body.get("usage"))

    async def _request_with_retry(self, prompt: str) -> dict[str, Any]:
        base_url, model = self._base_url, self._model
        assert base_url is not None and model is not None  # guaranteed by `configured`

        payload = {
            "model": model,
            "temperature": self._temperature,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "user", "content": prompt}],
        }
        headers = {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}

        last_error: Exception | None = None
        async with httpx.AsyncClient(
            timeout=self._timeout_seconds, transport=self._transport
        ) as client:
            for attempt in range(1, self._max_attempts + 1):
                try:
                    response = await client.post(
                        f"{base_url}/chat/completions", json=payload, headers=headers
                    )
                except httpx.TransportError as exc:
                    last_error = exc
                    if attempt == self._max_attempts:
                        break
                    await asyncio.sleep(self._backoff_seconds(attempt))
                    continue

                if response.status_code == 200:
                    result = response.json()
                    if not isinstance(result, dict):
                        raise ModelUnavailable(
                            f"{self._provider} response body was not a JSON object"
                        )
                    return result

                detail = f"{self._provider} returned {response.status_code}: {response.text[:200]}"
                if response.status_code in _RETRYABLE_STATUS_CODES and attempt < self._max_attempts:
                    last_error = ModelUnavailable(detail)
                    await asyncio.sleep(self._retry_delay(attempt, response))
                    continue
                raise ModelUnavailable(detail)

        raise ModelUnavailable(
            f"{self._provider} unavailable after {self._max_attempts} attempts: {last_error}"
        )

    def _retry_delay(self, attempt: int, response: httpx.Response) -> float:
        retry_after = response.headers.get("Retry-After")
        if retry_after is not None:
            try:
                # Capped: an uncapped Retry-After (a daily-quota reset can be
                # hours away) would block this call — and therefore any
                # router waiting to fall back to a secondary provider
                # (crucible.agent.router.RouterPolicy.fallback_on_error) —
                # for that entire duration. A capped wait fails fast instead,
                # so a provider-level cap is a reroute signal, not a stall.
                return max(0.0, min(float(retry_after), self._max_retry_after_seconds))
            except ValueError:
                pass  # non-numeric Retry-After (an HTTP-date) — fall back to backoff
        return self._backoff_seconds(attempt)

    def _backoff_seconds(self, attempt: int) -> float:
        return self._backoff_base_seconds * (2.0 ** (attempt - 1)) + random.uniform(0, 0.5)

    def _usage_from_response(self, prompt: str, completion: str, raw_usage: Any) -> ModelUsage:
        tokens_in = raw_usage.get("prompt_tokens") if isinstance(raw_usage, dict) else None
        tokens_out = raw_usage.get("completion_tokens") if isinstance(raw_usage, dict) else None
        if not isinstance(tokens_in, int):
            tokens_in = registry.estimate_tokens(prompt)
        if not isinstance(tokens_out, int):
            tokens_out = registry.estimate_tokens(completion)

        model = self._model or "unconfigured"
        return ModelUsage(
            provider=self._provider,
            model_id=model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=registry.compute_cost(model, tokens_in=tokens_in, tokens_out=tokens_out),
        )
