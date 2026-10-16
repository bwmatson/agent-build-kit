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
    declared_splits,
    held_splits,
    remove_hold,
    write_hold,
)
from agent_build_kit.pipeline.shell import Run
from agent_build_kit.pipeline.usage_guard import gate_result

# Who the held set records as the writer of a gate entry.
EVALUATOR = "gate evaluation"


class GateAction(Frozen):
    """What an evaluation did, or would do, to one split's gate entry."""

    split: str
    action: Literal["hold", "renew", "lift"]
    reason: str


def _gates(installation: Installation) -> dict[str, GateConfig]:
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
    gates = _gates(installation)
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
