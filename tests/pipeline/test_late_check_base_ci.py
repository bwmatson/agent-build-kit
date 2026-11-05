"""A late check reads the merge commit's own checks first (spec: merged-waits-for-ci).

When every check that failed on the pull request is among the merge commit's checks and passed,
and none is running, the unit becomes merged with a note naming the commit, and no local run
starts. While a check of the merge commit runs, the unit stays settling and is asked again at the
next poll. A failed check on the merge commit, no check of the failed one's name, no checks at
all, or a forge that cannot answer: the failing tests run on the default branch as before.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agent_build_kit.forges import PullRequest, RepoId
from agent_build_kit.forges.base import (
    UNKNOWN_CHECKS,
    Check,
    CheckStatus,
    CommitChecks,
    CommitOutcome,
    commit_checks_of,
)
from agent_build_kit.pipeline import events
from agent_build_kit.pipeline.unit_store import Pull, StoredUnit, UnitStore
from agent_build_kit.pipeline.units import HELD, MERGED, PLANNED, SETTLING
from tests.factories import stored_unit
from tests.fake_clock import FakeClock, install
from tests.forges.stand_in import StandInForge

MERGE = "0123456789abcdef0123456789abcdef01234567"
TICK = 9
LOG = "FAILED tests/test_marker.py::test_registers - AssertionError"
MERGED_AT = datetime(2026, 10, 27, 11, 43, tzinfo=UTC)


class Base:
    """The local run on the default branch: what it said, and whether it was asked."""

    def __init__(self, passes: bool) -> None:
        self.passes = passes
        self.asked: list[str] = []

    def __call__(self, unit: StoredUnit, log: str) -> bool:
        self.asked.append(unit.id)
        return self.passes


class BaseChecks:
    """The forge's answer for the merge commit's checks, one per poll, and the commits asked,
    with the branch each was asked on."""

    def __init__(self, *answers: CommitChecks) -> None:
        self.answers = list(answers)
        self.asked: list[str] = []
        self.branches: list[str] = []

    def __call__(self, unit: StoredUnit, sha: str, branch: str) -> CommitChecks:
        self.asked.append(sha)
        self.branches.append(branch)
        return self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]


@pytest.fixture(autouse=True)
def clock(monkeypatch: pytest.MonkeyPatch) -> FakeClock:
    """Half an hour after the merge, well inside the wait for the merge commit's checks."""
    return install(monkeypatch, MERGED_AT + timedelta(minutes=30))


def checks(**statuses: CheckStatus) -> CommitChecks:
    return commit_checks_of([Check(name=name, status=s) for name, s in statuses.items()])


PASSED = CheckStatus.PASSED
FAILED = CheckStatus.FAILED
PENDING = CheckStatus.PENDING
SKIPPED = CheckStatus.SKIPPED


def late_fix(number: int, k: int) -> Pull:
    return Pull(
        number=number,
        branch=f"spec/add-marker/1-fix{k}",
        role="late-fix",
        merged_at=MERGED_AT,
        merge_sha=f"{MERGE[:-1]}{k}",
    )


def settling(tmp_path: Path, pulls: tuple[Pull, ...] = ()) -> UnitStore:
    first = Pull(number=4, branch="spec/add-marker/1", merged_at=MERGED_AT, merge_sha=MERGE)
    held = pulls or (first,)
    store = UnitStore(tmp_path / "units.json")
    store.upsert([stored_unit("add-marker/1")])
    store.set_state("add-marker/1", SETTLING, pr=held[-1].number, branch=held[-1].branch)
    store.set_pulls("add-marker/1", held)
    store.set_merge_record("add-marker/1", held[-1].merge_sha, None)
    return store


def red(number: int = 4, merge_commit: str | None = MERGE) -> PullRequest:
    return PullRequest(
        number=number,
        head="spec/add-marker/1",
        base="main",
        state="merged",
        checks=(
            Check(name="test", status=CheckStatus.FAILED),
            Check(name="lint", status=CheckStatus.PASSED),
        ),
        merge_commit=merge_commit,
    )


def late_check(
    store: UnitStore, base: Base, base_checks: BaseChecks, pull: PullRequest | None = None
) -> bool:
    dispatch = events.build_dispatch(
        store,
        restack=lambda **k: None,
        merge_record=lambda unit: (MERGE, TICK),
        fetch_checks=lambda repo, pull: LOG,
        base_passes=base,
        base_checks=base_checks,
        log=lambda m: None,
    )
    pull = pull or red()
    return dispatch("late_check", pull.number, repo="app", pull=pull)


def test_the_merge_commit_s_checks_all_passed_make_the_unit_merged_without_a_local_run(
    tmp_path: Path,
) -> None:
    store = settling(tmp_path)
    base, read = Base(passes=False), BaseChecks(checks(test=PASSED, lint=PASSED, types=PASSED))

    assert late_check(store, base, read) is True

    unit = store.get("add-marker/1")
    assert unit.state == MERGED
    assert unit.merged_tick == TICK
    assert base.asked == [], "no local run starts"
    assert read.asked == [MERGE]
    note = unit.history[-1]["note"]
    assert MERGE[:10] in note
    assert MERGE not in note, "the note names the commit in its short form"
    assert "passed" in note


def test_a_running_check_on_the_merge_commit_leaves_the_unit_settling_until_the_next_poll(
    tmp_path: Path,
) -> None:
    store = settling(tmp_path)
    base = Base(passes=False)
    read = BaseChecks(checks(test=PENDING, lint=PASSED), checks(test=PASSED, lint=PASSED))

    assert late_check(store, base, read) is True
    assert store.get("add-marker/1").state == SETTLING
    assert base.asked == []

    assert late_check(store, base, read) is True
    assert store.get("add-marker/1").state == MERGED
    assert base.asked == []
    assert read.asked == [MERGE, MERGE]


def test_a_running_check_on_the_merge_commit_is_waited_on_even_when_the_failed_one_passed(
    tmp_path: Path,
) -> None:
    store = settling(tmp_path)
    base = Base(passes=True)

    late_check(store, base, BaseChecks(checks(test=PASSED, slow=PENDING)))

    assert store.get("add-marker/1").state == SETTLING
    assert base.asked == []


@pytest.mark.parametrize(
    "answer",
    [
        pytest.param(checks(test=FAILED, lint=PASSED), id="failed-on-the-merge-commit"),
        pytest.param(checks(test=PASSED, lint=FAILED), id="another-check-failed"),
        pytest.param(checks(lint=PASSED, types=PASSED), id="no-check-of-that-name"),
        pytest.param(checks(), id="no-checks"),
        pytest.param(CommitChecks(outcome=CommitOutcome.UNKNOWN), id="unknown"),
    ],
)
def test_any_other_answer_runs_the_failing_tests_on_the_default_branch(
    tmp_path: Path, answer: CommitChecks
) -> None:
    store = settling(tmp_path)
    base = Base(passes=True)

    late_check(store, base, BaseChecks(answer))

    unit = store.get("add-marker/1")
    assert base.asked == ["add-marker/1"]
    assert unit.state == MERGED
    assert "fixed on the base" in unit.history[-1]["note"]


@pytest.mark.parametrize(
    "answer",
    [
        pytest.param(checks(test=FAILED), id="failed-on-the-merge-commit"),
        pytest.param(CommitChecks(outcome=CommitOutcome.UNKNOWN), id="unknown"),
    ],
)
def test_a_local_run_that_fails_sends_the_unit_to_its_late_fix(
    tmp_path: Path, answer: CommitChecks
) -> None:
    store = settling(tmp_path)
    base = Base(passes=False)

    late_check(store, base, BaseChecks(answer))

    unit = store.get("add-marker/1")
    assert base.asked == ["add-marker/1"]
    assert unit.state == PLANNED
    assert unit.branch == "spec/add-marker/1-fix1"


def test_after_two_late_fixes_a_failure_on_the_merge_commit_holds_the_unit(
    tmp_path: Path,
) -> None:
    first = Pull(number=4, branch="spec/add-marker/1", merged_at=MERGED_AT, merge_sha=MERGE)
    store = settling(tmp_path, (first, late_fix(9, 1), late_fix(12, 2)))

    late_check(store, Base(passes=False), BaseChecks(checks(test=FAILED)), pull=red(12))

    assert store.get("add-marker/1").state == HELD


def test_with_no_merge_commit_in_the_listing_the_unit_s_recorded_one_is_asked(
    tmp_path: Path,
) -> None:
    store = settling(tmp_path)
    read = BaseChecks(checks(test=PASSED))

    late_check(store, Base(passes=False), read, pull=red(merge_commit=None))

    assert read.asked == [MERGE]
    assert store.get("add-marker/1").state == MERGED


def test_a_unit_that_is_not_settling_reads_no_checks(tmp_path: Path) -> None:
    store = settling(tmp_path)
    store.set_state("add-marker/1", MERGED)
    read = BaseChecks(checks(test=PASSED))

    late_check(store, Base(passes=False), read)

    assert read.asked == []


# --- the read through the forge ---------------------------------------------------------


def test_the_read_asks_the_unit_s_forge_for_the_commit_s_checks() -> None:
    answer = checks(test=PASSED)
    forge = StandInForge(commit_checks={MERGE: answer})
    repo = RepoId(forge="stand_in", account="example", name="app")
    read = events.build_base_checks(for_repo=lambda name: (forge, repo))

    assert read(stored_unit("add-marker/1"), MERGE, "main") == answer
    assert forge.commit_check_reads == [MERGE]


def test_a_forge_that_raises_is_read_as_unknown() -> None:
    class Broken(StandInForge):
        def commit_checks(
            self, repo: RepoId, sha: str, *, branch: str = "", since: datetime | None = None
        ) -> CommitChecks:
            raise RuntimeError("the host went away")

    repo = RepoId(forge="stand_in", account="example", name="app")
    read = events.build_base_checks(for_repo=lambda name: (Broken(), repo))

    assert read(stored_unit("add-marker/1"), MERGE, "main").outcome == CommitOutcome.UNKNOWN


# --- review ------------------------------------------------------------------------------


def test_a_failed_check_skipped_on_the_merge_commit_runs_the_tests_locally(
    tmp_path: Path,
) -> None:
    store = settling(tmp_path)
    base = Base(passes=True)

    late_check(store, base, BaseChecks(checks(test=SKIPPED, lint=PASSED)))

    assert base.asked == ["add-marker/1"], "a skipped check ran nothing, so it is no pass"
    assert "fixed on the base" in store.get("add-marker/1").history[-1]["note"]


def test_the_merge_commit_s_checks_are_asked_on_the_pull_request_s_base(tmp_path: Path) -> None:
    store = settling(tmp_path)
    read = BaseChecks(checks(test=PASSED))

    late_check(store, Base(passes=False), read)

    assert read.branches == ["main"]


def test_checks_still_running_long_after_the_merge_are_given_up_for_the_local_run(
    tmp_path: Path, clock: FakeClock
) -> None:
    store = settling(tmp_path)
    base = Base(passes=False)
    read = BaseChecks(checks(test=PENDING))
    clock.advance((events.BASE_CHECKS_WAIT - timedelta(minutes=31)).total_seconds())

    late_check(store, base, read)
    assert store.get("add-marker/1").state == SETTLING
    assert base.asked == []

    clock.advance(timedelta(minutes=2).total_seconds())
    late_check(store, base, read)
    assert base.asked == ["add-marker/1"]
    assert store.get("add-marker/1").state == PLANNED


def test_a_unit_after_two_late_fixes_whose_merge_commit_passed_is_merged_not_held(
    tmp_path: Path,
) -> None:
    first = Pull(number=4, branch="spec/add-marker/1", merged_at=MERGED_AT, merge_sha=MERGE)
    store = settling(tmp_path, (first, late_fix(9, 1), late_fix(12, 2)))
    base = Base(passes=False)

    late_check(store, base, BaseChecks(checks(test=PASSED)), pull=red(12))

    assert store.get("add-marker/1").state == MERGED
    assert base.asked == []


class Recording(StandInForge):
    def __init__(self) -> None:
        super().__init__()
        self.kwargs: list[dict] = []

    def commit_checks(
        self, repo: RepoId, sha: str, *, branch: str = "", since: datetime | None = None
    ) -> CommitChecks:
        self.kwargs.append({"branch": branch, "since": since})
        return UNKNOWN_CHECKS


def test_the_read_asks_for_the_branch_and_from_shortly_before_the_merge() -> None:
    forge = Recording()
    repo = RepoId(forge="stand_in", account="example", name="app")
    unit = stored_unit(
        "add-marker/1",
        pulls=(Pull(number=4, branch="spec/add-marker/1", merged_at=MERGED_AT, merge_sha=MERGE),),
    )

    events.build_base_checks(for_repo=lambda name: (forge, repo))(unit, MERGE, "main")

    [asked] = forge.kwargs
    assert asked["branch"] == "main"
    assert asked["since"] is not None and asked["since"] <= MERGED_AT
    assert MERGED_AT - asked["since"] <= timedelta(hours=1)
