"""`abk status` shows the unit-test slots when a limit is set (spec: unit-test-concurrency): the
holder of each slot and the units that wait; nothing when no limit is set."""

from __future__ import annotations

import argparse
import re
import threading
from contextlib import ExitStack
from pathlib import Path

import pytest

from agent_build_kit import config as config_module
from agent_build_kit.cli import pipeline as cli
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.unit_test_slots import unit_test_slot
from tests.conftest import make_installation
from tests.factories import stored_unit
from tests.fake_clock import install


def limited(limit: int | None) -> None:
    current = config_module.active()
    config_module.activate(
        current.model_copy(
            update={
                "global_limits": current.global_limits.model_copy(
                    update={"max_concurrent_unit_tests": limit}
                )
            }
        ),
        config_module.active_root(),
    )


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Installation:
    installation = make_installation(
        tmp_path, planning=dict(state_dir=".", worktree_root=str(tmp_path.parent / "trees"))
    )
    UnitStore(tmp_path / "units.json").upsert([stored_unit("one/1", change="one")])
    monkeypatch.setattr(cli, "current_usage", lambda: None)
    install(monkeypatch)
    return installation


def slot_lines(workspace: Installation, capsys: pytest.CaptureFixture[str]) -> list[str]:
    assert cli.cmd_status(argparse.Namespace(), workspace) == 0
    unstamped = [re.sub(r"^\[[^\]]*\] ", "", line) for line in capsys.readouterr().out.splitlines()]
    return [line for line in unstamped if line.startswith("unit-test slots")]


def test_the_holders_and_a_waiting_unit_are_named(
    workspace: Installation, capsys: pytest.CaptureFixture[str]
) -> None:
    limited(2)
    release, waiting = threading.Event(), threading.Event()

    def wait_for_a_slot() -> None:
        with unit_test_slot(
            workspace.locks_dir, 2, holder="c/1", on_wait=lambda message: waiting.set()
        ):
            release.wait(timeout=20)

    with ExitStack() as held:
        held.enter_context(unit_test_slot(workspace.locks_dir, 2, holder="a/1"))
        held.enter_context(unit_test_slot(workspace.locks_dir, 2, holder="b/1"))
        thread = threading.Thread(target=wait_for_a_slot, daemon=True)
        thread.start()
        assert waiting.wait(timeout=20)

        [line] = slot_lines(workspace, capsys)
    release.set()
    thread.join(timeout=20)

    assert "slot 1 held by a/1" in line and "slot 2 held by b/1" in line
    assert "waiting: c/1" in line


def test_nothing_is_said_when_no_limit_is_set(
    workspace: Installation, capsys: pytest.CaptureFixture[str]
) -> None:
    limited(None)

    assert slot_lines(workspace, capsys) == []
