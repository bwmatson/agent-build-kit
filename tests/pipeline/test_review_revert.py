"""A revert is a trunk commit that names the unit's merge (spec: review-outcomes).

The repository is a temporary git one and the forge is the stand-in, which answers the
merge commit; nothing here talks to a host."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.forges.base import RepoId
from agent_build_kit.pipeline.review_outcome import with_outcome
from agent_build_kit.pipeline.review_revert import reverts_merge
from agent_build_kit.pipeline.units import UnitState
from tests.factories import commit, commit_files, git, init_repo, stored_unit
from tests.forges.stand_in import StandInForge

UID = "add-marker/1"
REPO = RepoId(forge="stand_in", account="example", name="app")
PR = 42


@pytest.fixture
def app(tmp_path: Path) -> Path:
    repo = init_repo(tmp_path / "app")
    commit(repo, "base.txt")
    return repo


def land(app: Path, name: str = "feature.txt") -> str:
    """The squash commit the unit's pull request produced."""
    return commit(app, name)


def say(app: Path, message: str) -> str:
    commit_files(app, message, {"later.txt": message})
    return git(app, "rev-parse", "HEAD")


def reverted(app: Path, merge: str) -> bool:
    return reverts_merge(app, trunk="main", merge_commit=merge, repo=REPO, pr=PR) is True


def test_git_revert_wording_with_the_full_sha_marks_the_unit_reverted(app: Path) -> None:
    merge = land(app)
    say(app, f"Revert feature\n\nThis reverts commit {merge}.")

    assert reverted(app, merge)


def test_a_host_revert_pull_request_naming_the_unit_marks_it_reverted(app: Path) -> None:
    merge = land(app)
    say(app, f"Revert feature\n\nReverts example/app#{PR}")

    assert reverted(app, merge)


@pytest.mark.parametrize(
    "line",
    [
        "This reverts commit {other}.",
        "Reverts example/app#43",
        "Reverts example/platform#42",
    ],
)
def test_a_commit_reverting_something_else_does_not_count(app: Path, line: str) -> None:
    merge = land(app)
    say(app, "Revert other\n\n" + line.format(other="d" * 40))

    assert not reverted(app, merge)


def test_a_commit_before_the_merge_naming_it_does_not_count(app: Path) -> None:
    say(app, f"Revert early\n\nThis reverts commit {'e' * 40}.\nReverts example/app#{PR}")
    merge = land(app)

    assert not reverted(app, merge)


def test_a_short_sha_does_not_count(app: Path) -> None:
    merge = land(app)
    say(app, f"Revert feature\n\nThis reverts commit {merge[:12]}.")

    assert not reverted(app, merge)


def test_a_commit_only_on_a_side_branch_does_not_count(app: Path) -> None:
    merge = land(app)
    git(app, "checkout", "-q", "-b", "side")
    say(app, f"Revert feature\n\nThis reverts commit {merge}.")
    git(app, "checkout", "-q", "main")

    assert not reverted(app, merge)


def test_a_forge_that_cannot_name_the_merge_leaves_the_history_and_says_unchecked(
    app: Path,
) -> None:
    say(app, f"Revert feature\n\nReverts example/app#{PR}")
    unit = stored_unit(
        UID,
        state=UnitState.MERGED,
        pr=PR,
        history=({"state": "merged", "at": "2026-10-01T10:00:00+00:00", "cause": "merged"},),
    )

    record = with_outcome(
        {UID: {"brief": True}}, unit, forge=StandInForge(), repo=REPO, checkout=app, trunk="main"
    )[UID]

    assert record["outcome"] == "clean"
    assert record["revert_checked"] is False


def test_a_reverted_merge_makes_the_outcome_reverted_and_the_revert_checked(app: Path) -> None:
    merge = land(app)
    say(app, f"Revert feature\n\nThis reverts commit {merge}.")
    forge = StandInForge()
    forge.merged[PR] = merge
    unit = stored_unit(
        UID,
        state=UnitState.MERGED,
        pr=PR,
        history=({"state": "merged", "at": "2026-10-01T10:00:00+00:00", "cause": "merged"},),
    )

    record = with_outcome(
        {UID: {"brief": True}}, unit, forge=forge, repo=REPO, checkout=app, trunk="main"
    )[UID]

    assert record["outcome"] == "reverted"
    assert record["revert_checked"] is True


def test_a_merge_commit_the_checkout_does_not_hold_is_unchecked_not_clear_of_reverts(
    app: Path,
) -> None:
    absent = "a" * 40
    forge = StandInForge()
    forge.merged[PR] = absent
    unit = stored_unit(
        UID,
        state=UnitState.MERGED,
        pr=PR,
        history=({"state": "merged", "at": "2026-10-01T10:00:00+00:00", "cause": "merged"},),
    )

    record = with_outcome(
        {UID: {"brief": True}}, unit, forge=forge, repo=REPO, checkout=app, trunk="main"
    )[UID]

    assert reverts_merge(app, trunk="main", merge_commit=absent, repo=REPO, pr=PR) is None
    assert record["outcome"] == "clean"
    assert record["revert_checked"] is False
