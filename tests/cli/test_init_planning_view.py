"""`abk init . --repo .`: the `.planning` link to the state directory, and the guard against a
state directory inside the repository."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.cli import init as init_cmd
from agent_build_kit.cli import main
from agent_build_kit.config import dump
from tests.cli.init_quiet import app_repo, quiet
from tests.cli.test_init_in_repo import FLAGS
from tests.planning_worktree_support import installation_at


def configured(repo: Path, state: Path) -> None:
    """An `abk.yaml` at the repository root, which init keeps, whose state directory is `state`."""
    config = installation_at(repo, repo, planning={"state_dir": str(state)}).config
    (repo / "abk.yaml").write_text(dump(config))


def run_init(repo: Path, monkeypatch: pytest.MonkeyPatch, *extra: str) -> int:
    quiet(monkeypatch)
    monkeypatch.chdir(repo)
    return main(["init", ".", "--repo", ".", *FLAGS, *extra])


def test_an_in_repo_init_prints_the_links_line_and_leaves_the_link(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = app_repo(tmp_path)
    state = tmp_path / "state-home" / "state"
    configured(repo, state)

    assert run_init(repo, monkeypatch) == 0

    assert (repo / ".planning").is_symlink()
    assert (repo / ".planning").resolve() == state.resolve()
    assert any(".planning" in line for line in capsys.readouterr().out.splitlines())


def test_a_separate_planning_repo_gets_no_link_where_an_in_repo_one_does(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    quiet(monkeypatch)
    for name in ("NAME", "EMAIL"):
        monkeypatch.setenv(f"GIT_AUTHOR_{name}", "t")
        monkeypatch.setenv(f"GIT_COMMITTER_{name}", "t")
    app = app_repo(tmp_path)
    planning = tmp_path / "planning"
    inside = app_repo(tmp_path / "other")
    configured(inside, tmp_path / "state-home" / "state")

    assert main(["init", str(planning), "--repo", str(app), *FLAGS]) == 0
    assert run_init(inside, monkeypatch) == 0

    assert (inside / ".planning").is_symlink()
    assert not (planning / ".planning").is_symlink()
    assert not (app / ".planning").is_symlink()


def test_a_state_directory_inside_the_repository_is_refused_under_yes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = app_repo(tmp_path)
    state = repo / "data" / "state"
    configured(repo, state)
    written = sorted(path.name for path in repo.iterdir())

    assert run_init(repo, monkeypatch) == 1

    assert "--allow-state-in-repo" in capsys.readouterr().err
    assert sorted(path.name for path in repo.iterdir()) == written
    assert not state.exists()
    assert not (repo / ".planning").is_symlink()


def test_the_allow_flag_warns_and_proceeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = app_repo(tmp_path)
    configured(repo, repo / "data" / "state")

    assert run_init(repo, monkeypatch, "--allow-state-in-repo") == 0

    captured = capsys.readouterr()
    assert "fast-forward" in captured.out + captured.err
    assert (repo / ".planning").is_symlink()


def test_a_state_directory_outside_the_repository_is_not_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = app_repo(tmp_path)
    configured(repo, tmp_path / "outside" / "state")

    assert run_init(repo, monkeypatch) == 0

    captured = capsys.readouterr()
    assert "--allow-state-in-repo" not in captured.out + captured.err
    assert (repo / ".planning").is_symlink()


def test_interactively_the_same_case_asks_and_no_exits_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = app_repo(tmp_path)
    state = repo / "data" / "state"
    configured(repo, state)
    questions: list[str] = []

    def decline(prompt: str) -> str:
        questions.append(prompt)
        return "n"

    quiet(monkeypatch)
    monkeypatch.setattr(init_cmd, "ask", decline)
    monkeypatch.chdir(repo)

    status = main(["init", ".", "--repo", ".", "--skip-research", "--skip-propose"])

    assert status == 1
    assert questions
    assert not state.exists()
    assert not (repo / ".planning").is_symlink()


def test_a_real_planning_directory_exits_1_naming_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = app_repo(tmp_path)
    state = tmp_path / "state-home" / "state"
    configured(repo, state)
    (repo / ".planning").mkdir()
    (repo / ".planning" / "notes.md").write_text("mine\n")

    assert run_init(repo, monkeypatch) == 1

    assert ".planning" in capsys.readouterr().err
    assert (repo / ".planning" / "notes.md").read_text() == "mine\n"
    assert not state.exists()


def test_a_first_init_with_no_abk_yaml_links_the_state_the_installation_would_use(
    tmp_path: Path, data: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = app_repo(tmp_path)
    assert not (repo / "abk.yaml").exists()

    assert run_init(repo, monkeypatch) == 0

    state = installation_at(repo, repo).state_dir
    assert state.is_relative_to(data)
    assert (repo / ".planning").is_symlink()
    assert (repo / ".planning").resolve() == state.resolve()
    exclude = repo / ".git" / "info" / "exclude"
    assert "/.planning" in exclude.read_text().splitlines()


def test_a_kept_abk_yaml_without_a_state_setting_links_the_default_state(
    tmp_path: Path, data: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = app_repo(tmp_path)
    (repo / "abk.yaml").write_text(dump(installation_at(repo, repo).config))

    assert run_init(repo, monkeypatch) == 0

    assert (repo / ".planning").resolve() == installation_at(repo, repo).state_dir.resolve()


def test_a_dry_run_says_what_it_would_do_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = app_repo(tmp_path)
    state = repo / "data" / "state"
    configured(repo, state)
    written = sorted(path.name for path in repo.iterdir())

    assert run_init(repo, monkeypatch, "--dry-run") == 0

    out = capsys.readouterr().out
    assert "planning view: .planning would create" in out
    assert "inside the repository" in out
    assert sorted(path.name for path in repo.iterdir()) == written
    assert not state.exists()
