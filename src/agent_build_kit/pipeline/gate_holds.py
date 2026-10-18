"""Evaluating every split's gate and keeping its result in the held set (spec: split-gate-usage)."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Literal

from agent_build_kit.config import E2eSplit, GateConfig
from agent_build_kit.installation import Installation
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.e2e_holds import (
    SOURCE_GATE,
    Hold,
    current_holds,
    declared_splits,
    held_splits,
    remove_hold,
    write_hold,
)
from agent_build_kit.pipeline.shell import Run
from agent_build_kit.pipeline.usage_guard import GateResult, gate_result

# Who the held set records as the writer of a gate entry.
EVALUATOR = "gate evaluation"


class GateAction(Frozen):
    """What an evaluation did, or would do, to one split's gate entry."""

    split: str
    action: Literal["hold", "renew", "lift"]
    reason: str


def split_gates(installation: Installation) -> dict[str, GateConfig]:
    """Each split's gate, the top-level declaration first and then any repo's own."""
    config = installation.config
    gates: dict[str, GateConfig] = {}
    declarations = [config.tests.e2e_splits]
    declarations += [
        repo.tests.e2e_splits for repo in config.repos.values() if repo.tests.e2e_splits is not None
    ]
    for declared in declarations:
        for name, entry in declared.items():
            if entry.gate is not None:
                gates.setdefault(name, entry.gate)
    return gates


def evaluate_gates(
    installation: Installation,
    *,
    now: datetime,
    dry_run: bool = False,
    refresh: bool = False,
    read: Callable[[], object] | None = None,
    run: Run = subprocess.run,
) -> list[GateAction]:
    """Evaluate every split with a gate and write, renew or lift its `gate` entry; with
    `dry_run` only report. The only writer of gate entries: an entry of another source, and a
    split the configuration holds, are left alone."""
    gates = split_gates(installation)
    if not gates:
        return []
    state = installation.state_dir
    configured_hold = {
        split.name for split in declared_splits(installation.config) if split.hold is True
    }
    # The file's own entries, read with no configured `hold` so that a hand-set entry on a split
    # the configuration releases (or one no repo declares) is seen and left alone.
    unconfigured = tuple(E2eSplit(name=name) for name in gates)
    current = held_splits(unconfigured, state, now=now).held
    # Entries that ran out still say a gate wrote them, so a rewrite is a renewal.
    written = held_splits(unconfigured, state, now=datetime.min.replace(tzinfo=UTC)).held
    actions: list[GateAction] = []
    for name, gate in gates.items():
        existing = current.get(name)
        previous = written.get(name)
        if name in configured_hold or (existing and existing.source != SOURCE_GATE):
            continue
        standing = existing is not None
        renewing = previous is not None and previous.source == SOURCE_GATE
        result = gate_result(
            name,
            gate,
            now=now,
            state_dir=state,
            root=installation.root,
            standing=standing,
            refresh=refresh,
            read=read,
            run=run,
            persist=not dry_run,
        )
        until = result.until
        reason = result.reason
        if result.state == "unknown":
            if gate.on_unknown.value != "hold":
                continue
            reason = f"usage unknown: {result.reason}"
            until = now + timedelta(minutes=gate.usage_stale_retry_minutes)
            if existing is not None and existing.until is not None:
                # A standing hold is never shortened by an unreadable result.
                until = max(existing.until, until)
        elif result.state == "usable":
            if standing:
                if not dry_run:
                    remove_hold(state, name)
                actions.append(GateAction(split=name, action="lift", reason=reason))
            continue
        if not dry_run:
            write_hold(
                state, name, reason=reason, source=SOURCE_GATE, by=EVALUATOR, until=until, now=now
            )
        actions.append(
            GateAction(split=name, action="renew" if renewing else "hold", reason=reason)
        )
    return actions


def _age_minutes(result: GateResult, now: datetime) -> str:
    return (
        ""
        if result.taken_at is None
        else f", {int((now - result.taken_at).total_seconds() // 60)}m old"
    )


def gate_standing(hold: Hold | None) -> bool:
    """Whether `hold`, the split's entry in the held set, is one a gate evaluation wrote."""
    return hold is not None and hold.source == SOURCE_GATE


def gate_status_line(
    split: str,
    gate: GateConfig,
    result: GateResult,
    hold: Hold | None,
    *,
    now: datetime,
) -> str:
    """The `abk status` line for one split's gate: the figures, the threshold, the reset, the
    state and where the figure came from. The state is `held` whenever the held set holds the
    split; a hold of another source names that source, since it and not the gate's figures is
    what holds the split."""
    provider = gate.provider
    source = "provider reading" if provider is not None else "command result"
    where = f"{source}{_age_minutes(result, now)}"
    subject = f"gate usage: {split} ({provider.name if provider else 'command'})"
    if hold is None:
        state = result.state
    elif gate_standing(hold):
        state = "held"
    else:
        state = f"held ({hold.source or ' and '.join(hold.origins)})"
    if result.state == "unknown":
        return f"{subject} {state}: {result.reason} ({where})"
    if provider is None or result.used_amount is None or result.window_end is None:
        reason = f": {result.reason}" if result.reason else ""
        return f"{subject} {state}{reason} ({where})"
    return (
        f"{subject} {result.used_amount:.2f} of {provider.budget_usd:g} USD ({result.used_pct}%), "
        f"{result.threshold_note}, resets {result.window_end.astimezone(UTC):%m-%d %H:%M} UTC, "
        f"{state} ({where})"
    )


def gate_status_lines(
    installation: Installation,
    *,
    now: datetime,
    refresh: bool = False,
    read: Callable[[], object] | None = None,
    run: Run = subprocess.run,
) -> list[str]:
    """One line for each split with a gate, for `abk status`. Without `refresh` the cache is all
    that is read: no provider is asked and no command run."""
    held = current_holds(installation.config, installation.state_dir, now=now).held
    lines = []
    for name, gate in split_gates(installation).items():
        result = gate_result(
            name,
            gate,
            now=now,
            state_dir=installation.state_dir,
            root=installation.root,
            standing=gate_standing(held.get(name)),
            refresh=refresh,
            fetch=refresh,
            read=read,
            run=run,
        )
        lines.append(gate_status_line(name, gate, result, held.get(name), now=now))
    return lines
