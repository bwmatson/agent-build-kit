"""Commands a separately installed package registers through the `abk.commands` entry-point
group: `abk worker` is one, and without its package it says so instead of failing every command
(spec: kit-has-a-worker-package)."""

from __future__ import annotations

import importlib.metadata
import sys
import types
from collections.abc import Callable
from typing import Any

import pytest

from agent_build_kit.cli import COMMANDS_GROUP, build_parser, main

EntryPoint = importlib.metadata.EntryPoint
EntryPoints = importlib.metadata.EntryPoints

GONE = "the entry is absent"
MISSING_MODULE = "the entry names a module that is not installed"


def installed(monkeypatch: pytest.MonkeyPatch, replace_worker: EntryPoint | None) -> None:
    """Make the group list the real entries but the worker's, which `replace_worker` stands in
    for (nothing when it is None)."""
    real = importlib.metadata.entry_points

    def listed(group: str) -> EntryPoints:
        found = real(group=group)
        if group != COMMANDS_GROUP:
            return found
        kept = [e for e in found if e.name != "worker"]
        return EntryPoints([*kept, *([replace_worker] if replace_worker else [])])

    monkeypatch.setattr(importlib.metadata, "entry_points", listed)


def absent() -> EntryPoint | None:
    return None


def unimportable() -> EntryPoint | None:
    return EntryPoint(
        name="worker", value="agent_build_kit.cli.nonexistent:register", group=COMMANDS_GROUP
    )


def test_the_worker_command_is_registered_by_the_register_function_its_entry_point_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def register(sub: Any) -> None:
        sub.add_parser("worker").set_defaults(marker="registered by the entry point")

    monkeypatch.setitem(sys.modules, "worker_stand_in", types.SimpleNamespace(register=register))
    installed(
        monkeypatch,
        EntryPoint(name="worker", value="worker_stand_in:register", group=COMMANDS_GROUP),
    )

    args = build_parser().parse_args(["worker"])

    assert args.marker == "registered by the entry point"


@pytest.mark.parametrize("stand_in", [absent, unimportable], ids=[GONE, MISSING_MODULE])
def test_abk_worker_without_the_worker_package_says_so_and_exits_2(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    stand_in: Callable[[], EntryPoint | None],
) -> None:
    installed(monkeypatch, stand_in())

    code = main(["worker", "build", "x"])

    captured = capsys.readouterr()
    assert code == 2
    assert "worker package is not installed" in captured.out + captured.err


def test_a_command_whose_entry_point_module_is_missing_leaves_the_other_commands_parsing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    installed(monkeypatch, unimportable())

    args = build_parser().parse_args(["status"])

    assert args.command == "status"
