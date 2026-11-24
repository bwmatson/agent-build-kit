"""`abk doctor`'s `public content` check on the files that must never be
committed: the local scrub list and the `*.pre-redact` copies."""

from __future__ import annotations

from pathlib import Path

from tests.cli.public_content_repo import planning, public_content, said
from tests.factories import git

LIST = "scrub.local"
COPY = "runs/units.json.pre-redact"
IGNORED = "scrub.local\n*.pre-redact\n"


def put(root: Path, *names: str) -> None:
    for name in names:
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text("x\n")


def linked(config: Path, tmp_path: Path) -> Path:
    git(config.parent, "worktree", "add", "-q", str(tmp_path / "linked"), "-b", "side")
    return tmp_path / "linked" / "abk.yaml"


def test_a_local_list_without_an_ignore_line_warns_naming_the_line_to_add(
    tmp_path: Path,
) -> None:
    config = planning(tmp_path / "plan", ignore="*.pre-redact\n")
    put(config.parent, LIST)

    found = public_content(config)

    assert [c.status for c in found] == ["warn"]
    assert LIST in found[0].fix


def test_a_tracked_local_list_warns_that_it_is_tracked(tmp_path: Path) -> None:
    config = planning(tmp_path / "plan", ignore=IGNORED)
    put(config.parent, LIST)
    git(config.parent, "add", "-f", LIST)
    git(config.parent, "commit", "-qm", "the list")

    found = public_content(config)

    assert [c.status for c in found] == ["warn"]
    assert "tracked" in said(found[0])
    assert LIST in said(found[0])


def test_an_unignored_redaction_copy_warns_naming_it(tmp_path: Path) -> None:
    config = planning(tmp_path / "plan", ignore="scrub.local\n")
    put(config.parent, COPY)

    found = public_content(config)

    assert [c.status for c in found] == ["warn"]
    assert "units.json.pre-redact" in said(found[0])


def test_the_list_and_the_copy_both_ignored_give_ok(tmp_path: Path) -> None:
    config = planning(tmp_path / "plan", ignore=IGNORED)
    put(config.parent, LIST, COPY)

    assert [c.status for c in public_content(config)] == ["ok"]


def test_a_linked_worktree_gives_the_results_of_its_main_checkout(tmp_path: Path) -> None:
    config = planning(tmp_path / "plan", ignore="scrub.local\n")
    worktree = linked(config, tmp_path)
    for checkout in (config.parent, worktree.parent):
        put(checkout, LIST, COPY)

    main = public_content(config)
    side = public_content(worktree)

    assert [c.status for c in main] == ["warn"]
    assert [(c.status, c.detail, c.fix) for c in side] == [
        (c.status, c.detail, c.fix) for c in main
    ]


def test_a_linked_worktree_with_everything_ignored_is_ok(tmp_path: Path) -> None:
    config = planning(tmp_path / "plan", ignore=IGNORED)
    worktree = linked(config, tmp_path)
    for checkout in (config.parent, worktree.parent):
        put(checkout, LIST, COPY)

    assert [c.status for c in public_content(worktree)] == ["ok"]
    assert [c.status for c in public_content(config)] == ["ok"]


def test_a_state_directory_outside_the_repository_holds_nothing_to_commit(
    tmp_path: Path,
) -> None:
    # Relative to the planning root, not `str(tmp_path / ...)`: the doctor reads a committed value
    # that starts `/home/<name>` as a home-directory path, and a temp root under the home
    # directory (the kit's own, for a pipeline run) would make this value one.
    elsewhere = tmp_path / "elsewhere"
    config = planning(tmp_path / "plan", ignore="scrub.local\n", state_dir="../elsewhere")
    put(elsewhere, "units.json.pre-redact")

    assert [c.status for c in public_content(config)] == ["ok"]


def test_a_tracked_redaction_copy_says_to_untrack_it(tmp_path: Path) -> None:
    config = planning(tmp_path / "plan", ignore=IGNORED)
    put(config.parent, COPY)
    git(config.parent, "add", "-f", COPY)
    git(config.parent, "commit", "-qm", "the copy")

    found = public_content(config)

    assert [c.status for c in found] == ["warn"]
    assert "git rm --cached" in found[0].fix
    assert "units.json.pre-redact" in said(found[0])
