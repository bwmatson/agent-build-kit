"""A second `abk config --migrate` changes nothing, and a dry run shows the diffs and writes
nothing."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.runtimes.policy_apply import BACKUP_SUFFIX
from tests.cli.config_migrate_fakes import beside, run_migrate
from tests.cli.config_migrate_machine_fakes import MACHINE, tracked
from tests.cli.config_migrate_running_fakes import running_unit

WITH_DEFAULTS = (
    MACHINE + "runtimes:\n  claude_code:\n    limits:\n      max_units_in_progress: 3\n"
    "tests:\n  e2e_schedule: off\n"
)
NOTHING = "nothing needed migrating"


def snapshot(root: Path) -> dict[str, bytes]:
    """The bytes of every file under `root` other than git's own."""
    return {
        str(entry.relative_to(root)): entry.read_bytes()
        for entry in sorted(root.rglob("*"))
        if entry.is_file() and entry.relative_to(root).parts[0] != ".git"
    }


@pytest.mark.parametrize("flags", [(), ("--include-defaults",)], ids=["plain", "defaults"])
def test_a_second_run_prints_nothing_to_migrate_and_changes_nothing(
    flags: tuple[str, ...],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tracked(tmp_path, WITH_DEFAULTS)
    first, _ = run_migrate(capsys, monkeypatch, path, "--yes", *flags)
    assert first == 0
    files = snapshot(tmp_path)
    names = beside(path)

    code, terminal = run_migrate(capsys, monkeypatch, path, *flags, answers=())

    assert code == 0
    assert NOTHING in terminal.out
    assert terminal.asked == 0
    assert snapshot(tmp_path) == files
    assert beside(path) == names
    assert names.count(path.name + BACKUP_SUFFIX) == 1


def test_a_dry_run_prints_the_diffs_and_the_hint_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tracked(tmp_path)
    path.write_text(MACHINE + "# not committed\n")
    running_unit(tmp_path)
    files = snapshot(tmp_path)

    code, terminal = run_migrate(capsys, monkeypatch, path, "--dry-run", answers=())

    assert code == 0
    assert terminal.asked == 0
    local = tmp_path / "abk.local.yaml"
    assert f"+++ {path}" in terminal.out
    assert f"+++ {local}" in terminal.out
    assert "has changes git has not committed" in terminal.err
    assert "is running" not in terminal.err
    assert snapshot(tmp_path) == files
    assert beside(path) == [".git", "runs"]
