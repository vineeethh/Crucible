"""Identity of an agent configuration under evaluation.

Every behavior-changing input is captured and hashed so a report is
reproducible and two experiments can be compared honestly (plan principle 5).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field


@dataclass(frozen=True, slots=True)
class EvalConfig:
    id: str
    model_backend: str
    executor_backend: str
    prompt_version: str = "unknown"
    policy_version: str = "unknown"
    model_variant: str = "reference"
    limits: dict[str, float] = field(default_factory=dict)

    @property
    def config_hash(self) -> str:
        payload = asdict(self)
        payload.pop("id", None)  # the hash is over behavior, not the label
        canonical = json.dumps(payload, separators=(",", ":"), sort_keys=True)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
