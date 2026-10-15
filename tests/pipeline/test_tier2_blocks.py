"""The runtimes blocked now: the configuration and the state file together, the configuration
winning (spec: tier2-runtime-blocks)."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier
from typing import Any

import pytest

from agent_build_kit.config import WorkspaceConfig
from agent_build_kit.pipeline.tier2_blocks import (
    BLOCKED_FILE,
    ORIGIN_CONFIGURATION,
    ORIGIN_FILE,
    Blocks,
    blocked_runtimes,
    write_block,
)

NOW = datetime(2030, 1, 1, 9, 0, tzinfo=UTC)


def config(**tests: Any) -> WorkspaceConfig:
    return WorkspaceConfig.model_validate({"tests": tests})


def read(cfg: WorkspaceConfig, state: Path, *, now: datetime = NOW) -> Blocks:
    return blocked_runtimes(cfg, state, now=now)


def block(
    state: Path,
    runtime: str = "acp",
    *,
    reason: str = "out of budget",
    source: str = "command",
    by: str = "someone",
    until: datetime | None = None,
    now: datetime = NOW - timedelta(hours=1),
) -> None:
    write_block(state, runtime, reason=reason, source=source, by=by, until=until, now=now)


def test_a_runtime_in_the_configuration_is_blocked_with_no_file(tmp_path: Path) -> None:
    found = read(config(runtimes_blocked=["acp"]), tmp_path)

    assert set(found.blocked) == {"acp"}
    assert found.blocked["acp"].origins == (ORIGIN_CONFIGURATION,)
    assert not found.unreadable


def test_a_runtime_in_the_file_is_blocked_with_no_configuration(tmp_path: Path) -> None:
    block(tmp_path, reason="out of budget")

    found = read(config(), tmp_path)

    assert set(found.blocked) == {"acp"}
    assert found.blocked["acp"].origins == (ORIGIN_FILE,)
    assert found.blocked["acp"].reason == "out of budget"


def test_a_runtime_in_both_is_blocked_once_with_both_origins(tmp_path: Path) -> None:
    block(tmp_path)

    found = read(config(runtimes_blocked=["acp"]), tmp_path)

    assert list(found.blocked) == ["acp"]
    assert set(found.blocked["acp"].origins) == {ORIGIN_CONFIGURATION, ORIGIN_FILE}


def test_a_runtime_in_neither_is_not_blocked(tmp_path: Path) -> None:
    block(tmp_path, "acp")

    found = read(config(runtimes_blocked=["acp"]), tmp_path)

    assert "claude_code" not in found.blocked
    assert read(config(), tmp_path / "nothing-here").blocked == {}


def test_the_configuration_allowing_a_runtime_beats_the_file(tmp_path: Path) -> None:
    block(tmp_path)

    found = read(config(runtimes_allowed=["acp"]), tmp_path)

    assert found.blocked == {}
    assert found.overridden == ("acp",)


def test_the_configuration_blocking_a_runtime_beats_a_missing_or_expired_entry(
    tmp_path: Path,
) -> None:
    cfg = config(runtimes_blocked=["acp"])
    assert set(read(cfg, tmp_path / "empty").blocked) == {"acp"}

    block(tmp_path, source="provider", until=NOW - timedelta(minutes=1))
    found = read(cfg, tmp_path)

    assert set(found.blocked) == {"acp"}
    assert found.blocked["acp"].origins == (ORIGIN_CONFIGURATION,)


@pytest.mark.parametrize("offset", [timedelta(minutes=-5), timedelta(0)], ids=["past", "now"])
def test_an_entry_whose_deadline_has_passed_or_is_now_no_longer_blocks(
    tmp_path: Path, offset: timedelta
) -> None:
    block(tmp_path, source="provider", until=NOW + offset)

    assert read(config(), tmp_path).blocked == {}


def test_an_entry_with_a_deadline_ahead_still_blocks_and_reports_it(tmp_path: Path) -> None:
    deadline = NOW + timedelta(minutes=5)
    block(tmp_path, source="availability", until=deadline)

    found = read(config(), tmp_path)

    assert found.blocked["acp"].until == deadline


def test_an_entry_with_no_deadline_never_expires(tmp_path: Path) -> None:
    block(tmp_path)

    found = read(config(), tmp_path, now=NOW + timedelta(days=3650))

    assert set(found.blocked) == {"acp"}
    assert found.blocked["acp"].until is None


def test_a_command_entry_is_never_written_with_a_deadline(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="command"):
        block(tmp_path, source="command", until=NOW + timedelta(hours=1))

    assert not (tmp_path / BLOCKED_FILE).exists()


def test_a_configuration_entry_never_expires(tmp_path: Path) -> None:
    found = read(config(runtimes_blocked=["acp"]), tmp_path, now=NOW + timedelta(days=3650))

    assert found.blocked["acp"].until is None


def test_reading_changes_nothing_on_disk(tmp_path: Path) -> None:
    block(tmp_path, source="provider", until=NOW - timedelta(hours=1))
    path = tmp_path / BLOCKED_FILE
    before = (
        path.read_bytes(),
        path.stat().st_mtime_ns,
        sorted(p.name for p in tmp_path.iterdir()),
    )

    read(config(), tmp_path)

    assert (
        path.read_bytes(),
        path.stat().st_mtime_ns,
        sorted(p.name for p in tmp_path.iterdir()),
    ) == before


def test_an_entry_carries_its_reason_time_deadline_source_and_writer(tmp_path: Path) -> None:
    written = NOW - timedelta(hours=2)
    deadline = NOW + timedelta(hours=1)
    block(
        tmp_path,
        reason="window full",
        source="provider",
        by="the provider check",
        until=deadline,
        now=written,
    )

    entry = read(config(), tmp_path).blocked["acp"]

    assert entry.reason == "window full"
    assert entry.since == written
    assert entry.until == deadline
    assert entry.source == "provider"
    assert entry.by == "the provider check"


@pytest.mark.parametrize("source", ["command", "provider", "availability"])
def test_each_source_is_accepted(tmp_path: Path, source: str) -> None:
    block(tmp_path, source=source)

    assert read(config(), tmp_path).blocked["acp"].source == source


def test_a_second_write_for_a_runtime_replaces_its_entry(tmp_path: Path) -> None:
    block(tmp_path, reason="first")
    block(tmp_path, reason="second")

    found = read(config(), tmp_path)

    assert list(found.blocked) == ["acp"]
    assert found.blocked["acp"].reason == "second"


def test_a_file_that_cannot_be_read_blocks_nothing_and_is_reported(tmp_path: Path) -> None:
    (tmp_path / BLOCKED_FILE).write_text("{not json")

    found = read(config(), tmp_path)

    assert found.blocked == {}
    assert found.unreadable


def test_an_unreadable_file_leaves_the_configurations_blocks(tmp_path: Path) -> None:
    (tmp_path / BLOCKED_FILE).write_text("{not json")

    found = read(config(runtimes_blocked=["acp"]), tmp_path)

    assert set(found.blocked) == {"acp"}
    assert found.unreadable


def test_an_entry_for_a_runtime_nothing_knows_is_ignored_and_reported(tmp_path: Path) -> None:
    block(tmp_path, "nothing")
    block(tmp_path, "acp")

    found = read(config(), tmp_path)

    assert set(found.blocked) == {"acp"}
    assert found.unknown == ("nothing",)


def test_two_writers_at_once_leave_a_file_holding_both_entries(tmp_path: Path) -> None:
    barrier = Barrier(2)

    def write(runtime: str) -> None:
        barrier.wait(timeout=10)
        block(tmp_path, runtime)

    with ThreadPoolExecutor(max_workers=2) as pool:
        for future in [pool.submit(write, "acp"), pool.submit(write, "claude_code")]:
            future.result(timeout=30)

    assert set(read(config(), tmp_path).blocked) == {"acp", "claude_code"}


def test_a_write_leaves_no_temporary_file_behind(tmp_path: Path) -> None:
    block(tmp_path)

    assert (tmp_path / BLOCKED_FILE).is_file()
    assert [p.name for p in tmp_path.iterdir() if p.suffix in (".tmp", ".part")] == []
