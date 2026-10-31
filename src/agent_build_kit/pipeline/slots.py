"""What a unit's place in progress is counted under: the pool's rounds and admission read it."""

from __future__ import annotations

from collections.abc import Callable, Hashable

from agent_build_kit import claude_account
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.units import Unit, project_key


def slot_of(inst: Installation) -> Callable[[Unit], Hashable]:
    """What a unit's place in progress is counted under: its account's label (None for the
    default account) when the installation uses accounts, else its project."""
    if not claude_account.slots_per_account(inst.config):
        return project_key
    return lambda unit: claude_account.for_repo(inst.config, unit.repo).label


def slot_limit(inst: Installation) -> Callable[[Hashable], int]:
    """The units in progress one slot of `slot_of` allows: an account's own limit, else the
    project limit."""
    if not claude_account.slots_per_account(inst.config):
        return lambda _slot: inst.max_units_in_progress

    def limit(label: Hashable) -> int:
        named = claude_account.resolve(inst, label if isinstance(label, str) else None)
        return named.max_units_in_progress or inst.max_units_in_progress

    return limit


def account_labels(inst: Installation) -> dict[str | None, int]:
    """The limit of each account label the repos run on, when units in progress are counted per
    account; empty when they are counted per project."""
    if not claude_account.slots_per_account(inst.config):
        return {}
    limit = slot_limit(inst)
    return {account.label: limit(account.label) for account in claude_account.in_use(inst.config)}
