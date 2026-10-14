"""The "Tier 2 results" section lists the time of each test: the three slowest entries
lead, the listing is cut to `global_limits.tier2_durations_shown` with every entry kept, and an
entry with no split shows a dash (spec: tier2-time-is-recorded-per-test)."""

from pathlib import Path

from agent_build_kit.pipeline.tier2 import TestTime, Tier2Result, build_snapshot
from tests.conftest import make_installation
from tests.tier2_duration_fakes import E2E, timed


def _result(*durations: TestTime) -> Tier2Result:
    return Tier2Result(
        sha="abcdef0123",
        passed=3,
        failed=0,
        skipped=0,
        duration_seconds=1.5,
        command="uv run pytest -m local_stack",
        output="3 passed in 1.50s",
        durations=list(durations),
    )


def _listing(snapshot: str) -> str:
    """The section above the output, which is where the listing sits."""
    return snapshot.split("<details>")[0]


def _rows(snapshot: str) -> list[str]:
    return [
        line for line in _listing(snapshot).splitlines() if line.startswith("|") and "::" in line
    ]


def _entries(count: int) -> list[TestTime]:
    return [timed(100.0 - n, f"{E2E}::test_{n:02d}") for n in range(count)]


def test_the_three_slowest_entries_lead_with_their_phase_and_time() -> None:
    entries = [
        timed(30.0, f"{E2E}::test_d"),
        timed(374.0, f"{E2E}::test_c"),
        timed(842.0, f"{E2E}::test_a"),
        timed(571.0, f"{E2E}::test_b", "setup"),
    ]

    snapshot = build_snapshot(_result(*entries))

    (slowest,) = [line for line in _listing(snapshot).splitlines() if "Slowest" in line]
    first = slowest.index(f"`{E2E}::test_a` call 14m 2s")
    second = slowest.index(f"`{E2E}::test_b` setup 9m 31s")
    third = slowest.index(f"`{E2E}::test_c` call 6m 14s")
    assert first < second < third
    assert "test_d" not in slowest
    assert snapshot.index("Slowest") < snapshot.index("Ran against")


def test_a_pipe_in_a_test_id_does_not_split_its_row() -> None:
    test = f"{E2E}::test_x[a|b]"

    (row,) = _rows(build_snapshot(_result(timed(5.0, test))))

    assert f"`{E2E}::test_x[a\\|b]`" in row
    assert row.replace("\\|", "").count("|") == 7


def test_the_listing_is_slowest_first_whatever_the_order_given() -> None:
    entries = [timed(5.0, f"{E2E}::test_a"), timed(50.0, f"{E2E}::test_b")]

    rows = _rows(build_snapshot(_result(*entries)))

    assert ["test_b" in rows[0], "test_a" in rows[1]] == [True, True]
    assert len(rows) == 2


def test_the_listing_is_cut_to_the_configured_number_and_all_entries_are_kept(
    tmp_path: Path,
) -> None:
    make_installation(tmp_path, limits={"tier2_durations_shown": 5})
    result = _result(*_entries(12))

    snapshot = build_snapshot(result)

    assert len(_rows(snapshot)) == 5
    assert "5 of 12 shown" in _listing(snapshot)
    assert len(result.durations) == 12


def test_zero_lists_every_entry(tmp_path: Path) -> None:
    make_installation(tmp_path, limits={"tier2_durations_shown": 0})

    snapshot = build_snapshot(_result(*_entries(40)))

    assert len(_rows(snapshot)) == 40


def test_fifteen_entries_are_listed_by_default() -> None:
    snapshot = build_snapshot(_result(*_entries(16)))

    assert len(_rows(snapshot)) == 15
    assert "15 of 16 shown" in _listing(snapshot)


def test_an_entry_shows_its_split_and_one_without_shows_a_dash() -> None:
    split = TestTime(
        test=f"{E2E}::test_a",
        phase="call",
        seconds=270.0,
        agent_ms={"implement": 120_000},
        calls={"implement": 1},
        checks_ms=90_000,
        other_ms=60_000,
    )

    rows = _rows(build_snapshot(_result(split, timed(10.0, f"{E2E}::test_b"))))

    with_split = next(row for row in rows if "test_a" in row)
    without = next(row for row in rows if "test_b" in row)
    for shown in ("2m 0s", "1m 30s", "1m 0s"):
        assert shown in with_split
    assert "- | - | -" in without.replace("  ", " ")


def test_a_result_with_no_durations_has_no_listing_and_a_stored_one_still_loads() -> None:
    stored = _result().model_dump(mode="json", exclude={"durations"})

    loaded = Tier2Result.model_validate(stored)

    assert loaded.durations == []
    assert "Slowest" not in build_snapshot(loaded)
    assert "Slowest" in build_snapshot(_result(timed(5.0)))
