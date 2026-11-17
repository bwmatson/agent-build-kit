"""Test support: the module a name the tick's run code reads is patched on.

The runs a unit gets live in `agent_build_kit.run_support` (shared by the dispatcher and the
worker) and `agent_build_kit.worker_run` (the worker's own), so a name those runs read is replaced
there and not on the dispatcher's command module."""

from __future__ import annotations

from types import ModuleType

from agent_build_kit import run_support, worker_run
from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline import events

RUN_SUPPORT_NAMES = frozenset(
    {
        "current_usage",
        "build_runner",
        "may_start_unit",
        "decide_start",
        "build_unit_test",
    }
)
WORKER_RUN_NAMES = frozenset({"run_unit_thread"})
EVENT_NAMES = frozenset({"build_restack"})


def patch_target(name: str) -> ModuleType:
    """The module whose `name` the code under test reads."""
    if name in RUN_SUPPORT_NAMES:
        return run_support
    if name in WORKER_RUN_NAMES:
        return worker_run
    if name in EVENT_NAMES:
        return events
    return cli
