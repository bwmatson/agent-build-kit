"""Test support: the module a name the tick's run code reads is patched on.

The worker's runs live in `agent_build_kit.worker_run`, so a name those runs read is replaced there
and not on the dispatcher's command module."""

from __future__ import annotations

from types import ModuleType

from agent_build_kit import worker_run
from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline import events

WORKER_RUN_NAMES = frozenset(
    {
        "current_usage",
        "build_runner",
        "may_start_unit",
        "decide_start",
        "run_unit_thread",
        "build_unit_test",
    }
)
EVENT_NAMES = frozenset({"build_restack"})


def patch_target(name: str) -> ModuleType:
    """The module whose `name` the code under test reads."""
    if name in WORKER_RUN_NAMES:
        return worker_run
    if name in EVENT_NAMES:
        return events
    return cli
