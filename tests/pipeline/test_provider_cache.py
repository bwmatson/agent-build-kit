"""A good reading is kept per split for its cache time, and never past its window's end."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from agent_build_kit.config import GateConfig
from agent_build_kit.pipeline import usage_guard
from agent_build_kit.pipeline.usage_guard import GateResult, gate_result
from tests.provider_gate_support import gate
from tests.provider_summaries import END, START, summary

T0 = datetime(2026, 10, 14, 9, 0, tzinfo=START.tzinfo)


class Provider:
    """A reading function that counts how often it is asked and answers a metered cost."""

    def __init__(self, cost: str = "100", *, error: Exception | None = None, **fields) -> None:  # noqa: ANN003
        self.cost = cost
        self.error = error
        self.fields = fields
        self.asked = 0

    def __call__(self) -> object:
        self.asked += 1
        if self.error is not None:
            raise self.error
        return summary(metered_cost=Decimal(self.cost), **self.fields)


def evaluate(
    state_dir: Path,
    provider: Provider,
    *,
    at: datetime = T0,
    config: GateConfig | None = None,
    split: str = "acp",
    refresh: bool = False,
) -> GateResult:
    return gate_result(
        split,
        config or gate(),
        now=at,
        state_dir=state_dir,
        root=state_dir,
        refresh=refresh,
        read=provider,
    )


def minutes(count: float) -> timedelta:
    return timedelta(minutes=count)


def test_a_reading_three_minutes_old_answers_a_round_status_and_a_second_process(
    tmp_path: Path,
) -> None:
    taken = Provider("100")
    evaluate(tmp_path, taken)

    # Each reader asks with a reading function of its own, which must not be called.
    readers = [Provider("999") for _ in range(3)]
    answers = [evaluate(tmp_path, reader, at=T0 + minutes(3)) for reader in readers]

    assert [reader.asked for reader in readers] == [0, 0, 0]
    assert {answer.used_pct for answer in answers} == {50}


def test_a_reading_sixteen_minutes_old_is_replaced(tmp_path: Path) -> None:
    evaluate(tmp_path, Provider("100"))
    later = Provider("160")

    result = evaluate(tmp_path, later, at=T0 + minutes(16))

    assert (later.asked, result.used_pct) == (1, 80)


def test_the_cache_time_of_the_gate_is_honoured(tmp_path: Path) -> None:
    five = gate(usage_cache_minutes=5)
    evaluate(tmp_path, Provider("100"), config=five)
    within, past = Provider("120"), Provider("120")

    kept = evaluate(tmp_path, within, at=T0 + minutes(4), config=five)
    replaced = evaluate(tmp_path, past, at=T0 + minutes(6), config=five)

    assert (within.asked, kept.used_pct) == (0, 50)
    assert (past.asked, replaced.used_pct) == (1, 60)


def test_a_reading_is_dropped_at_its_windows_end_whatever_its_age(tmp_path: Path) -> None:
    last_minutes = END - minutes(10)
    evaluate(tmp_path, Provider("100"), at=last_minutes)
    november = Provider("4", start=END, end=datetime(2026, 12, 1, tzinfo=END.tzinfo))

    result = evaluate(tmp_path, november, at=END + minutes(1))

    assert (november.asked, result.used_pct) == (1, 2)


def test_an_unknown_result_is_kept_for_the_stale_retry_time(tmp_path: Path) -> None:
    missing = Provider(error=ImportError("no module named modal"))

    results = [evaluate(tmp_path, missing, at=T0 + minutes(offset)) for offset in (0, 1, 2)]

    assert missing.asked == 1
    assert {result.state for result in results} == {"unknown"}

    evaluate(tmp_path, missing, at=T0 + minutes(6))
    assert missing.asked == 2


def test_a_refresh_runs_the_provider_at_once(tmp_path: Path) -> None:
    evaluate(tmp_path, Provider("100"))
    again = Provider("120")

    result = evaluate(tmp_path, again, at=T0 + minutes(1), refresh=True)

    assert (again.asked, result.used_pct) == (1, 60)
    # And the refresh replaced the cache.
    after = Provider("999")
    assert evaluate(tmp_path, after, at=T0 + minutes(2)).used_pct == 60


def test_two_splits_keep_two_readings(tmp_path: Path) -> None:
    evaluate(tmp_path, Provider("100"), split="acp")
    evaluate(tmp_path, Provider("40"), split="other")
    unasked = Provider("999")

    acp = evaluate(tmp_path, unasked, at=T0 + minutes(1), split="acp")
    other = evaluate(tmp_path, unasked, at=T0 + minutes(1), split="other")

    assert (acp.used_pct, other.used_pct, unasked.asked) == (50, 20, 0)


def test_a_command_gates_result_is_cached_too(tmp_path: Path) -> None:
    runs: list[list[str]] = []

    def run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        runs.append(argv)
        return subprocess.CompletedProcess(argv, 3, stdout="quota spent\n", stderr="")

    config = GateConfig(command=["probe"], usage_cache_minutes=15)

    def ask(at: datetime) -> GateResult:
        return gate_result(
            "acp", config, now=at, state_dir=tmp_path, root=tmp_path, read=None, run=run
        )

    first, second = ask(T0), ask(T0 + minutes(3))

    assert len(runs) == 1
    assert (first.state, second.state, second.reason) == ("held", "held", "quota spent")


def test_the_file_is_written_whole_through_the_atomic_writer_under_a_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    locked: list[Path] = []
    writes: list[tuple[Path, bool]] = []
    real_lock = usage_guard.file_lock

    @contextmanager
    def lock(path: Path) -> Iterator[None]:
        with real_lock(path):
            locked.append(path)
            yield
            locked.pop()

    def write(path: Path, text: str) -> None:
        writes.append((path, bool(locked)))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    monkeypatch.setattr(usage_guard, "file_lock", lock)
    monkeypatch.setattr(usage_guard, "atomic_write_text", write)

    evaluate(tmp_path, Provider("100"))

    assert writes == [(tmp_path / "gate-usage.json", True)]
    assert "acp" in json.loads((tmp_path / "gate-usage.json").read_text())


@pytest.mark.parametrize("damage", [None, "", "{not json", "[1, 2]", '{"acp": "x"}'])
def test_a_corrupt_or_missing_cache_file_reads_as_no_reading(
    tmp_path: Path, damage: str | None
) -> None:
    if damage is not None:
        (tmp_path / "gate-usage.json").write_text(damage)
    provider = Provider("100")

    result = evaluate(tmp_path, provider)

    assert (provider.asked, result.used_pct) == (1, 50)


def test_a_provider_reading_is_not_replayed_to_a_command_gate(tmp_path: Path) -> None:
    evaluate(tmp_path, Provider("100"))
    runs: list[list[str]] = []

    def run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        runs.append(argv)
        return subprocess.CompletedProcess(argv, 3, stdout="quota spent\n", stderr="")

    result = gate_result(
        "acp",
        GateConfig(command=["probe"]),
        now=T0 + minutes(1),
        state_dir=tmp_path,
        root=tmp_path,
        run=run,
    )

    assert (len(runs), result.state, result.reason) == (1, "held", "quota spent")


def test_a_raised_budget_is_judged_afresh_without_a_refresh(tmp_path: Path) -> None:
    spent = "173.04285316"
    first = evaluate(tmp_path, Provider(spent), config=gate(budget=200))
    again = Provider(spent)

    raised = gate_result(
        "acp",
        gate(budget=400),
        now=T0 + minutes(1),
        state_dir=tmp_path,
        root=tmp_path,
        standing=True,
        read=again,
    )

    assert first.used_pct == 87
    assert (again.asked, raised.used_pct, raised.state) == (1, 44, "usable")


def test_a_command_result_is_not_replayed_to_a_provider_gate(tmp_path: Path) -> None:
    def run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    gate_result(
        "acp", GateConfig(command=["probe"]), now=T0, state_dir=tmp_path, root=tmp_path, run=run
    )
    provider = Provider("100")

    result = evaluate(tmp_path, provider, at=T0 + minutes(1))

    assert (provider.asked, result.used_pct) == (1, 50)
