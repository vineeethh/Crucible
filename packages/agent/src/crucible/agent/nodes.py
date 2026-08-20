"""Graph nodes implementing the master plan §8.2 node contract.

Each node is a small async function over the shared AgentState that returns the
next Node to run (or Node.DONE when it has set a terminal reason, or a review
interrupt). Nodes read inputs and record evidence through the injected context;
they hold no infrastructure references of their own.
"""

from __future__ import annotations

from dataclasses import dataclass

from crucible.agent import policy, prompts
from crucible.agent.cache import compute_cache_key, config_signature, question_sha256
from crucible.agent.metamorphic import run_challenges
from crucible.agent.models.codegen import generate_source  # noqa: F401 (referenced in prompts)
from crucible.agent.ports import (
    AgentPersistence,
    AnswerCache,
    AttemptRecord,
    DatasetView,
    ModelGateway,
)
from crucible.agent.provenance import build_answer, output_guard
from crucible.agent.schemas import (
    Answer,
    Provenance,
    VerificationDecision,
    VerificationVector,
)
from crucible.agent.state import AgentState, ExecutionEvidence, Node, TerminalReason
from crucible.domain import FailureCategory
from crucible.execution import (
    DatasetInput,
    ExecutionLimits,
    ExecutionProgram,
    ExecutionRequest,
    Executor,
)


@dataclass(frozen=True, slots=True)
class NodeResult:
    next: Node
    interrupt: bool = False  # True => waiting for a reviewer; persist and stop


@dataclass(slots=True)
class AgentContext:
    persistence: AgentPersistence
    model: ModelGateway
    executor: Executor
    dataset: DatasetView
    dataset_bytes: bytes
    limits: ExecutionLimits
    # Exact-answer cache (Phase 8). None = the feature flag is off, and the
    # EXACT_CACHE node is a pass-through — the pre-Phase-8 behavior.
    cache: AnswerCache | None = None


class AgentNodes:
    def __init__(self, ctx: AgentContext) -> None:
        self.ctx = ctx

    # ------------------------------------------------------------------ helpers
    def _abstain(self, state: AgentState, reason: str) -> NodeResult:
        state.terminal_reason = TerminalReason.ABSTAINED
        state.detail = reason
        return NodeResult(Node.DONE)

    async def _attempt(self, state: AgentState, attempt: AttemptRecord) -> None:
        await self.ctx.persistence.append_attempt(state.run_id, state.organization_id, attempt)

    # -------------------------------------------------------------------- nodes
    async def validate(self, state: AgentState) -> NodeResult:
        if not state.question.strip():
            state.terminal_reason = TerminalReason.POLICY_DENIED
            state.detail = "empty question"
            return NodeResult(Node.DONE)
        return NodeResult(Node.PROFILE)

    async def profile(self, state: AgentState) -> NodeResult:
        state.profile = list(self.ctx.dataset.profile)
        state.dataset_sha256 = self.ctx.dataset.content_sha256
        if not state.profile:
            return self._abstain(state, "the dataset has no readable schema")
        return NodeResult(Node.EXACT_CACHE)

    async def exact_cache(self, state: AgentState) -> NodeResult:
        """Exact-match answer replay (feature-flagged; master plan §12.3).

        The key binds tenant + dataset content + config signature + question,
        and the adapter's lookup is additionally org-scoped in SQL. A hit is
        re-validated against the stored identity inputs; any mismatch is a
        *false hit*: it is counted, the entry is invalidated, and the run
        proceeds as a miss — a suspect entry is never served.
        """
        cache = self.ctx.cache
        if cache is None or not state.dataset_sha256:
            state.cache_key = None
            return NodeResult(Node.ROUTE)

        sig = config_signature(self.ctx.model.manifest())
        state.config_signature = sig
        state.cache_key = compute_cache_key(
            organization_id=state.organization_id,
            dataset_sha256=state.dataset_sha256,
            config_sig=sig,
            question=state.question,
        )
        hit = await cache.lookup(organization_id=state.organization_id, cache_key=state.cache_key)
        if hit is None:
            await self._attempt(
                state,
                AttemptRecord(kind="cache", sequence_no=0, payload={"outcome": "miss"}),
            )
            return NodeResult(Node.ROUTE)

        if hit.dataset_sha256 != state.dataset_sha256 or hit.config_signature != sig:
            await cache.invalidate(organization_id=state.organization_id, cache_key=state.cache_key)
            await self._attempt(
                state,
                AttemptRecord(kind="cache", sequence_no=0, payload={"outcome": "false_hit"}),
            )
            return NodeResult(Node.ROUTE)

        answer = Answer.model_validate(hit.answer).model_copy(update={"cached": True})
        state.answer = answer
        if hit.verification is not None:
            state.verification = VerificationVector.model_validate(hit.verification)
        await cache.record_hit(organization_id=state.organization_id, cache_key=state.cache_key)
        await self._attempt(
            state,
            AttemptRecord(
                kind="cache",
                sequence_no=0,
                payload={"outcome": "hit", "key_prefix": state.cache_key[:12]},
            ),
        )
        state.terminal_reason = TerminalReason.ANSWERED
        state.detail = "served from the exact cache"
        return NodeResult(Node.DONE)

    async def route(self, state: AgentState) -> NodeResult:
        # Record the routing policy in effect as evidence (a route-decision
        # span). Single-gateway deployments record the static policy marker.
        manifest = self.ctx.model.manifest()
        router = manifest.get("router") or {"policy_version": "single-tier@1"}
        await self._attempt(
            state, AttemptRecord(kind="route", sequence_no=0, payload={"router": router})
        )
        return NodeResult(Node.PLAN)

    @staticmethod
    def _with_route(payload: dict[str, object], usage: object) -> dict[str, object]:
        escalated = bool(getattr(usage, "escalated", False))
        if escalated:
            payload = {
                **payload,
                "route": {"escalated": True, "reason": getattr(usage, "route_reason", None)},
            }
        return payload

    async def plan(self, state: AgentState) -> NodeResult:
        try:
            plan, usage = await self.ctx.model.plan(question=state.question, profile=state.profile)
        except ValueError as exc:
            # The model's response didn't fit the AnalysisPlan schema (bad JSON,
            # or valid JSON missing a required field) — pydantic's ValidationError
            # subclasses ValueError. Same one-retry-then-abstain budget as the
            # unknown-column case below: a hallucinated shape is never a crash.
            if not state.plan_retry_used:
                state.plan_retry_used = True
                return NodeResult(Node.PLAN)
            return self._abstain(state, f"planner returned invalid structured output: {exc}")
        await self._attempt(
            state,
            AttemptRecord(
                kind="plan",
                sequence_no=0,
                payload=self._with_route(plan.model_dump(), usage),
                model_provider=usage.provider,
                model_id=usage.model_id,
                cost_usd=usage.cost_usd,
            ),
        )
        if plan.is_abstain:
            return self._abstain(state, plan.rationale or "the question is not supported")

        known = {c.name for c in state.profile}
        missing = [c for c in plan.referenced_columns if c not in known]
        if missing:
            # A plan that references a non-existent column is invalid. One
            # structured-output retry, then abstain (never invent a column).
            if not state.plan_retry_used:
                state.plan_retry_used = True
                return NodeResult(Node.PLAN)
            return self._abstain(state, f"plan referenced unknown columns: {missing}")

        state.plan = plan
        return NodeResult(Node.CODE)

    async def code(self, state: AgentState) -> NodeResult:
        assert state.plan is not None
        try:
            code, usage = await self.ctx.model.code(plan=state.plan, profile=state.profile)
        except ValueError as exc:
            if not state.code_retry_used:
                state.code_retry_used = True
                return NodeResult(Node.CODE)
            return self._abstain(state, f"coder returned invalid structured output: {exc}")
        state.code_source = code.source
        state.code_sha256 = ExecutionProgram(code.source).sha256
        await self._attempt(
            state,
            AttemptRecord(
                kind="code",
                sequence_no=0,
                payload=self._with_route({"explanation": code.explanation}, usage),
                model_provider=usage.provider,
                model_id=usage.model_id,
                cost_usd=usage.cost_usd,
                source_sha256=state.code_sha256,
            ),
        )
        return NodeResult(Node.EXECUTE)

    async def execute(self, state: AgentState) -> NodeResult:
        assert state.code_source is not None
        request = ExecutionRequest(
            run_id=state.run_id,
            attempt_id=str(state.repair_count + 1),
            program=ExecutionProgram(state.code_source),
            dataset=DatasetInput(
                filename=self.ctx.dataset.filename,
                media_type=self.ctx.dataset.media_type,
                sha256=self.ctx.dataset.content_sha256 or "",
                content=self.ctx.dataset_bytes,
            ),
            limits=self.ctx.limits,
        )
        result = await self.ctx.executor.execute(request)
        category = result.failure_category
        state.last_execution = ExecutionEvidence(
            exit_class=result.exit_class.value,
            ok=result.ok,
            failure_category=category.value if category else None,
            result=result.result,
            stderr_excerpt=result.stderr[:500],
            error_detail=result.error_detail,
            image_ref=result.image_ref,
            backend=self.ctx.executor.backend,
            code_sha256=state.code_sha256 or "",
            artifacts=list(result.artifacts),
        )
        await self._attempt(
            state,
            AttemptRecord(
                kind="execute",
                sequence_no=state.repair_count + 1,
                payload={"span": result.span_attributes()},
                exit_class=result.exit_class.value,
                failure_category=category.value if category else None,
                duration_ms=result.usage.wall_ms,
                source_sha256=state.code_sha256,
            ),
        )
        return NodeResult(Node.OBSERVE)

    async def observe(self, state: AgentState) -> NodeResult:
        ev = state.last_execution
        assert ev is not None
        if ev.ok and ev.result is not None:
            return NodeResult(Node.CHALLENGE)

        category = FailureCategory(ev.failure_category) if ev.failure_category else None
        fp = policy.fingerprint(ev.code_sha256, ev.failure_category, ev.error_detail)
        seen_before = fp in state.fingerprints
        state.fingerprints.append(fp)

        if (
            policy.is_repairable(category)
            and state.repair_count < policy.MAX_REPAIRS
            and not seen_before
        ):
            return NodeResult(Node.REFLECT)

        reason = self._abstain_reason(ev, category, seen_before)
        return self._abstain(state, reason)

    @staticmethod
    def _abstain_reason(
        ev: ExecutionEvidence, category: FailureCategory | None, seen_before: bool
    ) -> str:
        if seen_before:
            return "the same failure recurred after repair; stopping to avoid an oscillation"
        if not policy.is_repairable(category):
            return f"non-repairable failure: {ev.exit_class}"
        return f"repair budget exhausted after {policy.MAX_REPAIRS} attempts ({ev.exit_class})"

    async def challenge(self, state: AgentState) -> NodeResult:
        """Metamorphic verification (crucible.agent.metamorphic): re-run the
        SAME already-succeeded program against row-shuffled / column-reordered
        data and record whether the answer held. Gathers evidence only —
        verify() decides; a failure here never itself aborts the run, so a
        transform-execution hiccup can't turn a good answer into a crash."""
        assert state.code_source is not None and state.last_execution is not None
        ev = state.last_execution

        if (ev.result or {}).get("ambiguous"):
            # A genuine tie (e.g. two regions with equal totals) has more than
            # one equally correct answer, and the program's own tie-break
            # (which one it reports) is legitimately allowed to differ under a
            # row shuffle — that is not evidence of a bug, it's what "tie"
            # means. Re-checking would produce a false violation, so skip
            # rather than let an ambiguous-but-honest result look wrong.
            return NodeResult(Node.VERIFY)

        try:
            state.challenge_results = await run_challenges(
                executor=self.ctx.executor,
                run_id=state.run_id,
                attempt_id=str(state.repair_count + 1),
                program=ExecutionProgram(state.code_source),
                dataset=DatasetInput(
                    filename=self.ctx.dataset.filename,
                    media_type=self.ctx.dataset.media_type,
                    sha256=self.ctx.dataset.content_sha256 or "",
                    content=self.ctx.dataset_bytes,
                ),
                limits=self.ctx.limits,
                baseline_result=ev.result or {},
            )
        except Exception as exc:  # noqa: BLE001 - evidence-gathering must not crash the run
            state.challenge_results = []
            await self._attempt(
                state,
                AttemptRecord(
                    kind="challenge",
                    sequence_no=0,
                    payload={"error": f"{type(exc).__name__}: {exc}"},
                ),
            )
            return NodeResult(Node.VERIFY)

        await self._attempt(
            state,
            AttemptRecord(
                kind="challenge",
                sequence_no=0,
                payload={"results": [c.model_dump() for c in state.challenge_results]},
            ),
        )
        return NodeResult(Node.VERIFY)

    async def reflect(self, state: AgentState) -> NodeResult:
        assert state.plan is not None and state.code_source is not None and state.last_execution
        ev = state.last_execution
        try:
            repaired, usage = await self.ctx.model.repair(
                plan=state.plan,
                profile=state.profile,
                prior_code=state.code_source,
                error=ev.error_detail or ev.stderr_excerpt or ev.exit_class,
            )
        except ValueError as exc:
            # Already inside the bounded repair loop (policy.MAX_REPAIRS, an
            # oscillation guard) — a malformed repair response is a terminal
            # failure of this attempt, not a case for its own retry budget.
            return self._abstain(state, f"repair returned invalid structured output: {exc}")
        state.repair_count += 1
        state.code_source = repaired.source
        state.code_sha256 = ExecutionProgram(repaired.source).sha256
        await self._attempt(
            state,
            AttemptRecord(
                kind="repair",
                sequence_no=state.repair_count,
                payload=self._with_route({"explanation": repaired.explanation}, usage),
                model_provider=usage.provider,
                model_id=usage.model_id,
                cost_usd=usage.cost_usd,
                source_sha256=state.code_sha256,
            ),
        )
        # The repaired program is the next attempt: go straight to Execute.
        return NodeResult(Node.EXECUTE)

    async def verify(self, state: AgentState) -> NodeResult:
        assert state.plan is not None and state.last_execution is not None
        ev = state.last_execution
        result = ev.result or {}
        known = {c.name for c in state.profile}

        vector = VerificationVector(
            plan_valid=not state.plan.is_abstain,
            columns_exist=all(c in known for c in state.plan.referenced_columns),
            execution_ok=ev.ok,
            result_schema_valid=policy.result_schema_valid(state.plan, result, ev.artifacts),
            # A full-table operation (e.g. a row count) legitimately uses no
            # columns; its provenance is the operation itself over the dataset.
            provenance_present=bool(
                result.get("operation")
                or result.get("columns_used")
                or state.plan.referenced_columns
            ),
            policy_ok=ev.exit_class != "policy_violation",
            ambiguous=bool(result.get("ambiguous")),
        )

        # Reasons are tagged by what would actually fix them: a SEMANTIC
        # failure means the PLAN's column choice was wrong (Node.REVISE
        # re-plans); a COMPUTATIONAL failure means the PLAN was fine but the
        # CODE is wrong (Node.REVISE repairs it). Untagged failures (e.g. a
        # sandbox policy_violation) are never revised — see below.
        semantic_reasons: list[str] = []
        computational_reasons: list[str] = []

        contradiction, uncertain, reason = policy.check_column_semantics(
            state.plan, state.profile, self.ctx.dataset.row_count
        )
        if contradiction:
            vector.policy_ok = False
            semantic_reasons.append(reason)
        elif uncertain:
            vector.ambiguous = True
            vector.reasons.append(reason)

        vector.metamorphic_checks = state.challenge_results
        violated = [c for c in state.challenge_results if not c.held]
        if violated:
            # A correct program's answer cannot legitimately change under a
            # row shuffle or column reorder (crucible.agent.metamorphic) — a
            # violation is direct evidence the program is wrong, needing no
            # gold answer to say so. Hard gate: same standing as any other
            # policy failure, never downgraded to merely "ambiguous".
            vector.policy_ok = False
            computational_reasons.extend(
                f"metamorphic check failed ({c.transform}): expected {c.relation}, but {c.detail}"
                for c in violated
            )

        plausibility_violations = policy.check_plausibility(
            state.plan, result, state.profile, self.ctx.dataset.row_count
        )
        if plausibility_violations:
            # A count over the row count, a mean outside the column's own
            # observed range, a NaN — these are logically impossible outcomes
            # for a correct program, not a judgment call. Same hard-gate
            # standing as the metamorphic and anti-fabrication checks.
            vector.policy_ok = False
            computational_reasons.extend(plausibility_violations)

        if not vector.result_schema_valid:
            computational_reasons.append("result did not match the declared answer shape")
        if not vector.provenance_present:
            computational_reasons.append("result carried no provenance (operation/columns_used)")

        vector.reasons.extend(semantic_reasons)
        vector.reasons.extend(computational_reasons)

        vector.decision = policy.decide(vector)
        state.verification = vector
        await self._attempt(
            state, AttemptRecord(kind="verify", sequence_no=0, payload=vector.model_dump())
        )

        if vector.decision is VerificationDecision.ANSWER:
            return NodeResult(Node.SYNTHESIZE)

        # A deliberate abstain from the planner itself: there is no column
        # choice or code bug to revise — the model already said it can't.
        if not vector.plan_valid:
            return self._abstain(state, "verification did not meet the answer threshold")

        revisable = semantic_reasons or computational_reasons
        if vector.decision is VerificationDecision.ABSTAIN and revisable:
            target = Node.PLAN if semantic_reasons else Node.CODE
            fp = policy.revision_fingerprint(
                state.plan.model_dump_json(), semantic_reasons + computational_reasons
            )
            seen_before = fp in state.revision_fingerprints
            state.revision_fingerprints.append(fp)
            state.critique_history.append("; ".join(semantic_reasons + computational_reasons))
            if state.revision_count < policy.MAX_REVISIONS and not seen_before:
                state.revision_count += 1
                state.pending_revision_target = target
                return NodeResult(Node.REVISE)
            state.pending_revision_target = target
            state.detail = (
                "automatic revision budget exhausted"
                if not seen_before
                else "the same verification failure recurred after a revision"
            ) + "; routed to human review"
            return NodeResult(Node.HUMAN_REVIEW)

        if vector.decision is VerificationDecision.REVIEW:
            return NodeResult(Node.HUMAN_REVIEW)
        return self._abstain(state, "verification did not meet the answer threshold")

    async def revise(self, state: AgentState) -> NodeResult:
        """Re-plan or repair using the accumulated critique
        (state.critique_history) — reached either automatically from verify()
        or via a human's "revise" decision (human_review()), which is why the
        target is read from state rather than passed as an argument: both
        callers just set `pending_revision_target` and route here."""
        assert state.plan is not None
        target = state.pending_revision_target
        state.pending_revision_target = None
        critique = "; ".join(state.critique_history) or "verification failed"

        if target is Node.PLAN:
            question = prompts.augment_question_for_revision(state.question, critique)
            try:
                plan, usage = await self.ctx.model.plan(question=question, profile=state.profile)
            except ValueError as exc:
                return self._abstain(
                    state, f"revision planner returned invalid structured output: {exc}"
                )
            await self._attempt(
                state,
                AttemptRecord(
                    kind="revise_plan",
                    sequence_no=state.revision_count,
                    payload=self._with_route(plan.model_dump(), usage),
                    model_provider=usage.provider,
                    model_id=usage.model_id,
                    cost_usd=usage.cost_usd,
                ),
            )
            if plan.is_abstain:
                return self._abstain(state, plan.rationale or "revision: the question is not supported")
            known = {c.name for c in state.profile}
            missing = [c for c in plan.referenced_columns if c not in known]
            if missing:
                return self._abstain(state, f"revision plan referenced unknown columns: {missing}")
            state.plan = plan
            return NodeResult(Node.CODE)

        # target is Node.CODE: repair the existing program against the
        # critique, same shape as reflect()'s crash-repair call but a
        # SEPARATE budget (revision_count, not repair_count) since this is a
        # different failure mode — the code ran; verify() judged it wrong.
        assert state.code_source is not None
        try:
            repaired, usage = await self.ctx.model.repair(
                plan=state.plan,
                profile=state.profile,
                prior_code=state.code_source,
                error=f"The program ran, but verification rejected the answer: {critique}",
            )
        except ValueError as exc:
            return self._abstain(state, f"revision coder returned invalid structured output: {exc}")
        state.code_source = repaired.source
        state.code_sha256 = ExecutionProgram(repaired.source).sha256
        await self._attempt(
            state,
            AttemptRecord(
                kind="revise_code",
                sequence_no=state.revision_count,
                payload=self._with_route({"explanation": repaired.explanation}, usage),
                model_provider=usage.provider,
                model_id=usage.model_id,
                cost_usd=usage.cost_usd,
                source_sha256=state.code_sha256,
            ),
        )
        return NodeResult(Node.EXECUTE)

    async def human_review(self, state: AgentState) -> NodeResult:
        if state.review_decision is None:
            # Interrupt: the run waits for a reviewer. The runner persists at
            # this node and stops without finalizing.
            return NodeResult(Node.HUMAN_REVIEW, interrupt=True)
        decision = state.review_decision
        state.review_decision = None  # consumed; a later interrupt needs a fresh decision
        if decision == "approve":
            return NodeResult(Node.SYNTHESIZE)
        if decision == "revise":
            if state.human_revision_count >= policy.MAX_HUMAN_REVISIONS:
                return self._abstain(state, "human revision budget exhausted")
            state.human_revision_count += 1
            if state.review_feedback:
                state.critique_history.append(f"reviewer feedback: {state.review_feedback}")
            state.review_feedback = None
            target = state.pending_revision_target or Node.PLAN
            state.pending_revision_target = target
            # Fresh human feedback earns a fresh automatic-retry budget rather
            # than inheriting whatever was left (or exhausted) before this
            # review — the human's input is new information, not a retry.
            state.revision_count = 0
            state.revision_fingerprints = []
            return NodeResult(Node.REVISE)
        return self._abstain(state, "a reviewer rejected the answer")

    async def synthesize(self, state: AgentState) -> NodeResult:
        assert state.plan is not None and state.last_execution is not None
        ev = state.last_execution
        result = ev.result or {}
        raw_cols = result.get("columns_used")
        source_cols = raw_cols if isinstance(raw_cols, list) else state.plan.referenced_columns
        columns = [str(c) for c in source_cols]
        provenance = Provenance(
            dataset_version_id=state.dataset_version_id,
            dataset_sha256=state.dataset_sha256,
            operation=state.plan.operation.value,
            columns_used=columns,
            code_sha256=state.code_sha256 or "",
            attempt_count=state.repair_count + 1,
            executor_backend=ev.backend,
            image_ref=ev.image_ref,
        )
        state.answer = build_answer(plan=state.plan, result=result, provenance=provenance)
        return NodeResult(Node.OUTPUT_GUARD)

    async def output_guard(self, state: AgentState) -> NodeResult:
        assert state.answer is not None
        ok, reason = output_guard(state.answer)
        if not ok:
            state.answer = None
            return self._abstain(state, f"output guard rejected the answer: {reason}")
        state.terminal_reason = TerminalReason.ANSWERED
        await self._store_in_cache(state)
        return NodeResult(Node.DONE)

    async def _store_in_cache(self, state: AgentState) -> None:
        """Cache only a fully verified, freshly computed answer. Reviewed or
        abstained runs are never cached (a human decision is not a lookup), and
        a replayed hit is never re-stored."""
        cache = self.ctx.cache
        if (
            cache is None
            or state.cache_key is None
            or state.config_signature is None
            or state.answer is None
            or state.answer.cached
            or state.dataset_sha256 is None
            or state.verification is None
            or state.verification.decision is not VerificationDecision.ANSWER
        ):
            return
        await cache.store(
            organization_id=state.organization_id,
            cache_key=state.cache_key,
            dataset_version_id=state.dataset_version_id,
            dataset_sha256=state.dataset_sha256,
            question_sha256=question_sha256(state.question),
            config_signature=state.config_signature,
            answer=state.answer.model_dump(),
            verification=state.verification.model_dump(),
        )
        await self._attempt(
            state, AttemptRecord(kind="cache", sequence_no=1, payload={"outcome": "store"})
        )


DISPATCH = {
    Node.VALIDATE: "validate",
    Node.PROFILE: "profile",
    Node.EXACT_CACHE: "exact_cache",
    Node.ROUTE: "route",
    Node.PLAN: "plan",
    Node.CODE: "code",
    Node.EXECUTE: "execute",
    Node.OBSERVE: "observe",
    Node.REFLECT: "reflect",
    Node.CHALLENGE: "challenge",
    Node.VERIFY: "verify",
    Node.REVISE: "revise",
    Node.HUMAN_REVIEW: "human_review",
    Node.SYNTHESIZE: "synthesize",
    Node.OUTPUT_GUARD: "output_guard",
}
