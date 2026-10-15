"""`abk init` ignores `abk.local.yaml` beside the other local files and says what it is for
(spec: local-config-overlay)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.cli import main
from tests.cli.init_quiet import app_repo, quiet
from tests.cli.test_init_local_ignore import FLAGS, init, squashed, tree
from tests.factories import recognised_planning

LOCAL_LINES = ["abk.local.yaml", "scrub.local", "*.pre-redact"]


@pytest.fixture(autouse=True)
def quiet_init(monkeypatch: pytest.MonkeyPatch) -> None:
    quiet(monkeypatch)
    for name in ("NAME", "EMAIL"):
        monkeypatch.setenv(f"GIT_AUTHOR_{name}", "t")
        monkeypatch.setenv(f"GIT_COMMITTER_{name}", "t")


def test_init_in_an_empty_directory_ignores_all_three_and_creates_no_overlay(
    tmp_path: Path,
) -> None:
    assert init(tmp_path) == 0

    planning = tmp_path / "planning"
    lines = (planning / ".gitignore").read_text().splitlines()
    assert all(lines.count(line) == 1 for line in LOCAL_LINES)
    assert not (planning / "abk.local.yaml").exists()


def test_an_ignore_file_holding_the_overlay_line_gets_only_the_others_and_a_rerun_changes_nothing(
    tmp_path: Path,
) -> None:
    planning = recognised_planning(tmp_path / "planning")
    (planning / ".gitignore").write_text("abk.local.yaml\n")
    argv = ["init", str(planning), "--repo", str(app_repo(tmp_path)), *FLAGS]

    assert main(argv) == 0
    first = tree(planning)
    assert main(argv) == 0

    lines = (planning / ".gitignore").read_text().splitlines()
    assert all(lines.count(line) == 1 for line in LOCAL_LINES)
    assert tree(planning) == first
    assert "abk.local.yaml" in tree(planning)["openspec/config.yaml"]


def test_the_output_and_the_planning_context_say_what_the_overlay_is_for(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert init(tmp_path) == 0

    context = squashed((tmp_path / "planning" / "openspec" / "config.yaml").read_text())
    output = squashed(capsys.readouterr().out)
    for text in (context, output):
        assert "abk.local.yaml" in text
        assert "user-specific" in text
        assert "structured" in text
        assert ".env" in text
