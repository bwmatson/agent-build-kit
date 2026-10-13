"""Whether a clean move is checked by what it can affect or in full (spec:
a-moved-base-is-checked-by-what-it-can-affect).

The repository is real: a unit's branch cut from a base, the base moved on, and the
branch replayed on top of it, as the restack leaves it. The old base is the one the
restack computed.
"""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.config import RestackCheck
from agent_build_kit.pipeline.moved_base import MoveScope, moved_base_scope, scope_of
from tests.factories import git
from tests.moved_base_fakes import commit, moved


def scope(
    repo: Path, old_base: str, setting: RestackCheck = RestackCheck.AFFECTED, base: str = "main"
) -> MoveScope:
    own = git(repo, "diff", "--name-only", f"{base}...HEAD").split()
    return moved_base_scope(repo, own=own, base=base, moved_from=old_base, setting=setting)


def test_a_move_over_files_the_unit_does_not_change_is_scoped(tmp_path: Path) -> None:
    repo, old_base = moved(tmp_path, own={"a.py": "a = 2\n"}, incoming={"b.py": "b = 2\n"})

    assert scope(repo, old_base).scoped


def test_a_file_the_move_brought_in_that_the_unit_also_changes_is_full_and_named(
    tmp_path: Path,
) -> None:
    repo, old_base = moved(
        tmp_path,
        own={"a.py": "a = 1\nx = 2\n"},
        incoming={"a.py": "w = 0\na = 1\n", "b.py": "b = 2\n"},
    )

    result = scope(repo, old_base)

    assert not result.scoped
    assert "a.py" in result.reason
    assert "b.py" not in result.reason


def test_a_unit_that_produced_nothing_is_full(tmp_path: Path) -> None:
    repo, old_base = moved(tmp_path, own={}, incoming={"b.py": "b = 2\n"})

    result = scope(repo, old_base)

    assert not result.scoped
    assert "nothing" in result.reason


def test_the_full_setting_is_full_whatever_the_files(tmp_path: Path) -> None:
    repo, old_base = moved(tmp_path, own={"a.py": "a = 2\n"}, incoming={"b.py": "b = 2\n"})

    result = scope(repo, old_base, RestackCheck.FULL)

    assert not result.scoped
    assert "restack_check" in result.reason


def test_a_move_with_no_old_base_is_full(tmp_path: Path) -> None:
    repo, _ = moved(tmp_path, own={"a.py": "a = 2\n"}, incoming={"b.py": "b = 2\n"})

    result = scope(repo, "")

    assert not result.scoped
    assert "old base" in result.reason


def test_the_incoming_files_are_those_between_the_old_base_and_the_base(tmp_path: Path) -> None:
    repo, old_base = moved(tmp_path, own={"a.py": "a = 2\n"}, incoming={"b.py": "b = 2\n"})
    earlier = git(repo, "rev-parse", "main").strip()
    git(repo, "checkout", "-q", "main")
    commit(repo, {"a.py": "a = 9\n"}, "main moves again")
    git(repo, "checkout", "-q", "spec/feature/1")

    assert scope(repo, old_base, base=earlier).scoped
    assert not scope(repo, old_base, base="main").scoped


def test_the_rule_over_the_files_alone() -> None:
    assert scope_of(["a.py"], ["b.py"], RestackCheck.AFFECTED).scoped
    assert scope_of(["a.py"], [], RestackCheck.AFFECTED).scoped
    assert not scope_of(["a.py", "b.py"], ["b.py"], RestackCheck.AFFECTED).scoped
    assert not scope_of([], ["b.py"], RestackCheck.AFFECTED).scoped
    assert not scope_of(["a.py"], ["b.py"], RestackCheck.FULL).scoped


def test_a_base_that_cannot_be_listed_is_full_and_says_so(tmp_path: Path) -> None:
    repo, _ = moved(tmp_path, own={"a.py": "a = 2\n"}, incoming={"b.py": "b = 2\n"})

    result = scope(repo, "no-such-ref")

    assert not result.scoped
    assert "could not be listed" in result.reason
