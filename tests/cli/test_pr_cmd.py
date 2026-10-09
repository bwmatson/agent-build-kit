"""`abk pr view` and `abk pr diff`: an agent reads its local pull request (spec: local-forge).

The pull request is opened on a real repository with no remote; the commands run through the
real command line and are checked for what they print and for what they leave alone.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from agent_build_kit.cli import main
from agent_build_kit.config import dump
from agent_build_kit.forges.local import FILE, LocalForge
from tests.conftest import make_installation
from tests.factories import git, init_repo

HEAD = "spec/feature/2"


@dataclass
class Opened:
    repo: Path
    state: Path
    config: Path
    number: int

    def run(self, *argv: str) -> int:
        return main(["--config", str(self.config), *argv])

    def snapshot(self) -> tuple[str, str]:
        return (
            (self.state / FILE).read_text(),
            git(self.repo, "for-each-ref", "--format=%(refname) %(objectname)"),
        )


@pytest.fixture
def opened(tmp_path: Path) -> Opened:
    repo = init_repo(tmp_path / "app")
    (repo / "base.txt").write_text("base\n")
    git(repo, "add", "base.txt")
    git(repo, "commit", "-q", "-m", "base")
    git(repo, "checkout", "-q", "-b", HEAD)
    (repo / "marker.txt").write_text("the marker\n")
    git(repo, "add", "marker.txt")
    git(repo, "commit", "-q", "-m", "add the marker")
    git(repo, "checkout", "-q", "main")
    installation = make_installation(
        tmp_path / "planning", repos={"app": {"path": str(repo), "forge": "local"}}
    )
    config = installation.root / "abk.yaml"
    config.write_text(dump(installation.config))
    forge = LocalForge(installation.state_dir)
    number = forge.create_pr(
        forge.identity(installation.repo("app")),
        head=HEAD,
        base="main",
        title="Register the marker",
        body="Adds the marker file.",
    )
    return Opened(repo, installation.state_dir, config, number)


def test_view_prints_the_pull_request(opened: Opened, capsys: pytest.CaptureFixture[str]) -> None:
    code = opened.run("pr", "view", "--repo", "app", str(opened.number))

    shown = capsys.readouterr().out
    assert code == 0
    forge = LocalForge()
    assert ("abk", "pr", "view") in forge.read_commands
    assert ("abk", "pr", "diff") in forge.read_commands
    assert not set(forge.read_commands) & set(forge.denied_commands)
    for part in ("Register the marker", "Adds the marker file.", HEAD, "main", "open"):
        assert part in shown


def test_diff_prints_what_the_branch_adds_to_its_base(
    opened: Opened, capsys: pytest.CaptureFixture[str]
) -> None:
    code = opened.run("pr", "diff", "--repo", "app", str(opened.number))

    shown = capsys.readouterr().out
    assert code == 0
    assert "marker.txt" in shown
    assert "+the marker" in shown
    assert "base.txt" not in shown


def test_the_pull_request_of_the_checked_out_branch_is_the_default(
    opened: Opened, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    git(opened.repo, "checkout", "-q", HEAD)
    monkeypatch.chdir(opened.repo)

    assert opened.run("pr", "view", "--repo", "app") == 0

    assert "Register the marker" in capsys.readouterr().out


def test_view_prints_the_state_git_shows(
    opened: Opened, capsys: pytest.CaptureFixture[str]
) -> None:
    git(opened.repo, "merge", "-q", "--ff-only", HEAD)

    assert opened.run("pr", "view", "--repo", "app", str(opened.number)) == 0

    assert "state: merged" in capsys.readouterr().out


def test_the_default_repo_is_found_from_a_worktree_outside_the_checkout(
    opened: Opened,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    tree = tmp_path / "tree"
    git(opened.repo, "worktree", "add", "-q", str(tree), HEAD)
    monkeypatch.chdir(tree)

    assert opened.run("pr", "view") == 0

    assert "Register the marker" in capsys.readouterr().out


def test_neither_command_changes_anything(opened: Opened) -> None:
    before = opened.snapshot()

    assert opened.run("pr", "view", "--repo", "app", str(opened.number)) == 0
    assert opened.run("pr", "diff", "--repo", "app", str(opened.number)) == 0

    assert opened.snapshot() == before


def test_a_pull_request_that_does_not_exist_is_an_error(opened: Opened) -> None:
    assert opened.run("pr", "view", "--repo", "app", "99") != 0
