"""`carry` links the machine files from the working copy into the pipeline worktree, and refuses
what it must not touch."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.machine_files import MachineFileRefused, carry
from tests.factories import git
from tests.machine_files_support import CONTENT, GITIGNORE, give, machine_repo, results

ALL = (".env", "abk.local.yaml", "scrub.local")


def test_the_files_are_linked_as_absolute_links_and_the_worktree_stays_clean(
    tmp_path: Path,
) -> None:
    setup = machine_repo(tmp_path)
    give(setup.working_copy, *ALL)

    carried = carry(setup.working_copy, setup.worktree, dry_run=False)

    assert results(carried) == dict.fromkeys(ALL, "linked")
    for name in ALL:
        link = setup.worktree / name
        assert link.is_symlink()
        assert Path(link.readlink()) == setup.working_copy / name
        assert link.read_text() == CONTENT[name]
    assert git(setup.worktree, "status", "--porcelain") == ""


def test_a_file_the_working_copy_lacks_is_skipped_and_not_reported(tmp_path: Path) -> None:
    setup = machine_repo(tmp_path)
    give(setup.working_copy, ".env")

    carried = carry(setup.working_copy, setup.worktree, dry_run=False)

    assert results(carried) == {".env": "linked"}
    assert not (setup.worktree / "abk.local.yaml").is_symlink()
    assert not (setup.worktree / "scrub.local").exists()


def test_a_second_carry_reports_every_file_unchanged(tmp_path: Path) -> None:
    setup = machine_repo(tmp_path)
    give(setup.working_copy, *ALL)
    carry(setup.working_copy, setup.worktree, dry_run=False)

    again = carry(setup.working_copy, setup.worktree, dry_run=False)

    assert results(again) == dict.fromkeys(ALL, "unchanged")


def test_a_dangling_link_is_repointed_and_reported(tmp_path: Path) -> None:
    setup = machine_repo(tmp_path)
    give(setup.working_copy, ".env")
    (setup.worktree / ".env").symlink_to(tmp_path / "moved" / ".env")

    carried = carry(setup.working_copy, setup.worktree, dry_run=False)

    assert results(carried) == {".env": "repointed"}
    assert (setup.worktree / ".env").resolve() == (setup.working_copy / ".env").resolve()


def test_a_dry_run_says_would_link_and_writes_nothing(tmp_path: Path) -> None:
    setup = machine_repo(tmp_path)
    give(setup.working_copy, *ALL)

    carried = carry(setup.working_copy, setup.worktree, dry_run=True)

    assert results(carried) == dict.fromkeys(ALL, "would link")
    assert not any((setup.worktree / name).is_symlink() for name in ALL)
    assert not any((setup.worktree / name).exists() for name in ALL)


def test_a_regular_file_with_different_bytes_is_refused_by_name_and_left_alone(
    tmp_path: Path,
) -> None:
    setup = machine_repo(tmp_path)
    give(setup.working_copy, "abk.local.yaml")
    mine = setup.worktree / "abk.local.yaml"
    mine.write_text("planning: {self_pull: false}\n")

    with pytest.raises(MachineFileRefused, match="abk.local.yaml"):
        carry(setup.working_copy, setup.worktree, dry_run=False)

    assert not mine.is_symlink()
    assert mine.read_text() == "planning: {self_pull: false}\n"


def test_a_link_to_another_existing_file_is_refused_by_name_and_left_alone(
    tmp_path: Path,
) -> None:
    setup = machine_repo(tmp_path)
    give(setup.working_copy, ".env")
    other = tmp_path / "other.env"
    other.write_text("TOKEN=other\n")
    (setup.worktree / ".env").symlink_to(other)

    with pytest.raises(MachineFileRefused, match=r"\.env"):
        carry(setup.working_copy, setup.worktree, dry_run=False)

    assert (setup.worktree / ".env").readlink() == other


def test_a_worktree_whose_gitignore_lacks_the_name_is_refused_by_name(tmp_path: Path) -> None:
    lines = [line for line in GITIGNORE.splitlines() if line != "scrub.local"]
    setup = machine_repo(tmp_path, ignore="\n".join(lines) + "\n")
    give(setup.working_copy, "scrub.local")

    with pytest.raises(MachineFileRefused, match="scrub.local"):
        carry(setup.working_copy, setup.worktree, dry_run=False)

    assert not (setup.worktree / "scrub.local").exists()


def test_a_tracked_file_of_that_name_is_refused_by_name(tmp_path: Path) -> None:
    setup = machine_repo(tmp_path)
    give(setup.working_copy, ".env")
    git(setup.working_copy, "add", "-f", ".env")
    git(setup.working_copy, "commit", "-qm", "track the env file")
    worktree = tmp_path / "second"
    git(setup.working_copy, "worktree", "add", "-q", "--detach", str(worktree), "HEAD")

    with pytest.raises(MachineFileRefused, match=r"\.env"):
        carry(setup.working_copy, worktree, dry_run=False)

    assert not (worktree / ".env").is_symlink()


def test_a_refusal_found_second_leaves_the_first_file_unlinked(tmp_path: Path) -> None:
    setup = machine_repo(tmp_path)
    give(setup.working_copy, ".env", "abk.local.yaml")
    (setup.worktree / "abk.local.yaml").write_text("different: true\n")

    with pytest.raises(MachineFileRefused, match="abk.local.yaml"):
        carry(setup.working_copy, setup.worktree, dry_run=False)

    assert not (setup.worktree / ".env").exists()
    assert not (setup.worktree / ".env").is_symlink()


def test_a_regular_file_with_the_same_bytes_is_unchanged(tmp_path: Path) -> None:
    setup = machine_repo(tmp_path)
    give(setup.working_copy, ".env")
    copy = setup.worktree / ".env"
    copy.write_text(CONTENT[".env"])

    carried = carry(setup.working_copy, setup.worktree, dry_run=False)

    assert results(carried) == {".env": "unchanged"}
    assert not copy.is_symlink()
    assert copy.read_text() == CONTENT[".env"]
