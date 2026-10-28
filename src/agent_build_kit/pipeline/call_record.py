"""The one writer of an agent call's row in the usage ledger.

The unit graph's steps and every other call that sends a prompt to an agent record through
`call_recorder`, so a row has one shape and a cost one derivation.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from agent_build_kit import claude_account
from agent_build_kit.pipeline.gateway_usage import Spend
from agent_build_kit.pipeline.usage_ledger import (
    Cost,
    CostBasis,
    UsageRecord,
    record_call,
    session_cumulative,
    session_spend,
)
from agent_build_kit.runtimes import AgentRequest, AgentResult, AgentRuntime
from agent_build_kit.usage import Context, Usage

# The session's cumulative cost before a call, by session id.
Baseline = Callable[[str | None], float | None]
# Told after the row is written: the result, the runtime, the model and the session's
# cumulative figure the next call's baseline starts from.
After = Callable[[AgentResult, str, str | None, float | None], None]


def ledger_baseline(session_id: str | None) -> float | None:
    """The session's cumulative cost the active ledger last recorded."""
    return session_cumulative(session_id) if session_id else None


def derive_cost(
    result: AgentResult,
    spent: Spend,
    *,
    exact: bool,
    resumed: bool,
    baseline: float | None,
    say: Callable[[str], None],
) -> tuple[Cost | None, float | None]:
    """The call's cost object and the session's cumulative figure after it, for the
    next call's baseline: the runtime's own, whatever the record says."""
    reported: float | None = None
    runtime_total = result.cumulative_cost_usd
    basis = CostBasis.UNKNOWN
    if runtime_total is not None:
        if baseline is not None and runtime_total >= baseline:
            reported, basis = runtime_total - baseline, CostBasis.DERIVED
        elif baseline is not None:
            say(
                f"the session's cost fell from {baseline} to {runtime_total}: the baseline is reset"
            )
            reported, basis = runtime_total, CostBasis.FIRST
        elif not resumed:
            reported, basis = runtime_total, CostBasis.FIRST
        elif result.cost_usd is not None:
            # No baseline here, but the runtime worked out the call's own spend against
            # the total its agent replayed when the session was loaded.
            reported, basis = result.cost_usd, CostBasis.DERIVED
        cumulative: float | None = runtime_total
    elif result.cost_usd is not None:
        reported, basis = result.cost_usd, CostBasis.REPORTED
        cumulative = (baseline or 0.0) + result.cost_usd
    else:
        cumulative = None
    if exact and spent.cost_usd is not None:
        earlier = session_spend(result.session_id) if result.session_id else None
        cost = Cost(
            incremental_usd=spent.cost_usd,
            cumulative_usd=(earlier or 0.0) + spent.cost_usd,
            basis=CostBasis.REPORTED,
            reported_usd=reported,
        )
    elif reported is None and cumulative is None:
        return None, None
    else:
        cost = Cost(incremental_usd=reported, cumulative_usd=cumulative, basis=basis)
    return cost, runtime_total if runtime_total is not None else cumulative


def call_recorder(
    node: str,
    *,
    unit: str = "",
    change: str = "",
    repo: str = "",
    tier: str = "",
    round: int = 0,
    resumed: bool = False,
    say: Callable[[str], None],
    gateway: Callable[[], Spend] | None = None,
    baseline: Baseline = ledger_baseline,
    after: After | None = None,
    account: str | None = None,
) -> Callable[..., None]:
    """What a runtime calls with the finished `AgentResult`, as
    `record(result, *, role, model, runtime, gateway=None)`. `baseline` finds the session's
    cumulative cost before a call; `after` is told what the call ended on."""

    def record(
        result: AgentResult,
        *,
        role: str,
        model: str | None,
        runtime: str,
        gateway: Callable[[], Spend] | None = gateway,
    ) -> None:
        # What the gateway logged for the call's own key is exact; what the
        # agent said is kept beside it, for the report to compare.
        spent = gateway() if gateway else Spend()
        exact = spent.usage is not None
        usage = (spent.usage if exact else result.usage) or Usage()
        cost, cumulative = derive_cost(
            result,
            spent,
            exact=exact,
            resumed=resumed,
            baseline=baseline(result.session_id),
            say=say,
        )
        if after is not None:
            after(result, runtime, model, cumulative)
        line = UsageRecord(
            at=datetime.now(UTC).isoformat(),
            unit=unit,
            node=node,
            round=round,
            change=change,
            repo=repo,
            tier=tier,
            role=role,
            model=model,
            reported_model=result.reported_model,
            runtime=runtime,
            session_id=result.session_id,
            resumed=resumed,
            **usage.model_dump(),
            cost=cost,
            context=result.context or Context(),
            turns=result.turns,
            duration_ms=result.duration_ms,
            usage_source="gateway" if exact else result.usage_source,
            reported=result.usage if exact else None,
            outcome="ok" if result.succeeded else "failed",
            account=account,
        )
        record_call(line, say)

    return record


def recorded(
    request: AgentRequest,
    runtime: AgentRuntime,
    *,
    node: str,
    unit: str = "",
    change: str = "",
    repo: str = "",
    tier: str = "",
    round: int = 0,
    resumed: bool = False,
    say: Callable[[str], None],
) -> AgentRequest:
    """`request` with `on_result` writing the call's row under `node`; a callback the
    request already had is called first."""
    record = call_recorder(
        node,
        unit=unit,
        change=change,
        repo=repo,
        tier=tier,
        round=round,
        resumed=resumed,
        say=say,
        account=claude_account.account_key(request.account or claude_account.Account.default()),
    )
    earlier = request.on_result

    def done(result: AgentResult) -> None:
        if earlier is not None:
            earlier(result)
        record(result, role=request.role, model=request.model, runtime=runtime.name)

    return request.model_copy(update={"on_result": done})
