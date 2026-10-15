"""`abk init . --repo .`: the repository is its own planning repo."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from agent_build_kit import skills
from agent_build_kit.cli import main
from tests.cli.init_quiet import app_repo, quiet
from tests.factories import git
from tests.init.test_code_repo_conventions import snapshot

FLAGS = ["--yes", "--skip-research", "--skip-propose"]


def head(repo: Path) -> str:
    return git(repo, "rev-parse", "HEAD").strip()


def run_init(repo: Path, monkeypatch: pytest.MonkeyPatch) -> int:
    quiet(monkeypatch)
    monkeypatch.chdir(repo)
    return main(["init", ".", "--repo", ".", *FLAGS])


def test_the_repo_is_written_at_dot_and_the_store_is_left_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = app_repo(tmp_path)
    (repo / "runs").mkdir()
    store = b'{"units": [{"id": "feature/1"}]}'
    (repo / "runs" / "units.json").write_bytes(store)

    assert run_init(repo, monkeypatch) == 0

    config = yaml.safe_load((repo / "abk.yaml").read_text())
    assert [entry["path"] for entry in config["repos"].values()] == ["."]
    assert (repo / "runs" / "units.json").read_bytes() == store


def test_a_clean_tree_is_not_committed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = app_repo(tmp_path)
    before = head(repo)

    assert run_init(repo, monkeypatch) == 0

    assert head(repo) == before
    assert "committed: abk init" not in capsys.readouterr().out
    assert (repo / "abk.yaml").is_file()


def test_a_dirty_tree_is_not_committed_and_its_edits_stay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = app_repo(tmp_path)
    (repo / "src" / "app.py").write_text("x = 2\n")
    (repo / "scratch.txt").write_text("loose\n")
    before, diff = head(repo), git(repo, "diff", "--", "src/app.py")

    assert run_init(repo, monkeypatch) == 0

    assert head(repo) == before
    assert (repo / "src" / "app.py").read_text() == "x = 2\n"
    assert git(repo, "diff", "--", "src/app.py") == diff
    assert "?? scratch.txt" in git(repo, "status", "--porcelain").splitlines()


def test_a_planning_directory_inside_the_repo_is_in_repo_too(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    quiet(monkeypatch)
    repo = app_repo(tmp_path)
    monkeypatch.chdir(repo)
    before = head(repo)

    assert main(["init", "sub", "--repo", ".", *FLAGS]) == 0

    assert not (repo / "sub" / ".git").exists()
    assert head(repo) == before
    config = yaml.safe_load((repo / "sub" / "abk.yaml").read_text())
    assert [entry["path"] for entry in config["repos"].values()] == [".."]
    assert "runs/unit-logs/" in (repo / "sub" / ".gitignore").read_text()
    assert "sub/abk.yaml" in (repo / "AGENTS.md").read_text()


def test_what_was_written_is_listed_and_each_skill_is_installed_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = app_repo(tmp_path)

    assert run_init(repo, monkeypatch) == 0

    lines = capsys.readouterr().out.splitlines()
    assert "wrote abk.yaml" in lines
    assert "wrote .gitignore" in lines
    assert "wrote AGENTS.md" in lines
    for name in skills.names():
        assert lines.count(f"wrote .claude/skills/{name}/SKILL.md") == 1


def test_a_second_run_writes_nothing_and_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = app_repo(tmp_path)
    assert run_init(repo, monkeypatch) == 0
    before = snapshot(repo)
    capsys.readouterr()

    assert run_init(repo, monkeypatch) == 0

    out = capsys.readouterr().out
    assert not [line for line in out.splitlines() if line.startswith("wrote ")]
    assert "nothing written" in out
    assert snapshot(repo) == before
