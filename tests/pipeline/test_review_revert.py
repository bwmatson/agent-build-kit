"""A revert is a trunk commit that names the unit's merge (spec: review-outcomes).

The repository is a temporary git one and the forge is the stand-in, which answers the
merge commit; nothing here talks to a host."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agent_build_kit.forges.base import RepoId
from agent_build_kit.pipeline.review_outcome import with_outcome
from agent_build_kit.pipeline.review_revert import reverts_merge, reverts_pull_request
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


MERGED_AT = datetime(2026, 9, 1, 12, tzinfo=UTC)


def commit_on(app: Path, monkeypatch: pytest.MonkeyPatch, when: datetime, message: str) -> str:
    """A commit whose author and committer dates are `when`."""
    monkeypatch.setenv("GIT_COMMITTER_DATE", when.isoformat())
    monkeypatch.setenv("GIT_AUTHOR_DATE", when.isoformat())
    commit_files(app, message, {f"{when.timestamp()}-{len(message)}.txt": message})
    return git(app, "rev-parse", "HEAD")


@pytest.fixture
def dated(app: Path, monkeypatch: pytest.MonkeyPatch):
    """A function making a commit `days` days after the merge, on top of a dated base."""
    commit_on(app, monkeypatch, MERGED_AT - timedelta(days=10), "dated base")

    def make(days: float, message: str) -> str:
        return commit_on(app, monkeypatch, MERGED_AT + timedelta(days=days), message)

    return make


def test_a_revert_dated_after_the_bound_is_found_only_without_the_bound(app: Path, dated) -> None:
    merge = dated(0, "feature")
    dated(40, f"Revert feature\n\nThis reverts commit {merge}.")
    bound = MERGED_AT + timedelta(days=30)

    bounded = reverts_merge(app, trunk="main", merge_commit=merge, repo=REPO, pr=PR, until=bound)
    unbounded = reverts_merge(app, trunk="main", merge_commit=merge, repo=REPO, pr=PR)

    assert bounded is False
    assert unbounded is True


def revert_search(app: Path, *, until_days: float = 30, merge: str | None = None) -> bool | None:
    """The search, with a host that names `merge` as the pull request's merge commit, or none."""
    forge = StandInForge()
    if merge:
        forge.merged[PR] = merge
    return reverts_pull_request(
        app,
        trunk="main",
        forge=forge,
        repo=REPO,
        pr=PR,
        since=MERGED_AT - timedelta(hours=1),
        until=MERGED_AT + timedelta(days=until_days),
    )


def test_the_pull_request_search_finds_a_revert_inside_the_bound_not_one_after_it(
    app: Path, dated
) -> None:
    merge = dated(0, "feature")
    dated(4, f"Revert feature\n\nReverts example/app#{PR}")
    dated(40, f"Revert feature again\n\nReverts example/app#{PR}")

    for named in (None, merge):
        assert revert_search(app, merge=named) is True
        assert revert_search(app, until_days=3, merge=named) is False


@pytest.mark.parametrize(
    "line",
    [
        pytest.param("Reverts example/app#43", id="another number"),
        pytest.param("Reverts example/platform#42", id="another repo"),
    ],
)
def test_the_pull_request_search_finds_nothing_for_a_revert_of_another_pull_request(
    app: Path, dated, line: str
) -> None:
    dated(0, f"feature (#{PR})")
    dated(4, f"Revert other\n\n{line}")

    assert revert_search(app) is False


def test_the_pull_request_search_finds_nothing_when_the_only_revert_is_after_the_bound(
    app: Path, dated
) -> None:
    dated(0, f"feature (#{PR})")
    dated(40, f"Revert feature\n\nReverts example/app#{PR}")

    assert revert_search(app) is False


def test_the_pull_request_search_reads_a_plain_revert_of_the_merge_commit_the_forge_names(
    app: Path, dated
) -> None:
    merge = dated(0, "feature, whatever its subject")
    dated(4, f"Revert feature\n\nThis reverts commit {merge}.")

    assert revert_search(app, merge=merge) is True


def test_the_pull_request_search_does_not_see_a_plain_revert_of_a_merge_it_cannot_identify(
    app: Path, dated
) -> None:
    merge = dated(0, "feature, merged some other way")
    dated(4, f"Revert feature\n\nThis reverts commit {merge}.")

    assert revert_search(app) is False


def test_the_pull_request_search_answers_none_when_the_checkout_cannot_be_searched(
    tmp_path: Path,
) -> None:
    assert revert_search(tmp_path) is None  # a folder that is no repository
