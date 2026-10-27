"""`abk doctor`'s `change locks` check and its one repair, `abk doctor --fix`: stray `*.md.lock`
files under the changes directory (spec: change-locks)."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.cli.doctor import Check, run_doctor
from agent_build_kit.pipeline.file_lock import try_file_lock
from tests.cli.public_content_repo import planning, said
from tests.cli.test_doctor import Answers
from tests.factories import git, which_all

CHECK = "change locks"
IGNORED = "*.md.lock\n"


def lay(root: Path, change: str, *names: str) -> list[Path]:
    """Empty files `names` in the change's directory; their paths."""
    directory = root / "openspec" / "changes" / change
    directory.mkdir(parents=True, exist_ok=True)
    paths = [directory / name for name in names]
    for path in paths:
        path.write_text("")
    return paths


def checks(config: Path, *, fix: bool = False) -> list[Check]:
    found = run_doctor(config, run=Answers(), which=which_all, fix=fix)
    return [check for check in found if check.name == CHECK]


def test_untracked_locks_give_one_warning_naming_the_count_and_the_repair(tmp_path: Path) -> None:
    config = planning(tmp_path / "plan", ignore=IGNORED)
    lay(config.parent, "feature", "tasks.md.lock", "follow-ups.md.lock")

    found = checks(config)

    assert [c.status for c in found] == ["warn"]
    assert "2" in said(found[0])
    assert "abk doctor --fix" in said(found[0])


def test_fix_deletes_both_and_a_rerun_is_quiet(tmp_path: Path) -> None:
    config = planning(tmp_path / "plan", ignore=IGNORED)
    locks = lay(config.parent, "feature", "tasks.md.lock", "follow-ups.md.lock")

    checks(config, fix=True)

    assert not any(path.exists() for path in locks)
    assert checks(config) == []


def test_a_lock_a_holder_has_is_kept_and_reported_as_in_use(tmp_path: Path) -> None:
    config = planning(tmp_path / "plan", ignore=IGNORED)
    held, free = lay(config.parent, "feature", "tasks.md.lock", "follow-ups.md.lock")

    with try_file_lock(held) as taken:
        assert taken
        found = checks(config, fix=True)

    assert held.exists()
    assert not free.exists()
    assert "in use" in " ".join(said(c) for c in found)


def test_a_tracked_lock_is_kept_and_named_with_the_git_rm_step(tmp_path: Path) -> None:
    config = planning(tmp_path / "plan", ignore=IGNORED)
    (tracked,) = lay(config.parent, "feature", "tasks.md.lock")
    git(config.parent, "add", "-f", str(tracked))
    git(config.parent, "commit", "-qm", "a lock got in")

    found = checks(config, fix=True)

    assert tracked.exists()
    assert "git rm" in " ".join(said(c) for c in found)
    assert str(tracked.relative_to(config.parent)) in " ".join(said(c) for c in found)


def test_fix_changes_nothing_else(tmp_path: Path) -> None:
    config = planning(tmp_path / "plan", ignore=IGNORED)
    tasks, _, other = lay(config.parent, "feature", "tasks.md", "tasks.md.lock", "notes.md")
    tasks.write_text("- [ ] 1.1 Test: it\n")
    other.write_text("keep\n")
    before = git(config.parent, "status", "--porcelain", "--ignored")

    checks(config, fix=True)

    assert tasks.read_text() == "- [ ] 1.1 Test: it\n"
    assert other.read_text() == "keep\n"
    after = git(config.parent, "status", "--porcelain", "--ignored")
    assert [line for line in before.splitlines() if line not in after.splitlines()] == [
        "!! openspec/changes/feature/tasks.md.lock"
    ]
    assert [line for line in after.splitlines() if line not in before.splitlines()] == []


def test_with_none_there_is_no_check_line_and_fix_changes_nothing(tmp_path: Path) -> None:
    config = planning(tmp_path / "plan", ignore=IGNORED)
    (tasks,) = lay(config.parent, "feature", "tasks.md")

    assert checks(config) == []
    assert checks(config, fix=True) == []
    assert tasks.exists()
