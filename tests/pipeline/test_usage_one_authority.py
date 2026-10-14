"""The usage module is the only authority on whether to call the endpoint, and on what a
reading may be used for (spec: usage-pause).

One process refreshes at the expiry of the cached reading, however many threads and
processes ask; a reading is not used past the reset of a window it describes, whichever
source it came from; the cache counts its hits, misses, expiries and waits. Only the
endpoint and the home directory are faked (`tests/usage_host.py`), so the real cache file
and its lock are what the askers contend for.
"""

import multiprocessing
import threading
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path

import pytest

from agent_build_kit import telemetry
from agent_build_kit.pipeline.file_lock import try_file_lock
from agent_build_kit.pipeline.usage_guard import current_usage, held_usage, read_live_usage
from agent_build_kit.pipeline.wiring import build_usage_gate
from tests.otlp import Collector, enabled
from tests.usage_asker import asking_in_a_process, slow_urlopen
from tests.usage_host import Host, configure, pause_at, payload

# Long enough for every asker to arrive while the one that refreshes is still calling.
CALL_SECONDS = 0.4
ASKERS = 4
# What the endpoint answers the one asker that calls it.
ANSWER = {"session": 33.0}


def slow_endpoint(monkeypatch: pytest.MonkeyPatch, calls: Path, **answer: float) -> None:
    """The endpoint answers after a while, and every call made to it, in any process, is
    written to `calls`."""

    monkeypatch.setattr("urllib.request.urlopen", slow_urlopen(calls, answer, CALL_SECONDS))


def calls_made(calls: Path) -> int:
    return len(calls.read_text().splitlines()) if calls.exists() else 0


# --- one process refreshes ---------------------------------------------------------------


def test_several_threads_at_expiry_make_one_call_and_the_rest_are_served_the_last_good(
    host: Host, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls = tmp_path / "calls"
    host.keep_reading(timedelta(minutes=20), payload(session=14.0))
    slow_endpoint(monkeypatch, calls, **ANSWER)
    arrived = threading.Barrier(ASKERS)
    answers: list = []

    def ask() -> None:
        arrived.wait()
        answers.append(read_live_usage())

    threads = [threading.Thread(target=ask) for _ in range(ASKERS)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert calls_made(calls) == 1
    served = [(r.source, r.session_pct) for r in answers if r is not None]
    assert len(served) == ASKERS
    assert served.count(("live", 33)) == 1
    # A loser that came after the winner had written the file reads the fresh reading.
    assert {source for source, _ in served if source != "live"} <= {"cache"}
    assert {session for _, session in served} <= {14, 33}


def test_an_asker_that_finds_the_lock_held_is_served_a_kept_reading_older_than_the_fallback_age(
    host: Host, exported: Collector
) -> None:
    """The cache time has stretched past the fallback age, so the reading kept at expiry
    can be older than it; the holder is calling, so the waiter is served it all the same."""
    configure(usage_cache_minutes=40)
    host.keep_reading(timedelta(minutes=35), payload(session=14.0))

    with try_file_lock(host.cache.with_name(host.cache.name + ".lock")) as taken:
        assert taken
        reading = read_live_usage(ttl=timedelta(minutes=30))

    assert reading is not None
    assert (reading.source, reading.session_pct) == ("cache", 14)
    assert host.asked == 0
    assert cache_events(exported).get("wait") == 1


def test_twenty_asks_from_several_processes_make_one_call(host: Host, tmp_path: Path) -> None:
    calls = tmp_path / "calls"
    host.keep_reading(timedelta(minutes=20), payload(session=14.0))
    parked = threading.Event()
    keeper = threading.Thread(target=parked.wait, daemon=True)
    keeper.start()  # a thread alive, as the runner's are: a fork now warns on any machine
    context = multiprocessing.get_context("spawn")
    results = context.Queue()
    processes = [
        context.Process(
            target=asking_in_a_process,
            args=(5, results, host.home, calls, ANSWER, CALL_SECONDS),
        )
        for _ in range(ASKERS)
    ]
    try:
        for process in processes:
            process.start()
        answers = [results.get(timeout=30) for _ in range(20)]
    finally:
        for process in processes:
            process.join(timeout=30)
            if process.is_alive():
                process.terminate()
                process.join()
        parked.set()
        keeper.join()

    assert calls_made(calls) == 1
    assert None not in answers
    assert ("live", 33) in answers
    assert {session for _, session in answers} <= {14, 33}


# --- a reading is not used past its window -----------------------------------------------


def test_neither_the_kept_reading_nor_the_editors_is_used_past_the_reset_of_its_window(
    host: Host,
) -> None:
    """The live call keeps failing. Both fallbacks were taken before the session window
    reset, ten minutes ago, and describe a window that no longer exists."""
    reset = timedelta(minutes=-10)
    host.keep_reading(timedelta(minutes=20), payload(session=90.0, session_resets_in=reset))
    host.keep_editor_reading(timedelta(minutes=20), session=90, resets_in=reset)

    assert current_usage() is None


def test_the_held_reading_is_not_the_cache_files_past_the_reset_of_its_window(host: Host) -> None:
    host.keep_reading(
        timedelta(minutes=20), payload(session=90.0, session_resets_in=timedelta(minutes=-10))
    )
    assert held_usage() is None

    host.keep_editor_reading(timedelta(minutes=5), session=20)

    reading = held_usage()
    assert reading is not None
    assert (reading.source, reading.session_pct) == ("claude.json", 20)


# --- a running step is not judged by the threshold ---------------------------------------


def test_a_start_allowed_under_the_threshold_is_followed_by_a_refusal_once_over(
    host: Host,
) -> None:
    """The threshold is applied when a start is asked for: the first start went ahead on
    the reading under it and nothing asks again while it runs; the gate that is asked next
    refuses on the new reading."""
    configure(**pause_at(70))
    host.keep_reading(timedelta(minutes=2), payload(session=66.0))
    may_start, _ = build_usage_gate()
    first, _ = may_start()

    host.keep_reading(timedelta(minutes=20), payload(session=66.0))
    host.answers = [payload(session=95.0)]
    may_start, _ = build_usage_gate()
    next_start, why = may_start()

    assert first
    assert not next_start
    assert "95%" in why


# --- the cache is counted ----------------------------------------------------------------


@pytest.fixture
def exported() -> Iterator[Collector]:
    with enabled() as collector:
        assert telemetry.init() is True
        yield collector


def cache_events(collector: Collector) -> dict[str, float]:
    telemetry.shutdown()
    return {p.attributes["event"]: p.value for p in collector.metric("abk.usage.cache")}


def test_a_hit_then_an_expiry_and_a_miss_are_counted_and_the_call_record_is_unchanged(
    host: Host, exported: Collector
) -> None:
    host.keep_reading(timedelta(minutes=2))
    read_live_usage()
    host.keep_reading(timedelta(minutes=20))
    host.answers = [payload()]
    read_live_usage()

    assert cache_events(exported) == {"hit": 1, "expiry": 1, "miss": 1}
    calls = {
        (p.attributes["outcome"], p.attributes["caller"]): p.value
        for p in exported.metric("abk.usage.calls")
    }
    assert calls == {("cache", "guard"): 1, ("ok", "guard"): 1}
    assert [line["outcome"] for line in host.lines()] == ["cache", "ok"]


def test_a_wait_on_the_refresh_lock_is_counted(
    host: Host, exported: Collector, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    host.keep_reading(timedelta(minutes=20))
    slow_endpoint(monkeypatch, tmp_path / "calls")
    arrived = threading.Barrier(2)

    def ask() -> None:
        arrived.wait()
        read_live_usage()

    threads = [threading.Thread(target=ask) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert cache_events(exported).get("wait") == 1
