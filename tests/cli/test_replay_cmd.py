"""`abk replay review`: each cassette waiting, with how its request differs, and the decision."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from agent_build_kit.cli import main
from agent_build_kit.config import WorkspaceConfig, dump
from agent_build_kit.replay.models import Cassette
from agent_build_kit.replay.state import read_state
from agent_build_kit.replay.store import cassette_name, cassette_path, load_cassette
from tests.cli.replay_driver import replay_repo, store
from tests.factories import init_repo
from tests.replay.support import waiting_cassette

TEST = "tests/test_a.py::test_one"


class Workspace:
    def __init__(self, tmp_path: Path) -> None:
        planning = init_repo(tmp_path / "planning")
        repo, self.directory = replay_repo(tmp_path / "app")
        self.config = planning / "abk.yaml"
        self.config.write_text(dump(WorkspaceConfig(repos={"app": repo})))
        self.old = waiting_cassette(
            TEST, 0, path="/v1/old", reason="superseded by a live call at index 0"
        )
        self.new = waiting_cassette(TEST, 0, path="/v1/new", needs_review=False)
        self.lonely = waiting_cassette(TEST, 3, path="/v1/lonely", reason="no run asked for it")
        store(self.directory, self.old, self.new, self.lonely, unreviewed_runs=2)

    def run(self, capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str]:
        code = main(["--config", str(self.config), "replay", "review", *argv])
        captured = capsys.readouterr()
        return code, captured.out + captured.err

    def file(self, cassette: Cassette) -> str:
        return cassette_path(self.directory, cassette).name

    def named(self, output: str, cassette: Cassette) -> str:
        """The path the listing prints for `cassette`, to hand back to a decision flag."""
        return re.findall(rf"\S*{re.escape(self.file(cassette))}", output)[0]


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    return Workspace(tmp_path)


def test_each_waiting_cassette_is_listed_with_its_reason_and_the_difference_in_requests(
    workspace: Workspace, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out = workspace.run(capsys)

    assert code == 0
    assert workspace.file(workspace.old) in out
    assert workspace.file(workspace.lonely) in out
    assert workspace.file(workspace.new) not in out
    assert "superseded by a live call at index 0" in out
    assert "no run asked for it" in out
    # The summaries of the waiting cassette and of what superseded it, where they differ.
    assert "/v1/old" in out
    assert "/v1/new" in out
    assert "path differs" in out


def test_keep_clears_the_mark_and_leaves_the_file(
    workspace: Workspace, capsys: pytest.CaptureFixture[str]
) -> None:
    _, listing = workspace.run(capsys)
    name = workspace.named(listing, workspace.old)

    code, _ = workspace.run(capsys, "--keep", name)

    path = cassette_path(workspace.directory, workspace.old)
    assert code == 0
    assert not load_cassette(path).needs_review
    assert load_cassette(path).review_reason == ""
    _, after = workspace.run(capsys)
    assert path.name not in after
    assert workspace.file(workspace.lonely) in after


def test_delete_removes_the_file(workspace: Workspace, capsys: pytest.CaptureFixture[str]) -> None:
    _, listing = workspace.run(capsys)
    name = workspace.named(listing, workspace.lonely)

    code, _ = workspace.run(capsys, "--delete", name)

    assert code == 0
    assert not cassette_path(workspace.directory, workspace.lonely).exists()
    assert cassette_path(workspace.directory, workspace.old).exists()
    _, after = workspace.run(capsys)
    assert workspace.file(workspace.lonely) not in after
    assert cassette_name(workspace.directory, workspace.lonely) not in (
        read_state(workspace.directory).unreviewed_runs
    )
