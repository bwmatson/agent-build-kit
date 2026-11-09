"""The base's selection data is recorded, kept with its commit, and refreshed by age (spec:
selection-data-comes-from-the-base). A small real git project is the base; the recording run is
the faked boundary, writing a data file where it is told."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agent_build_kit.pipeline.scratch import selection_seed
from agent_build_kit.pipeline.selection_base import (
    BaseRecording,
    hand_over,
    kept_recordings,
    refresh_base_data,
)
from agent_build_kit.pipeline.shell import git
from tests.selection_base_fakes import BaseRepo

START = datetime(2026, 11, 8, 9, 0, tzinfo=UTC)


class Recorder:
    """The recording run: writes a data file naming the commit it was told to record."""

    def __init__(self) -> None:
        self.commits: list[str] = []

    def __call__(self, commit: str, data: Path) -> None:
        self.commits.append(commit)
        data.parent.mkdir(parents=True, exist_ok=True)
        data.write_text(f"data@{commit}")


class Base(BaseRepo):
    """A repository whose `main` is the base, and the store the recordings are kept in."""

    def __init__(self, tmp_path: Path) -> None:
        super().__init__(tmp_path / "app")
        self.store = tmp_path / "state" / "selection-base"
        self.recorder = Recorder()
        self.now = START

    def refresh(self, *, kept: int = 3, max_age_hours: float = 12) -> BaseRecording | None:
        return refresh_base_data(
            store=self.store,
            repo=self.repo,
            base="main",
            record=self.recorder,
            kept=kept,
            max_age_hours=max_age_hours,
            now=lambda: self.now,
        )

    def later(self, hours: float) -> None:
        self.now += timedelta(hours=hours)


@pytest.fixture
def base(tmp_path: Path) -> Base:
    return Base(tmp_path)


def test_a_recording_of_the_bases_tip_is_kept_with_its_commit(base: Base) -> None:
    tip = base.tip()

    made = base.refresh()

    assert made is not None and made.commit == tip
    assert base.recorder.commits == [tip]
    (kept,) = kept_recordings(base.store)
    assert kept.commit == tip and kept.recorded_at == START
    assert kept.path.read_text() == f"data@{tip}"


def test_a_moved_base_is_recorded_again_once_the_last_recording_is_older_than_the_limit(
    base: Base,
) -> None:
    base.refresh()
    base.later(13)
    tip = base.move()

    made = base.refresh()

    assert made is not None and made.commit == tip
    assert [r.commit for r in kept_recordings(base.store)][-1] == tip
    assert len(kept_recordings(base.store)) == 2


def test_a_moved_base_is_not_recorded_while_the_last_recording_is_younger_than_the_limit(
    base: Base,
) -> None:
    base.refresh()
    base.later(11)
    base.move()

    assert base.refresh() is None
    assert len(base.recorder.commits) == 1
    assert len(kept_recordings(base.store)) == 1


def test_a_base_that_has_not_moved_is_not_recorded_again_however_old_the_recording(
    base: Base,
) -> None:
    base.refresh()
    base.later(48)

    assert base.refresh() is None
    assert len(base.recorder.commits) == 1


def test_at_most_the_set_number_of_recordings_are_kept_and_the_oldest_goes_first(
    base: Base,
) -> None:
    tips = []
    for _ in range(4):
        base.refresh(kept=3)
        tips.append(base.tip())
        base.later(13)
        base.move()

    left = kept_recordings(base.store)

    assert [r.commit for r in left] == tips[1:]
    assert not any(tips[0] in p.name for p in base.store.rglob("*") if p.is_file())


def test_the_recordings_are_listed_oldest_first(base: Base) -> None:
    for _ in range(2):
        base.refresh()
        base.later(13)
        base.move()

    stamps = [r.recorded_at for r in kept_recordings(base.store)]

    assert len(stamps) == 2 and stamps == sorted(stamps)


def test_a_recording_that_fails_leaves_no_data_file_in_the_store(base: Base) -> None:
    def fails(commit: str, data: Path) -> None:
        data.parent.mkdir(parents=True, exist_ok=True)
        data.write_text("partial")
        raise RuntimeError("the recording run failed")

    base.recorder = fails  # type: ignore[assignment]

    with pytest.raises(RuntimeError):
        base.refresh()

    assert list(base.store.iterdir()) == []
    assert kept_recordings(base.store) == []


def test_a_failed_recording_of_a_commit_already_kept_leaves_that_recording_listed(
    base: Base,
) -> None:
    first = base.tip()
    base.refresh()
    base.later(13)
    base.move()
    base.refresh()
    base.later(13)
    git(base.repo, "reset", "--hard", first)

    def fails(commit: str, data: Path) -> None:
        data.write_text("partial")
        raise RuntimeError("the recording run failed")

    base.recorder = fails  # type: ignore[assignment]
    with pytest.raises(RuntimeError):
        base.refresh()

    listed = {r.commit: r for r in kept_recordings(base.store)}
    assert listed[first].path.read_text() == f"data@{first}"
    assert len(listed) == 2
    assert not list(base.store.glob("*.tmp"))


def test_no_recordings_may_be_kept_below_one(base: Base) -> None:
    with pytest.raises(ValueError):
        base.refresh(kept=0)

    assert kept_recordings(base.store) == []


def test_a_store_that_does_not_exist_holds_no_recording(tmp_path: Path) -> None:
    assert kept_recordings(tmp_path / "missing") == []


@pytest.mark.parametrize(
    ("unit_base", "expected"),
    [(3, 2), (2, 2), (1, 0), (0, 0)],
    ids=["after the last", "at the last", "between", "at the first"],
)
def test_a_unit_is_given_the_recording_nearest_at_or_before_its_base(
    base: Base, tmp_path: Path, unit_base: int, expected: int
) -> None:
    # Four commits of the base; recordings sit at the first and the third.
    commits = [base.tip()]
    base.refresh()
    base.later(13)
    commits.append(base.move())
    commits.append(base.move())
    base.refresh()
    commits.append(base.move())
    worktree = tmp_path / "unit"

    given = hand_over(store=base.store, repo=base.repo, base=commits[unit_base], worktree=worktree)

    assert given is not None
    assert given.commit == commits[expected]
    assert selection_seed(worktree).read_text() == f"data@{commits[expected]}"


def test_a_recording_made_after_the_units_base_is_not_given(base: Base, tmp_path: Path) -> None:
    first = base.tip()
    base.move()
    base.refresh()
    worktree = tmp_path / "unit"

    given = hand_over(store=base.store, repo=base.repo, base=first, worktree=worktree)

    assert given is None
    assert not selection_seed(worktree).exists()


def test_a_unit_gets_a_copy_so_its_own_rounds_leave_the_kept_recording_alone(
    base: Base, tmp_path: Path
) -> None:
    base.refresh()
    worktree = tmp_path / "unit"
    given = hand_over(store=base.store, repo=base.repo, base=base.tip(), worktree=worktree)
    assert given is not None

    selection_seed(worktree).write_text("moved on by the unit's run")

    assert given.path.read_text() == f"data@{given.commit}"
    assert [r.commit for r in kept_recordings(base.store)] == [given.commit]


def test_no_recording_gives_a_unit_nothing(base: Base, tmp_path: Path) -> None:
    worktree = tmp_path / "unit"

    assert hand_over(store=base.store, repo=base.repo, base="main", worktree=worktree) is None
    assert not selection_seed(worktree).exists()
