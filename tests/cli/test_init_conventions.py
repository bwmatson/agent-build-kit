"""`abk init` puts the changelog conventions into each code repo, shows them in the dry run,
and leaves them uncommitted."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.cli import init as init_cmd
from agent_build_kit.cli import main
from agent_build_kit.config import RepoConfig, WorkspaceConfig, dump
from tests.cli.test_init import fake_claude, fake_openspec
from tests.factories import git, init_repo, recognised_planning


@pytest.fixture(autouse=True)
def stubs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(init_cmd, "run_openspec", fake_openspec)
    monkeypatch.setattr(init_cmd, "run_claude", fake_claude)
    monkeypatch.setattr(init_cmd, "ask", lambda prompt: pytest.fail("prompted unexpectedly"))
    monkeypatch.setattr(
        init_cmd, "run_fix", lambda argv, **kwargs: pytest.fail(f"ran a fix unasked: {argv}")
    )
    monkeypatch.setenv("GIT_AUTHOR_NAME", "t")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "t@t.t")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "t")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "t@t.t")


def make_repo(tmp_path: Path, name: str, **files: str) -> Path:
    repo = init_repo(tmp_path / name)
    git(repo, "remote", "add", "origin", f"git@github.com:example/{name}.git")
    (repo / "pyproject.toml").write_text(f'[project]\nname = "{name}"\n')
    for file, content in files.items():
        (repo / file).write_text(content)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "first")
    return repo


def init(planning: Path, *repos: Path, extra: tuple[str, ...] = ()) -> int:
    argv = ["init", str(planning), "--yes", "--skip-research", "--skip-propose", *extra]
    for repo in repos:
        argv += ["--repo", str(repo)]
    return main(argv)


def tree(repo: Path) -> dict[str, bytes]:
    return {
        str(p.relative_to(repo)): p.read_bytes()
        for p in sorted(repo.rglob("*"))
        if p.is_file() and ".git" not in p.relative_to(repo).parts
    }


def test_init_writes_each_repos_conventions_and_leaves_them_uncommitted(tmp_path: Path) -> None:
    app = make_repo(tmp_path, "app", **{"AGENTS.md": "# App\n"})
    platform = make_repo(tmp_path, "platform")
    heads = {repo: git(repo, "rev-parse", "HEAD") for repo in (app, platform)}

    assert init(tmp_path / "planning", app, platform) == 0

    assert "<!-- abk:changelog" in (app / "AGENTS.md").read_text()
    assert (app / "AGENTS.md").read_text().startswith("# App\n")
    assert (app / "CHANGELOG.md").is_file()
    assert (app / ".gitattributes").read_text() == "CHANGELOG.md merge=union\n"
    assert "<!-- abk:changelog" in (platform / "AGENTS.md").read_text()
    assert not (platform / "CLAUDE.md").exists()
    for repo, head in heads.items():
        assert git(repo, "rev-parse", "HEAD") == head
        assert git(repo, "status", "--porcelain")


def test_a_second_init_changes_nothing_in_the_repos(tmp_path: Path) -> None:
    app = make_repo(tmp_path, "app")
    planning = recognised_planning(tmp_path / "planning")
    assert init(planning, app) == 0
    before = tree(app)
    assert {"AGENTS.md", "CHANGELOG.md", ".gitattributes"} <= set(before)

    assert init(planning, app) == 0

    assert tree(app) == before


def test_a_repo_whose_abk_yaml_entry_turns_the_changelog_off_is_left_alone(
    tmp_path: Path,
) -> None:
    app = make_repo(tmp_path, "app")
    platform = make_repo(tmp_path, "platform")
    planning = recognised_planning(tmp_path / "planning")
    config = WorkspaceConfig(
        repos={
            "app": RepoConfig(path=app, slug="example/app", changelog=None),
            "platform": RepoConfig(path=platform, slug="example/platform"),
        }
    )
    (planning / "abk.yaml").write_text(dump(config))
    before = tree(app)

    assert init(planning, app, platform) == 0

    assert tree(app) == before
    assert (platform / "CHANGELOG.md").is_file()


def test_dry_run_prints_a_line_per_repo_and_action_and_writes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    app = make_repo(tmp_path, "app", **{"AGENTS.md": "# App\n"})
    before = tree(app)

    assert init(tmp_path / "planning", app, extra=("--dry-run",)) == 0

    lines = capsys.readouterr().out.splitlines()
    (block,) = [line for line in lines if "app/AGENTS.md" in line]
    (changelog,) = [line for line in lines if "app/CHANGELOG.md" in line]
    (rule,) = [line for line in lines if "app/.gitattributes" in line]
    assert "write convention block" in block
    assert "create" in changelog
    assert "add union merge rule" in rule
    assert tree(app) == before
    assert not git(app, "status", "--porcelain")


def test_dry_run_after_init_says_each_action_is_already_current(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    app = make_repo(tmp_path, "app")
    planning = recognised_planning(tmp_path / "planning")
    assert init(planning, app) == 0
    capsys.readouterr()

    assert init(planning, app, extra=("--dry-run",)) == 0

    lines = capsys.readouterr().out.splitlines()
    for file in ("AGENTS.md", "CHANGELOG.md", ".gitattributes"):
        (line,) = [line for line in lines if f"app/{file}" in line]
        assert "already current" in line
