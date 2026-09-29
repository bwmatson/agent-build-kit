"""A policy check is asked at most once a short while.

A runtime whose agent runs its own tools answers `check_policy` with a probe
run, which is an agent call; `doctor` and `init` ask it every time they run.
So an answer is kept and reused while fresh, re-asked once it is not, and
re-asked on demand by a caller that has just changed what it depends on.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from agent_build_kit.runtimes import PolicyReport
from agent_build_kit.runtimes.policy_check import MAX_AGE, checked
from tests.runtimes.selectable import SelectableRuntime

NOW = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)

UNENFORCED = PolicyReport(
    ok=False, unenforced=("merging a pull request", "pushing to a default branch")
)


def probed(*reports: PolicyReport, name: str = "probed") -> SelectableRuntime:
    return SelectableRuntime(name, policy_coverage="agent_flagged", reports=reports)


def test_the_first_check_asks_the_runtime(tmp_path: Path) -> None:
    runtime = probed(UNENFORCED)

    report = checked(runtime, tmp_path, cache=tmp_path / "policy.json", now=NOW)

    assert report == UNENFORCED
    assert runtime.checked == [tmp_path]


def test_an_answer_is_reused_within_the_window(tmp_path: Path) -> None:
    runtime = probed(UNENFORCED, PolicyReport(ok=True))
    cache = tmp_path / "policy.json"

    checked(runtime, tmp_path, cache=cache, now=NOW)
    again = checked(runtime, tmp_path, cache=cache, now=NOW + MAX_AGE / 2)

    assert again == UNENFORCED
    assert len(runtime.checked) == 1


def test_an_answer_is_reused_by_a_later_process(tmp_path: Path) -> None:
    """Kept in the file, not in memory: each `abk doctor` is its own process."""
    cache = tmp_path / "policy.json"
    checked(probed(UNENFORCED), tmp_path, cache=cache, now=NOW)
    later = probed(PolicyReport(ok=True))

    assert checked(later, tmp_path, cache=cache, now=NOW + MAX_AGE / 2) == UNENFORCED
    assert later.checked == []


def test_an_answer_older_than_the_window_is_asked_again(tmp_path: Path) -> None:
    runtime = probed(UNENFORCED, PolicyReport(ok=True))
    cache = tmp_path / "policy.json"

    checked(runtime, tmp_path, cache=cache, now=NOW)
    again = checked(runtime, tmp_path, cache=cache, now=NOW + MAX_AGE * 2)

    assert again == PolicyReport(ok=True)
    assert len(runtime.checked) == 2


def test_a_fresh_check_asks_again_and_is_what_is_reused_after(tmp_path: Path) -> None:
    runtime = probed(UNENFORCED, PolicyReport(ok=True))
    cache = tmp_path / "policy.json"
    checked(runtime, tmp_path, cache=cache, now=NOW)

    fresh = checked(runtime, tmp_path, cache=cache, now=NOW, fresh=True)
    after = checked(runtime, tmp_path, cache=cache, now=NOW + MAX_AGE / 2)

    assert fresh == after == PolicyReport(ok=True)
    assert len(runtime.checked) == 2


def test_one_runtime_s_answer_is_not_another_s(tmp_path: Path) -> None:
    cache = tmp_path / "policy.json"
    checked(probed(UNENFORCED, name="first"), tmp_path, cache=cache, now=NOW)
    second = probed(PolicyReport(ok=True), name="second")

    assert checked(second, tmp_path, cache=cache, now=NOW) == PolicyReport(ok=True)
    assert second.checked == [tmp_path]


def test_an_unreadable_cache_is_asked_again(tmp_path: Path) -> None:
    cache = tmp_path / "policy.json"
    cache.write_text("{not json")
    runtime = probed(UNENFORCED)

    assert checked(runtime, tmp_path, cache=cache, now=NOW) == UNENFORCED
    assert len(runtime.checked) == 1


def test_the_cache_directory_is_made_when_missing(tmp_path: Path) -> None:
    cache = tmp_path / "runs" / "policy.json"
    runtime = probed(UNENFORCED)

    checked(runtime, tmp_path, cache=cache, now=NOW)

    assert cache.is_file()
