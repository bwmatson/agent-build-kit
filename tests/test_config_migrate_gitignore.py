"""The migration makes sure git ignores the local files, refuses a tracked one and never commits
(spec: config-migration, "The migration makes sure git ignores the local files")."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from agent_build_kit.config_migrate import ConfigMigrateError
from agent_build_kit.config_migrate_write import uncommitted_hint, write_both
from agent_build_kit.pipeline.shell import git as run_git
from agent_build_kit.runtimes.policy_apply import BACKUP_SUFFIX
from tests.config_migrate_write_fakes import BASE_NEW, BASE_OLD, LOCAL_NEW, LOCAL_OLD, files
from tests.factories import git, init_repo

IGNORE = "__pycache__/\n"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repository holding a committed abk.yaml and a committed .gitignore."""
    init_repo(tmp_path)
    files(tmp_path, local=None)
    (tmp_path / ".gitignore").write_text(IGNORE)
    git(tmp_path, "add", "abk.yaml", ".gitignore")
    git(tmp_path, "commit", "-q", "-m", "start")
    return tmp_path


def test_missing_lines_are_appended_once_first_and_their_diff_is_shown(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    ignore = repo / ".gitignore"
    seen: list[str] = []
    real = shutil.copy2

    def spy(source: Path, target: Path, **kwargs: bool) -> object:
        seen.append(ignore.read_text())
        return real(source, target, **kwargs)

    monkeypatch.setattr(shutil, "copy2", spy)

    write_both(repo / "abk.yaml", BASE_NEW, LOCAL_NEW)

    lines = ignore.read_text().splitlines()
    assert lines.count("abk.local.yaml") == 1
    assert lines.count("scrub.local") == 1
    assert lines[0] == IGNORE.strip()
    assert seen and "abk.local.yaml" in seen[0] and "scrub.local" in seen[0]
    shown = capsys.readouterr().out
    assert "+abk.local.yaml" in shown
    assert "+scrub.local" in shown


def test_a_gitignore_that_already_ignores_both_is_not_touched(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ignore = repo / ".gitignore"
    ignore.write_text("abk.local.*\nscrub.*\n")

    write_both(repo / "abk.yaml", BASE_NEW, LOCAL_NEW)

    assert ignore.read_text() == "abk.local.*\nscrub.*\n"
    assert ".gitignore" not in capsys.readouterr().out


def test_a_missing_gitignore_is_created(repo: Path) -> None:
    (repo / ".gitignore").unlink()
    git(repo, "rm", "-q", "--cached", ".gitignore")

    write_both(repo / "abk.yaml", BASE_NEW, LOCAL_NEW)

    assert (repo / ".gitignore").read_text().splitlines() == ["abk.local.yaml", "scrub.local"]


def test_a_directory_that_is_not_a_repository_gets_no_gitignore(tmp_path: Path) -> None:
    base, _ = files(tmp_path, local=None)

    write_both(base, BASE_NEW, LOCAL_NEW)

    assert not (tmp_path / ".gitignore").exists()


def test_a_tracked_local_file_is_refused_and_nothing_is_written(repo: Path) -> None:
    (repo / "abk.local.yaml").write_text(LOCAL_OLD)
    git(repo, "add", "abk.local.yaml")
    git(repo, "commit", "-q", "-m", "local")

    with pytest.raises(ConfigMigrateError, match="git rm --cached abk.local.yaml"):
        write_both(repo / "abk.yaml", BASE_NEW, LOCAL_NEW)

    assert (repo / "abk.yaml").read_text() == BASE_OLD
    assert (repo / "abk.local.yaml").read_text() == LOCAL_OLD
    assert (repo / ".gitignore").read_text() == IGNORE
    assert not (repo / ("abk.yaml" + BACKUP_SUFFIX)).exists()


def test_a_failed_gitignore_write_stops_before_the_backups(repo: Path) -> None:
    (repo / ".gitignore").unlink()
    git(repo, "rm", "-q", "--cached", ".gitignore")
    (repo / ".gitignore").mkdir()

    with pytest.raises((ConfigMigrateError, OSError)):
        write_both(repo / "abk.yaml", BASE_NEW, LOCAL_NEW)

    assert (repo / "abk.yaml").read_text() == BASE_OLD
    assert not (repo / "abk.local.yaml").exists()
    assert not (repo / ("abk.yaml" + BACKUP_SUFFIX)).exists()


def test_a_write_neither_commits_nor_stages(repo: Path) -> None:
    head = git(repo, "rev-parse", "HEAD")

    write_both(repo / "abk.yaml", BASE_NEW, LOCAL_NEW)

    assert git(repo, "rev-parse", "HEAD") == head
    assert git(repo, "diff", "--cached", "--name-only") == ""
    status = run_git(repo, "status", "--porcelain").stdout.splitlines()
    assert " M abk.yaml" in status
    assert " M .gitignore" in status
    assert all(line[0] in " ?" for line in status)


def test_an_abk_yaml_with_an_uncommitted_change_gives_the_hint_before_and_after_the_write(
    repo: Path,
) -> None:
    assert uncommitted_hint(repo / "abk.yaml") is None
    (repo / "abk.yaml").write_text(BASE_OLD + "max_unit_lines: 9\n")

    before = uncommitted_hint(repo / "abk.yaml")
    write_both(repo / "abk.yaml", BASE_NEW, LOCAL_NEW)
    after = uncommitted_hint(repo / "abk.yaml")

    assert before is not None
    assert "abk.yaml has changes git has not committed" in before
    assert "does not commit" in before
    assert after == before


def test_a_directory_that_is_not_a_repository_gives_no_hint(tmp_path: Path) -> None:
    base, _ = files(tmp_path, local=None)

    assert uncommitted_hint(base) is None
