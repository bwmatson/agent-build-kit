"""`abk policy check` lists, per runtime, each guard as active, skipped (confined) or kept
(meaning), from the one table in `runtimes/guards.py` (spec: sandbox-guard-fallback)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit import runtimes
from agent_build_kit.cli import main
from agent_build_kit.config import SandboxConfig
from agent_build_kit.runtimes.guards import guard_lines
from agent_build_kit.sandboxes import Coverage
from tests.cli.guard_listing_support import ACTIVE, KEPT, SKIPPED, state_of
from tests.cli.policy_step_fakes import configured
from tests.cli.sandbox_cli_support import CountingBackend, switch_on
from tests.cli.sandbox_cli_support import stand_in as stand_in  # noqa: F401 — fixture
from tests.cli.test_init import app, stubs  # noqa: F401 — fixtures
from tests.conftest import make_installation
from tests.runtimes.selectable import SelectableRuntime


def check(
    tmp_path: Path,
    app: Path,  # noqa: F811 — fixture
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    runtime: SelectableRuntime,
    *,
    sandbox: bool,
) -> list[str]:
    planning = configured(tmp_path, app, monkeypatch, runtime)
    if sandbox:
        switch_on(planning / "abk.yaml")
    capsys.readouterr()
    main(["--config", str(planning / "abk.yaml"), "policy", "check"])
    shown = capsys.readouterr()
    return (shown.out + shown.err).splitlines()


def test_a_confined_claude_code_shows_its_location_guards_skipped_and_its_meaning_guards_kept(
    tmp_path: Path,
    app: Path,  # noqa: F811 — fixture
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    stand_in: CountingBackend,  # noqa: F811 — fixture
) -> None:
    runtime = SelectableRuntime("claude_code", sandbox_coverage=Coverage.PROCESS)

    lines = check(tmp_path, app, monkeypatch, capsys, runtime, sandbox=True)

    assert state_of(lines, "worktree check") == SKIPPED
    assert state_of(lines, "specs fence") == SKIPPED
    assert state_of(lines, "merge rules") == KEPT


def test_the_same_runtime_with_the_sandbox_off_shows_the_location_guards_active(
    tmp_path: Path,
    app: Path,  # noqa: F811 — fixture
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime = SelectableRuntime("claude_code", sandbox_coverage=Coverage.PROCESS)

    lines = check(tmp_path, app, monkeypatch, capsys, runtime, sandbox=False)

    assert state_of(lines, "worktree check") == ACTIVE
    assert state_of(lines, "specs fence") == ACTIVE
    assert state_of(lines, "merge rules") == KEPT


def test_a_confined_acp_shows_its_command_text_fence_skipped_and_the_client_checks_kept(
    tmp_path: Path,
    app: Path,  # noqa: F811 — fixture
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    stand_in: CountingBackend,  # noqa: F811 — fixture
) -> None:
    runtime = SelectableRuntime("acp", sandbox_coverage=Coverage.PROCESS)

    lines = check(tmp_path, app, monkeypatch, capsys, runtime, sandbox=True)

    assert state_of(lines, "command-text fence") == SKIPPED
    assert state_of(lines, "client file checks") not in (None, SKIPPED)
    assert state_of(lines, "merge rules") == KEPT


def test_a_runtime_that_confines_nothing_keeps_every_location_guard_active(
    tmp_path: Path,
    app: Path,  # noqa: F811 — fixture
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    stand_in: CountingBackend,  # noqa: F811 — fixture
) -> None:
    runtime = SelectableRuntime("claude_code", sandbox_coverage=Coverage.NONE)

    lines = check(tmp_path, app, monkeypatch, capsys, runtime, sandbox=True)

    assert state_of(lines, "worktree check") == ACTIVE


def test_the_listing_is_the_one_the_table_gives(
    tmp_path: Path,
    app: Path,  # noqa: F811 — fixture
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    stand_in: CountingBackend,  # noqa: F811 — fixture
) -> None:
    runtime = SelectableRuntime("claude_code", sandbox_coverage=Coverage.PROCESS)
    lines = check(tmp_path, app, monkeypatch, capsys, runtime, sandbox=True)

    installation = make_installation(tmp_path / "other", sandbox=SandboxConfig(enabled=True))
    expected = guard_lines(runtimes.get("claude_code"), installation)
    assert expected
    for line in expected:
        assert any(line in shown for shown in lines), line
