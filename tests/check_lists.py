"""Lists of checks for tests that only care which names failed or were cancelled."""

from __future__ import annotations

from agent_build_kit.forges.base import Check, CheckStatus


def failed_list(*names: str) -> tuple[Check, ...]:
    return tuple(Check(name=name, status=CheckStatus.FAILED) for name in names)


def cancelled_list(*names: str) -> tuple[Check, ...]:
    return tuple(Check(name=name, status=CheckStatus.CANCELLED) for name in names)
