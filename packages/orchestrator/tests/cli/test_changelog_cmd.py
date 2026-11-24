"""`abk changelog check`: the changelog's form, checked for any repo the pipeline builds."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.cli import main
from agent_build_kit.config import RepoConfig, WorkspaceConfig, dump
from tests.factories import git, init_repo

WELL_FORMED = """\
# Changelog

## Unreleased

- A new thing, described for someone using the tool and
  wrapped with a two-space continuation.

- Another thing, with its reason.

## 0.2.0 — 2026-10-01

- Released work.

## 0.1.0 — 2026-09-28

- First release.
"""

# Each way the form can break, as a rewrite of the well-formed text and the line it names.
BROKEN = {
    "conflict marker": (
        WELL_FORMED.replace("- Another thing, with its reason.\n", "<<<<<<< HEAD\n- Another.\n"),
        "<<<<<<< HEAD",
    ),
    "bullets run together": (
        WELL_FORMED.replace(
            "\n- Another thing, with its reason.", "- Another thing, with its reason."
        ),
        "- Another thing, with its reason.",
    ),
    "repeated bullet": (
        WELL_FORMED.replace("- Another thing, with its reason.", "- Released work."),
        "- Released work.",
    ),
    "bullet outside a section": (
        WELL_FORMED.replace("## Unreleased\n", "- Stray.\n\n## Unreleased\n"),
        "- Stray.",
    ),
    "headings out of order": (
        "# Changelog\n\n## 0.1.0 — 2026-09-28\n\n- First release.\n\n"
        "## 0.2.0 — 2026-10-01\n\n- Released work.\n",
        "## 0.2.0 — 2026-10-01",
    ),
}


def run_check(
    capsys: pytest.CaptureFixture[str], *argv: str, config: Path | None = None
) -> tuple[int, str]:
    prefix = ["--config", str(config)] if config else []
    code = main([*prefix, "changelog", "check", *argv])
    captured = capsys.readouterr()
    return code, captured.out + captured.err


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = init_repo(tmp_path / "app")
    (path / "README.md").write_text("app\n")
    git(path, "add", "-A")
    git(path, "commit", "-q", "-m", "init")
    return path


def configure(tmp_path: Path, repo: Path, *, changelog: str | None = "CHANGELOG.md") -> Path:
    planning = init_repo(tmp_path / "planning")
    config = WorkspaceConfig(
        repos={"app": RepoConfig(path=repo, slug="example/app", changelog=changelog)}
    )
    (planning / "abk.yaml").write_text(dump(config))
    return planning / "abk.yaml"


def test_a_well_formed_file_exits_zero(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "CHANGELOG.md"
    path.write_text(WELL_FORMED)

    code, _ = run_check(capsys, str(path))

    assert code == 0


@pytest.mark.parametrize("kind", sorted(BROKEN))
def test_each_problem_is_reported_with_its_path_and_line_and_fails(
    kind: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    text, named = BROKEN[kind]
    path = tmp_path / "CHANGELOG.md"
    path.write_text(text)
    # the second occurrence is the one named where a line repeats a released bullet
    line = max(i for i, found in enumerate(text.splitlines(), start=1) if found == named)

    code, out = run_check(capsys, str(path))

    assert code != 0
    assert f"{path} line {line}" in out


def test_an_absent_file_exits_zero_with_a_note(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out = run_check(capsys, str(tmp_path / "CHANGELOG.md"))

    assert code == 0
    assert "CHANGELOG.md" in out


def test_the_path_comes_from_the_repos_setting_when_none_is_given(
    tmp_path: Path, repo: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    config = configure(tmp_path, repo, changelog="docs/HISTORY.md")
    (repo / "docs").mkdir()
    (repo / "docs" / "HISTORY.md").write_text(BROKEN["bullets run together"][0])
    (repo / "CHANGELOG.md").write_text(WELL_FORMED)
    monkeypatch.chdir(repo)

    code, out = run_check(capsys, config=config)

    assert code != 0
    assert "docs/HISTORY.md line" in out


def test_the_setting_is_found_from_a_worktree_of_the_repo(
    tmp_path: Path, repo: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    config = configure(tmp_path, repo, changelog="docs/HISTORY.md")
    tree = tmp_path / "trees" / "unit"
    git(repo, "worktree", "add", "-q", "-b", "spec/feature/1", str(tree))
    (tree / "docs").mkdir()
    (tree / "docs" / "HISTORY.md").write_text(BROKEN["conflict marker"][0])
    monkeypatch.chdir(tree)

    code, out = run_check(capsys, config=config)

    assert code != 0
    assert "docs/HISTORY.md line" in out


def test_a_set_path_with_no_file_yet_passes_with_a_note(
    tmp_path: Path, repo: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    config = configure(tmp_path, repo)
    monkeypatch.chdir(repo)

    code, out = run_check(capsys, config=config)

    assert code == 0
    assert "CHANGELOG.md" in out


def test_a_repo_with_the_changelog_off_passes_without_reading_the_file(
    tmp_path: Path, repo: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    config = configure(tmp_path, repo, changelog=None)
    (repo / "CHANGELOG.md").write_text(BROKEN["conflict marker"][0])
    monkeypatch.chdir(repo)

    code, _ = run_check(capsys, config=config)

    assert code == 0
