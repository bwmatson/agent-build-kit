"""The base's selection data is recorded, kept with its commit, and refreshed by age (spec:
selection-data-comes-from-the-base). A small real git project is the base; the recording run is
the faked boundary, writing a data file where it is told."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agent_build_kit.pipeline.selection_base import (
    BaseRecording,
    kept_recordings,
    refresh_base_data,
)
from agent_build_kit.pipeline.shell import git, git_out

START = datetime(2026, 11, 8, 9, 0, tzinfo=UTC)


class Recorder:
    """The recording run: writes a data file naming the commit it was told to record."""

    def __init__(self) -> None:
        self.commits: list[str] = []

    def __call__(self, commit: str, data: Path) -> None:
        self.commits.append(commit)
        data.parent.mkdir(parents=True, exist_ok=True)
        data.write_text(f"data@{commit}")


class Base:
    """A repository whose `main` is the base, and the store the recordings are kept in."""

    def __init__(self, tmp_path: Path) -> None:
        self.repo = tmp_path / "app"
        self.store = tmp_path / "state" / "selection-base"
        self.recorder = Recorder()
        self.now = START
        self.repo.mkdir()
        git(self.repo, "init", "-b", "main")
        git(self.repo, "config", "user.email", "a@example.com")
        git(self.repo, "config", "user.name", "a")
        self.move()

    def tip(self) -> str:
        return git_out(self.repo, "rev-parse", "main").strip()

    def move(self) -> str:
        """A new commit on the base; its hash."""
        marker = self.repo / "marker.txt"
        marker.write_text(marker.read_text() + "x" if marker.exists() else "x")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-m", "move")
        return self.tip()

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


def test_a_store_that_does_not_exist_holds_no_recording(base: Base) -> None:
    base.refresh()  # the module exists and runs

    assert kept_recordings(base.store.parent / "elsewhere") == []
