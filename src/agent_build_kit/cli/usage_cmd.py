"""`abk usage`: the usage ledger and readings.

`replay` is read-only: it re-runs the estimate over the recorded history.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta

from agent_build_kit import claude_account
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.usage_allowances import (
    WINDOWS,
    allowance_for,
    allowances_line,
    calibrate_pairs,
    calibrated_allowances,
    of_account,
    pairs,
)
from agent_build_kit.pipeline.usage_calls import CALLS_NAME, read_calls
from agent_build_kit.pipeline.usage_guard import WindowEstimate
from agent_build_kit.pipeline.usage_ledger import (
    LEDGER_NAME,
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


def cmd_usage_replay(args: argparse.Namespace, inst: Installation) -> int:
    """Re-run the estimate over each usable gap of the record; writes and asks nothing."""
    account = claude_account.resolve(inst, args.account)
    limits = account.limits
    # Only the readings of the account asked about (the default one without the flag).
    calls, ledger = of_account(
        read_calls(inst.state_dir / CALLS_NAME),
        read_ledger(inst.state_dir / LEDGER_NAME),
        claude_account.account_key(account),
    )
    margin = limits.usage_headroom_margin_pct if args.margin is None else args.margin
    min_gap = timedelta(minutes=limits.usage_cache_minutes)
    now = datetime.now(UTC)
    anywhere = False
    for window in WINDOWS:
        fixed = getattr(args, f"{window}_allowance")
        threshold = getattr(limits, window).usage_pause_pct
        usable = pairs(calls, ledger, window, min_gap=min_gap)
        shown = False
        under = missed = paused = allowed = 0
        overshoots: list[float] = []
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
            under += actual > judged.estimate
            missed += actual > judged.estimate + margin
            paused += not judged.ample and actual < threshold
            allowed += judged.ample and actual >= threshold
            if judged.estimate > actual:
                overshoots.append(judged.estimate - actual)
            shown = anywhere = True
            print(
                f"{window} at={pair.at.isoformat()} before={pair.before} after={actual} "
                f"units={pair.units} allowance={allowance} estimate={judged.estimate:g} "
                f"diff={actual - judged.estimate:g}"
            )
        if shown:
            mean = f"{sum(overshoots) / len(overshoots):.1f}" if overshoots else "none"
            print(
                f"{window}: underestimates {under}, misses beyond margin {missed}, "
                f"false pauses {paused}, false allows {allowed}, mean overshoot {mean}"
            )
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
    print(allowances_line(calibrated_allowances(calls, ledger, limits=limits, now=now), limits))
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
