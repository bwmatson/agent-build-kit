"""What a unit's place in progress is counted under: the pool's rounds and admission read it."""

from __future__ import annotations

from collections.abc import Callable, Hashable, Mapping
from dataclasses import dataclass, field

from agent_build_kit import claude_account
from agent_build_kit.config import ProjectLimitsConfig
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.units import Unit, project_key


@dataclass(frozen=True)
class AppliedLimits:
    """The limits that apply to one repo's units: the project's block, and the fields its account
    set. A field the account did not set is absent from `account`, so a default is never read as
    an account limit."""

    project: ProjectLimitsConfig
    account: Mapping[str, int] = field(default_factory=dict[str, int])


def _set_fields(account: claude_account.Account) -> dict[str, int]:
    """The fields of the account's block that it set."""
    block = account.project_limits
    return {name: getattr(block, name) for name in block.model_fields_set}


def limits_for(inst: Installation, repo: str) -> AppliedLimits:
    """The one function that resolves the limits of a repo's units, for the project and for the
    account the repo runs on (the default account, which sets none, adds none)."""
    account = claude_account.for_repo(inst.config, repo)
    return AppliedLimits(project=inst.config.project_limits, account=_set_fields(account))


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
        return _set_fields(named).get("max_units_in_progress", inst.max_units_in_progress)

    return limit


def slot_stack_limit(inst: Installation) -> Callable[[Hashable], int | None]:
    """The builds at once an account allows across its projects, for a slot of `slot_of`: the
    account's `max_concurrent_stacks` when it set one, else none. A project slot, the default
    account and an account that did not set it have none."""
    if not claude_account.slots_per_account(inst.config):
        return lambda _slot: None

    def limit(label: Hashable) -> int | None:
        named = claude_account.resolve(inst, label if isinstance(label, str) else None)
        return _set_fields(named).get("max_concurrent_stacks")

    return limit


def slot_restack_limit(inst: Installation) -> Callable[[Hashable], int | None]:
    """The restacks at once an account allows across its projects, for a slot of `slot_of`: the
    account's `max_concurrent_restacks` when it set one, else none. A project slot, the default
    account and an account that did not set it have none; a project's own cap holds beside it."""
    if not claude_account.slots_per_account(inst.config):
        return lambda _slot: None

    def limit(label: Hashable) -> int | None:
        named = claude_account.resolve(inst, label if isinstance(label, str) else None)
        return _set_fields(named).get("max_concurrent_restacks")

    return limit


def extra_of(inst: Installation) -> Callable[[Hashable], int | None]:
    """The emergency lane places an account allows across its projects, for a slot of `slot_of`:
    the account's `emergency_extra` when it set one (zero included), else none. A project slot,
    the default account and an account that did not set it have none; a project's own extra
    holds beside it."""
    if not claude_account.slots_per_account(inst.config):
        return lambda _slot: None

    def extra(label: Hashable) -> int | None:
        named = claude_account.resolve(inst, label if isinstance(label, str) else None)
        return _set_fields(named).get("emergency_extra")

    return extra


def account_labels(inst: Installation) -> dict[str | None, int]:
    """The limit of each account label the repos run on, when units in progress are counted per
    account; empty when they are counted per project."""
    if not claude_account.slots_per_account(inst.config):
        return {}
    limit = slot_limit(inst)
    return {account.label: limit(account.label) for account in claude_account.in_use(inst.config)}
