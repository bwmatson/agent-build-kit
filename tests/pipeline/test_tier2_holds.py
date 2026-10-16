"""The splits held now: the configuration and the state file together, the configuration
winning (spec: tier2-holds)."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier

import pytest

from agent_build_kit.config import Tier2Split
from agent_build_kit.pipeline.e2e_holds import (
    HELD_FILE,
    ORIGIN_CONFIGURATION,
    ORIGIN_FILE,
    SOURCE_GATE,
    Holds,
    held_splits,
    remove_hold,
    write_hold,
)

NOW = datetime(2030, 1, 1, 9, 0, tzinfo=UTC)


def splits(**holds: bool | None) -> tuple[Tier2Split, ...]:
    """`acp` and `claude_code` declared with the given `hold`s, then `rest`; a `rest` key sets
    the hold of `rest`."""
    return (
        Tier2Split(name="acp", marker="runtime_acp", hold=holds.get("acp")),
        Tier2Split(name="claude_code", marker="runtime_claude_code", hold=holds.get("claude_code")),
        Tier2Split(name="rest", hold=holds.get("rest")),
    )


def read(declared: tuple[Tier2Split, ...], state: Path, *, now: datetime = NOW) -> Holds:
    return held_splits(declared, state, now=now)


def hold(
    state: Path,
    split: str = "acp",
    *,
    reason: str = "out of budget",
    source: str = "command",
    by: str = "someone",
    until: datetime | None = None,
    now: datetime = NOW - timedelta(hours=1),
) -> None:
    write_hold(state, split, reason=reason, source=source, by=by, until=until, now=now)


def test_a_split_with_hold_true_is_held_with_no_file(tmp_path: Path) -> None:
    found = read(splits(acp=True), tmp_path)

    assert set(found.held) == {"acp"}
    assert found.held["acp"].origins == (ORIGIN_CONFIGURATION,)
    assert not found.unreadable


def test_a_split_in_the_file_is_held_with_no_configuration_entry(tmp_path: Path) -> None:
    hold(tmp_path, reason="out of budget")

    found = read(splits(), tmp_path)

    assert set(found.held) == {"acp"}
    assert found.held["acp"].origins == (ORIGIN_FILE,)
    assert found.held["acp"].reason == "out of budget"


def test_a_split_in_both_is_held_once_with_both_origins(tmp_path: Path) -> None:
    hold(tmp_path)

    found = read(splits(acp=True), tmp_path)

    assert list(found.held) == ["acp"]
    assert set(found.held["acp"].origins) == {ORIGIN_CONFIGURATION, ORIGIN_FILE}


def test_a_split_in_neither_is_not_held(tmp_path: Path) -> None:
    hold(tmp_path, "acp")

    found = read(splits(claude_code=True), tmp_path)

    assert set(found.held) == {"claude_code", "acp"}
    assert "rest" not in found.held
    assert read(splits(), tmp_path / "nothing-here").held == {}


@pytest.mark.parametrize("how", ["configuration", "file"])
def test_rest_is_held_like_any_split(tmp_path: Path, how: str) -> None:
    if how == "file":
        hold(tmp_path, "rest")

    found = read(splits(rest=True) if how == "configuration" else splits(), tmp_path)

    assert set(found.held) == {"rest"}


@pytest.mark.parametrize("source", ["command", SOURCE_GATE])
def test_hold_false_releases_what_the_file_holds_and_names_the_entry(
    tmp_path: Path, source: str
) -> None:
    hold(tmp_path, source=source)

    found = read(splits(acp=False), tmp_path)

    assert found.held == {}
    assert found.overridden == ("acp",)


def test_hold_true_stays_held_when_the_file_has_no_entry_or_an_expired_one(
    tmp_path: Path,
) -> None:
    declared = splits(acp=True)
    assert set(read(declared, tmp_path / "empty").held) == {"acp"}

    hold(tmp_path, source=SOURCE_GATE, until=NOW - timedelta(minutes=1))
    found = read(declared, tmp_path)

    assert set(found.held) == {"acp"}
    assert found.held["acp"].origins == (ORIGIN_CONFIGURATION,)


@pytest.mark.parametrize("offset", [timedelta(minutes=-5), timedelta(0)], ids=["past", "now"])
def test_an_entry_whose_deadline_has_passed_or_is_now_no_longer_holds(
    tmp_path: Path, offset: timedelta
) -> None:
    hold(tmp_path, source=SOURCE_GATE, until=NOW + offset)

    assert read(splits(), tmp_path).held == {}


def test_an_entry_with_a_deadline_ahead_still_holds_and_reports_it(tmp_path: Path) -> None:
    deadline = NOW + timedelta(minutes=5)
    hold(tmp_path, source=SOURCE_GATE, until=deadline)

    found = read(splits(), tmp_path)

    assert found.held["acp"].until == deadline


def test_an_entry_with_no_deadline_never_expires(tmp_path: Path) -> None:
    hold(tmp_path)

    found = read(splits(), tmp_path, now=NOW + timedelta(days=3650))

    assert set(found.held) == {"acp"}
    assert found.held["acp"].until is None


@pytest.mark.parametrize("source", ["command", "something-later"])
def test_only_a_gate_entry_is_ever_written_with_a_deadline(tmp_path: Path, source: str) -> None:
    with pytest.raises(ValueError, match=source):
        hold(tmp_path, source=source, until=NOW + timedelta(hours=1))

    assert not (tmp_path / HELD_FILE).exists()


def test_a_gate_entry_may_carry_a_deadline(tmp_path: Path) -> None:
    deadline = NOW + timedelta(hours=1)
    hold(tmp_path, source=SOURCE_GATE, until=deadline)

    assert read(splits(), tmp_path).held["acp"].until == deadline


def test_a_configuration_entry_never_expires(tmp_path: Path) -> None:
    found = read(splits(acp=True), tmp_path, now=NOW + timedelta(days=3650))

    assert found.held["acp"].until is None


def test_reading_changes_nothing_on_disk(tmp_path: Path) -> None:
    hold(tmp_path, source=SOURCE_GATE, until=NOW - timedelta(hours=1))
    path = tmp_path / HELD_FILE
    before = (
        path.read_bytes(),
        path.stat().st_mtime_ns,
        sorted(p.name for p in tmp_path.iterdir()),
    )

    read(splits(), tmp_path)

    assert (
        path.read_bytes(),
        path.stat().st_mtime_ns,
        sorted(p.name for p in tmp_path.iterdir()),
    ) == before


def test_an_entry_carries_its_reason_time_deadline_source_and_writer(tmp_path: Path) -> None:
    written = NOW - timedelta(hours=2)
    deadline = NOW + timedelta(hours=1)
    hold(
        tmp_path,
        reason="window full",
        source=SOURCE_GATE,
        by="the split's gate",
        until=deadline,
        now=written,
    )

    entry = read(splits(), tmp_path).held["acp"]

    assert entry.reason == "window full"
    assert entry.since == written
    assert entry.until == deadline
    assert entry.source == SOURCE_GATE
    assert entry.by == "the split's gate"


def test_a_source_the_code_does_not_know_holds_and_is_shown_as_written(tmp_path: Path) -> None:
    hold(tmp_path, source="something-later")

    found = read(splits(), tmp_path)

    assert set(found.held) == {"acp"}
    assert found.held["acp"].source == "something-later"


def test_a_file_that_cannot_be_read_holds_nothing_and_is_reported(tmp_path: Path) -> None:
    (tmp_path / HELD_FILE).write_text("not json")

    found = read(splits(), tmp_path)

    assert found.held == {}
    assert found.unreadable
    assert (tmp_path / HELD_FILE).read_text() == "not json"


def test_an_unreadable_file_leaves_the_configurations_holds(tmp_path: Path) -> None:
    (tmp_path / HELD_FILE).write_text("not json")

    found = read(splits(acp=True), tmp_path)

    assert set(found.held) == {"acp"}
    assert found.unreadable


def test_an_entry_for_a_split_nothing_declares_is_ignored_and_reported(tmp_path: Path) -> None:
    hold(tmp_path, "nothing")
    hold(tmp_path, "acp")

    found = read(splits(), tmp_path)

    assert set(found.held) == {"acp"}
    assert found.unknown == ("nothing",)


def test_the_known_names_are_the_declared_splits_and_rest(tmp_path: Path) -> None:
    hold(tmp_path, "claude_code")

    found = read((Tier2Split(name="rest"),), tmp_path)

    assert found.held == {}
    assert found.unknown == ("claude_code",)


def test_two_writers_at_once_leave_a_file_holding_both_entries(tmp_path: Path) -> None:
    barrier = Barrier(2)

    def write(split: str) -> None:
        barrier.wait(timeout=10)
        hold(tmp_path, split)

    with ThreadPoolExecutor(max_workers=2) as pool:
        for future in [pool.submit(write, "acp"), pool.submit(write, "claude_code")]:
            future.result(timeout=30)

    assert set(read(splits(), tmp_path).held) == {"acp", "claude_code"}


def test_a_second_write_for_a_split_replaces_its_entry(tmp_path: Path) -> None:
    hold(tmp_path, reason="first")
    hold(tmp_path, reason="second")

    found = read(splits(), tmp_path)

    assert list(found.held) == ["acp"]
    assert found.held["acp"].reason == "second"


def test_removing_an_entry_leaves_the_others(tmp_path: Path) -> None:
    hold(tmp_path, "acp")
    hold(tmp_path, "claude_code")

    assert remove_hold(tmp_path, "acp") is True

    assert set(read(splits(), tmp_path).held) == {"claude_code"}


def test_removing_an_entry_that_is_absent_says_so_and_changes_nothing(tmp_path: Path) -> None:
    hold(tmp_path, "acp")
    before = (tmp_path / HELD_FILE).read_bytes()

    assert remove_hold(tmp_path, "claude_code") is False

    assert (tmp_path / HELD_FILE).read_bytes() == before
    assert remove_hold(tmp_path / "nothing-here", "acp") is False


def test_removing_from_a_file_that_cannot_be_read_raises_and_leaves_it(tmp_path: Path) -> None:
    (tmp_path / HELD_FILE).write_text("not json")

    with pytest.raises(ValueError, match="cannot be read"):
        remove_hold(tmp_path, "acp")

    assert (tmp_path / HELD_FILE).read_text() == "not json"


def test_a_leftover_blocked_file_is_never_read(tmp_path: Path) -> None:
    entry = {"reason": "r", "since": NOW.isoformat(), "source": "command", "by": "x"}
    (tmp_path / "tier2-blocked.json").write_text(json.dumps({"acp": entry}))

    found = read(splits(), tmp_path)

    assert found.held == {}
    assert not found.unreadable
    assert found.unknown == ()


def test_a_write_leaves_no_temporary_file_behind(tmp_path: Path) -> None:
    hold(tmp_path)

    assert (tmp_path / HELD_FILE).is_file()
    assert [p.name for p in tmp_path.iterdir() if p.suffix in (".tmp", ".part")] == []


def test_an_entry_with_a_time_that_has_no_offset_reads_as_an_unreadable_file(
    tmp_path: Path,
) -> None:
    entry = {
        "reason": "r",
        "since": NOW.isoformat(),
        "until": (NOW + timedelta(days=1)).replace(tzinfo=None).isoformat(),
        "source": SOURCE_GATE,
        "by": "x",
    }
    (tmp_path / HELD_FILE).write_text(json.dumps({"acp": entry}))

    found = read(splits(), tmp_path)

    assert found.held == {}
    assert found.unreadable


def test_a_deadline_with_no_offset_is_refused_before_anything_is_written(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="timezone"):
        hold(tmp_path, source=SOURCE_GATE, until=datetime(2031, 1, 1))

    assert not (tmp_path / HELD_FILE).exists()


def test_a_written_time_with_no_offset_is_refused_before_anything_is_written(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="timezone"):
        hold(tmp_path, now=datetime(2031, 1, 1))

    assert not (tmp_path / HELD_FILE).exists()


OLD_HELD_FILE = "tier2-held.json"


def test_a_hold_left_in_the_file_under_the_old_name_still_holds(tmp_path: Path) -> None:
    hold(tmp_path)
    (tmp_path / HELD_FILE).rename(tmp_path / OLD_HELD_FILE)

    assert set(read(splits(), tmp_path).held) == {"acp"}
    assert (tmp_path / HELD_FILE).is_file()
    assert not (tmp_path / OLD_HELD_FILE).exists()


def test_a_hold_under_the_old_name_is_released_by_remove_hold(tmp_path: Path) -> None:
    hold(tmp_path)
    (tmp_path / HELD_FILE).rename(tmp_path / OLD_HELD_FILE)

    assert remove_hold(tmp_path, "acp") is True
    assert read(splits(), tmp_path).held == {}


def test_the_new_file_wins_when_both_exist(tmp_path: Path) -> None:
    hold(tmp_path, "claude_code")
    (tmp_path / OLD_HELD_FILE).write_text("{}")

    assert set(read(splits(), tmp_path).held) == {"claude_code"}
    assert (tmp_path / OLD_HELD_FILE).exists()
