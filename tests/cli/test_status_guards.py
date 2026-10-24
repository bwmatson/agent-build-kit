"""`abk status` lists the same per-runtime guard states as `abk policy check`, from the one
table in `runtimes/guards.py` (spec: sandbox-guard-fallback)."""

from __future__ import annotations

import argparse
from collections.abc import Iterator
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.sandboxes import Coverage
from agent_build_kit.settings import reload
from tests.cli.guard_listing_support import ACTIVE, KEPT, SKIPPED, state_of
from tests.conftest import make_installation
from tests.runtimes.selectable import SelectableRuntime, select


@pytest.fixture
def machine_runtime(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("ABK_RUNTIME", "claude_code")
    reload(None)
    yield
    monkeypatch.delenv("ABK_RUNTIME", raising=False)
    reload(None)


def status_lines(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *,
    sandbox: bool,
    coverage: Coverage = Coverage.PROCESS,
) -> list[str]:
    select(monkeypatch, SelectableRuntime("claude_code", sandbox_coverage=coverage))
    installation = make_installation(tmp_path, sandbox={"enabled": sandbox})
    capsys.readouterr()
    cli.cmd_status(argparse.Namespace(), installation)
    shown = capsys.readouterr()
    return (shown.out + shown.err).splitlines()


def test_status_lists_a_confined_runtimes_location_guards_as_skipped(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    machine_runtime: None,
) -> None:
    lines = status_lines(tmp_path, monkeypatch, capsys, sandbox=True)

    assert state_of(lines, "worktree check") == SKIPPED
    assert state_of(lines, "specs fence") == SKIPPED
    assert state_of(lines, "merge rules") == KEPT


def test_status_lists_the_location_guards_as_active_with_the_sandbox_off(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    machine_runtime: None,
) -> None:
    lines = status_lines(tmp_path, monkeypatch, capsys, sandbox=False)

    assert state_of(lines, "worktree check") == ACTIVE
    assert state_of(lines, "merge rules") == KEPT


def test_status_lists_the_location_guards_as_active_when_the_runtime_confines_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    machine_runtime: None,
) -> None:
    lines = status_lines(tmp_path, monkeypatch, capsys, sandbox=True, coverage=Coverage.NONE)

    assert state_of(lines, "worktree check") == ACTIVE
