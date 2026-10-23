"""`abk usage`: the usage ledger and readings.

`replay` is read-only: it re-runs the estimate over the recorded history.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta

from agent_build_kit import claude_account
from agent_build_kit.config import ClaudeLimitsConfig
from agent_build_kit.installation import Installation
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.usage_allowances import (
    WINDOWS,
    Calibrated,
    CostPair,
    UsagePair,
    Window,
    allowance_for,
    allowances_line,
    calibrate_pairs,
    calibrated_allowances,
    cost_pairs,
    gap_estimates,
    of_account,
    pairs,
)
from agent_build_kit.pipeline.usage_calls import UsageCall, calls_path, read_calls
from agent_build_kit.pipeline.usage_guard import WindowEstimate
from agent_build_kit.pipeline.usage_ledger import (
    LEDGER_NAME,
    UsageRecord,
    read_ledger,
)


def _since(value: str) -> datetime:
    try:
        at = datetime.fromisoformat(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a time: {value!r}") from None
    return at if at.tzinfo else at.replace(tzinfo=UTC)


def _points(value: str) -> int:
    try:
        points = int(value)
    except ValueError:
        points = -1
    if points < 0:
        raise argparse.ArgumentTypeError(f"not a whole number of points, 0 or more: {value!r}")
    return points


class CostGap(Frozen):
    """A cost pair judged both ways: the flat estimate and the cost fit's, from the pairs
    before it. No cost estimate where those pairs make no fit."""

    cost_usd: float
    actual: int
    flat: WindowEstimate
    cost_estimate: WindowEstimate | None


def _cost_gaps(
    calls: list[UsageCall],
    ledger: list[UsageRecord],
    flat_pairs: list[UsagePair],
    window: Window,
    args: argparse.Namespace,
    limits: ClaudeLimitsConfig,
    now: datetime,
    margin: int,
) -> dict[datetime, CostGap]:
    """The cost pairs after the first `usage_cost_min_pairs`, by time, judged both ways; none
    for a window on the units basis."""
    if getattr(limits, window).usage_estimate_basis == "units":
        return {}
    usable = cost_pairs(
        calls, ledger, window, min_gap=timedelta(minutes=limits.usage_cache_minutes)
    )
    threshold = getattr(limits, window).usage_pause_pct
    made = {}
    for index in range(limits.usage_cost_min_pairs, len(usable)):
        pair = usable[index]
        if args.since is not None and pair.at < args.since:
            continue
        flat, cost = gap_estimates(
            index,
            usable,
            flat_pairs,
            limits=limits,
            window=window,
            now=now,
            fixed=getattr(args, f"{window}_allowance"),
        )

        def judged(spent: float, pair: CostPair = pair) -> WindowEstimate:
            return WindowEstimate(
                name=window,
                read_pct=pair.before,
                spent_pct=spent,
                threshold=threshold,
                margin=margin,
            )

        made[pair.at] = CostGap(
            cost_usd=pair.cost_usd,
            actual=pair.before + pair.gain,
            flat=judged(flat),
            cost_estimate=None if cost is None else judged(cost),
        )
    return made


def _counts(judgements: list[tuple[WindowEstimate, int]]) -> str:
    """Underestimates, misses beyond the margin, false pauses, false allows and the mean
    overshoot of estimates against the readings that followed."""
    under = missed = paused = allowed = 0
    overshoots: list[float] = []
    for judged, actual in judgements:
        under += actual > judged.estimate
        missed += actual > judged.estimate + judged.margin
        paused += not judged.ample and actual < judged.threshold
        allowed += judged.ample and actual >= judged.threshold
        if judged.estimate > actual:
            overshoots.append(judged.estimate - actual)
    mean = f"{sum(overshoots) / len(overshoots):.1f}" if overshoots else "none"
    return (
        f"underestimates {under}, misses beyond margin {missed}, "
        f"false pauses {paused}, false allows {allowed}, mean overshoot {mean}"
    )


def _verdict(window: Window, kept: Calibrated | None, limits: ClaudeLimitsConfig) -> str:
    """The calibration's verdict on the cost basis for `window`."""
    head = f"{window} cost basis"
    needed = limits.usage_cost_min_pairs
    if kept is None:
        return f"{head} not used (calibration off)"
    if kept.basis == "cost":
        return (
            f"{head} adopted ({kept.cost_pairs_judged} gaps judged; false allows "
            f"{kept.false_allows_cost} cost, {kept.false_allows_flat} flat)"
        )
    why = {
        "basis_units": "usage_estimate_basis is units",
        "too_few_pairs": (
            f"too few pairs with cost ({kept.cost_pairs_held} held, {needed} needed)"
        ),
        "too_few_judged": (f"too few gaps judged ({kept.cost_pairs_judged} held, {needed} needed)"),
        "more_false_allows": (
            f"more false allows than flat (cost {kept.false_allows_cost}, "
            f"flat {kept.false_allows_flat})"
        ),
        "no_fit": "no fit",
    }.get(kept.reason or "", kept.reason or "unknown")
    return f"{head} not adopted: {why}"


def cmd_usage_replay(args: argparse.Namespace, inst: Installation) -> int:
    """Re-run the estimate over each usable gap of the record; writes and asks nothing."""
    account = claude_account.resolve(inst, args.account)
    limits = account.limits
    # Only the readings of the account asked about (the default one without the flag).
    calls, ledger = of_account(
        read_calls(calls_path(inst.state_dir, account)),
        read_ledger(inst.state_dir / LEDGER_NAME),
        account,
    )
    margin = limits.usage_headroom_margin_pct if args.margin is None else args.margin
    min_gap = timedelta(minutes=limits.usage_cache_minutes)
    now = datetime.now(UTC)
    anywhere = False
    for window in WINDOWS:
        fixed = getattr(args, f"{window}_allowance")
        threshold = getattr(limits, window).usage_pause_pct
        usable = pairs(calls, ledger, window, min_gap=min_gap)
        cost_gaps = _cost_gaps(calls, ledger, usable, window, args, limits, now, margin)
        shown = False
        judgements: list[tuple[WindowEstimate, int]] = []
        for index, pair in enumerate(usable):
            if args.since is not None and pair.at < args.since:
                continue
            allowance = fixed
            if allowance is None:
                found = calibrate_pairs(usable[:index], limits=limits, now=now)
                allowance = allowance_for(window, found, limits)
            judged = WindowEstimate(
                name=window,
                read_pct=pair.before,
                spent_pct=allowance * pair.units,
                threshold=threshold,
                margin=margin,
            )
            actual = pair.before + pair.gain
            judgements.append((judged, actual))
            shown = anywhere = True
            costed = cost_gaps.get(pair.at)
            extra = (
                ""
                if costed is None or costed.cost_estimate is None
                else f" cost=${costed.cost_usd:g} cost_estimate={costed.cost_estimate.estimate:g}"
            )
            print(
                f"{window} at={pair.at.isoformat()} before={pair.before} after={actual} "
                f"units={pair.units} allowance={allowance} estimate={judged.estimate:g} "
                f"diff={actual - judged.estimate:g}{extra}"
            )
        if shown:
            print(f"{window}: {_counts(judgements)}")
        costed_gaps = [gap for gap in cost_gaps.values() if gap.cost_estimate is not None]
        if costed_gaps:
            print(f"{window} flat: {_counts([(gap.flat, gap.actual) for gap in costed_gaps])}")
            by_cost = [(gap.cost_estimate, gap.actual) for gap in costed_gaps if gap.cost_estimate]
            print(f"{window} cost: {_counts(by_cost)}")
        if len(usable) < limits.usage_allowance_min_pairs:
            print(
                f"{window} not enough to judge: {len(usable)} usable gaps of "
                f"{limits.usage_allowance_min_pairs} needed"
            )
        print(
            f"{window} threshold: usage_pause_pct {threshold} (static: the record keeps no "
            "reset times, so a threshold that moves towards a reset is not modelled)"
        )
    if not anywhere:
        print("no usable gap")
    found = calibrated_allowances(calls, ledger, limits=limits, now=now, account=account)
    for window in WINDOWS:
        print(_verdict(window, found.get(window), limits))
    print(allowances_line(found, limits))
    return 0


def register(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser(
        "usage",
        help="the usage readings: a read-only replay",
    )
    commands = parser.add_subparsers(dest="usage_command", required=True)
    replay = commands.add_parser("replay", help="re-run the usage estimate over the history")
    replay.add_argument(
        "--account",
        default=None,
        help="the label of the account to replay (default: the default account)",
    )
    replay.add_argument(
        "--since", type=_since, default=None, help="only gaps whose first reading is this late"
    )
    replay.add_argument(
        "--session-allowance", type=_points, default=None, help="points a unit costs, session"
    )
    replay.add_argument(
        "--weekly-allowance", type=_points, default=None, help="points a unit costs, week"
    )
    replay.add_argument(
        "--margin", type=_points, default=None, help="points of headroom an estimate must leave"
    )
    replay.set_defaults(func=cmd_usage_replay)
