"""What a run says it replayed and what went live, which recordings it holds for review,
and the state it keeps outside the committed files."""

import json
from datetime import timedelta
from pathlib import Path

from agent_build_kit.pipeline.shell import git
from agent_build_kit.replay import review
from agent_build_kit.replay.models import ReplayMode
from agent_build_kit.replay.report import Miss, ReplayedTest, RunReport, render, replay_label
from agent_build_kit.replay.state import STATE_FILE, ReplayState, read_state, write_state
from agent_build_kit.replay.store import cassette_name, load_cassette, read_cassettes
from tests.factories import init_repo
from tests.replay.fake_upstream import Answer, FakeUpstream, Seen
from tests.replay.support import START, files, send
from tests.replay.test_replay_modes import TEST, passing_run, proxy_for, recorded
from tests.replay.test_replay_recording import PREFIXES, VOLATILE, body_in


def conversation(system: str, text: str = "hi") -> dict:
    payload = {"model": "m-1", "system": system, "messages": [{"role": "user", "content": text}]}
    return {"body": json.dumps(payload).encode()}


FIRST = [
    conversation("be brief"),
    {"path": "/v1/models", "body": b"{}"},
    {"path": "/v1/files", "body": b"{}"},
    {"path": "/v1/extra", "body": b"{}"},
]
# The same test run again: call 0's system prompt, call 1's path and call 3 (not made) differ.
SECOND = [conversation("be verbose"), {"path": "/v1/tags", "body": b"{}"}, FIRST[2]]


def replayed_second_run(upstream: FakeUpstream, tmp_path: Path):
    recorded(upstream, tmp_path, *FIRST)
    before = read_cassettes(tmp_path / "cassettes")
    with proxy_for(upstream, tmp_path, ReplayMode.replay) as proxy:
        passing_run(proxy, *SECOND)
    return before, proxy


def test_the_report_lists_the_hits_and_the_misses_with_where_each_differs(
    upstream: FakeUpstream, tmp_path: Path
) -> None:
    _, proxy = replayed_second_run(upstream, tmp_path)

    [test] = proxy.report().tests
    assert test.test_id == TEST
    assert test.hits == 1
    by_index = {miss.call_index: miss for miss in test.misses}
    assert sorted(by_index) == [0, 1]
    assert "system" in by_index[0].difference
    assert "path" in by_index[1].difference
    assert by_index[0].key != by_index[1].key


def test_the_report_lists_the_cassette_no_call_asked_for(
    upstream: FakeUpstream, tmp_path: Path
) -> None:
    before, proxy = replayed_second_run(upstream, tmp_path)

    [test] = proxy.report().tests
    unasked = next(c for c in before if c.call_index == 3)
    assert test.unused == [cassette_name(tmp_path / "cassettes", unasked)]


def test_the_report_lists_a_cassette_too_old_to_answer(
    upstream: FakeUpstream, tmp_path: Path
) -> None:
    recorded(upstream, tmp_path, FIRST[0], max_age_days=30)
    [old] = read_cassettes(tmp_path / "cassettes")

    later = START + timedelta(days=31)
    with proxy_for(upstream, tmp_path, ReplayMode.replay, clock=lambda: later) as proxy:
        passing_run(proxy, FIRST[0])

    [test] = proxy.report().tests
    assert test.aged_out == [old.key]
    assert test.hits == 0
    assert len(upstream.seen) == 2


def test_the_report_lists_the_declared_rules_that_applied(
    upstream: FakeUpstream, tmp_path: Path
) -> None:
    with proxy_for(upstream, tmp_path, ReplayMode.record) as proxy:
        proxy.begin(TEST, [VOLATILE])
        send(proxy, body=body_in(PREFIXES[0]))
        proxy.finish(passed=True)
    with proxy_for(upstream, tmp_path, ReplayMode.replay) as proxy:
        proxy.begin(TEST, [VOLATILE])
        send(proxy, body=body_in(PREFIXES[1]))
        proxy.finish(passed=True)

    report = proxy.report()
    assert report.rules == [VOLATILE]
    assert report.tests[0].rules == [VOLATILE]


def test_an_unused_cassette_and_a_superseded_one_are_marked_and_not_deleted(
    upstream: FakeUpstream, tmp_path: Path
) -> None:
    before, _ = replayed_second_run(upstream, tmp_path)

    stored = read_cassettes(tmp_path / "cassettes")
    by_key = {cassette.key: cassette for cassette in stored}
    old = {cassette.call_index: cassette.key for cassette in before}
    assert all(key in by_key for key in old.values()), "nothing was deleted"
    assert len(files(tmp_path / "cassettes")) == 6
    for superseded_or_unused in (0, 1, 3):
        marked = by_key[old[superseded_or_unused]]
        assert marked.needs_review
        assert marked.review_reason
    assert not by_key[old[2]].needs_review
    new = [c for c in stored if c.key not in old.values()]
    assert [(c.call_index, c.needs_review) for c in new] == [(0, False), (1, False)]


def test_a_failed_test_marks_nothing(upstream: FakeUpstream, tmp_path: Path) -> None:
    recorded(upstream, tmp_path, *FIRST)
    with proxy_for(upstream, tmp_path, ReplayMode.replay) as proxy:
        proxy.begin(TEST)
        send(proxy, path="/v1/tags", body=b"{}")
        proxy.finish(passed=False)

    assert not any(c.needs_review for c in read_cassettes(tmp_path / "cassettes"))


def usage_answer(seen: Seen) -> Answer:
    figures = {"input_tokens": 10, "output_tokens": 5}
    if b"heavy" in seen.body:
        figures = {"input_tokens": 20, "output_tokens": 30}
    payload: dict[str, object] = {"id": "msg_1", "content": []}
    if b"unmetered" not in seen.body:
        payload["usage"] = figures
    return Answer(chunks=[json.dumps(payload).encode()])


def test_billed_calls_avoided_are_totalled_from_the_recorded_usage_figures(
    tmp_path: Path,
) -> None:
    calls = [{"body": b"light"}, {"body": b"heavy"}, {"body": b"unmetered"}]
    with FakeUpstream(usage_answer) as upstream:
        recorded(upstream, tmp_path, *calls)
        with proxy_for(upstream, tmp_path, ReplayMode.replay) as proxy:
            passing_run(proxy, *calls, {"body": b"new and live"})

    report = proxy.report()
    assert report.tests[0].hits == 3
    # The response without figures adds nothing, and neither does the call that went live.
    assert report.billed_calls_avoided == 2
    assert report.tokens_avoided == 65


def streamed_answer(seen: Seen) -> Answer:
    def event(name: str, data: dict) -> bytes:
        return f"event: {name}\ndata: {json.dumps(data)}\n\n".encode()

    start = {
        "type": "message_start",
        "message": {"usage": {"input_tokens": 25, "output_tokens": 1}},
    }
    delta = {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "hi"}}
    final = {"type": "message_delta", "usage": {"output_tokens": 15}}
    return Answer(
        headers={"content-type": "text/event-stream"},
        chunks=[
            event("message_start", start),
            event("content_block_delta", delta),
            event("message_delta", final),
            event("message_stop", {"type": "message_stop"}),
        ],
    )


def test_a_streamed_response_totals_the_usage_of_its_start_and_its_final_delta(
    tmp_path: Path,
) -> None:
    with FakeUpstream(streamed_answer) as upstream:
        recorded(upstream, tmp_path, {"body": b"stream"})
        with proxy_for(upstream, tmp_path, ReplayMode.replay) as proxy:
            passing_run(proxy, {"body": b"stream"})

    report = proxy.report()
    assert report.tests[0].hits == 1
    assert report.billed_calls_avoided == 1
    assert report.tokens_avoided == 40


def test_a_run_that_replayed_nothing_avoided_nothing(tmp_path: Path) -> None:
    with FakeUpstream(usage_answer) as upstream:
        with proxy_for(upstream, tmp_path, ReplayMode.record) as proxy:
            passing_run(proxy, {"body": b"light"})

    assert proxy.report().billed_calls_avoided == 0
    assert proxy.report().tokens_avoided == 0


def test_the_label_gives_the_counts_and_is_absent_when_nothing_replayed() -> None:
    miss = Miss(call_index=2, key="k", difference="path differs")
    label = replay_label(ReplayedTest(test_id=TEST, hits=2, misses=[miss]))

    assert label is not None
    assert "replayed" in label
    assert "2 of 3" in label
    assert "1 live" in label
    assert replay_label(ReplayedTest(test_id=TEST, hits=0, misses=[miss])) is None


def test_using_a_cassette_changes_the_state_file_and_not_the_committed_one(
    upstream: FakeUpstream, tmp_path: Path
) -> None:
    repo = init_repo(tmp_path / "repo")
    directory = repo / "cassettes"
    recorded(upstream, repo, FIRST[0])
    before = {path: path.read_bytes() for path in files(directory)}
    [held] = read_cassettes(directory)
    assert read_state(directory).last_hit_at == {}

    later = START + timedelta(days=3)
    with proxy_for(upstream, repo, ReplayMode.replay, clock=lambda: later) as proxy:
        passing_run(proxy, FIRST[0])

    assert {path: path.read_bytes() for path in files(directory)} == before
    assert read_state(directory).last_hit_at == {cassette_name(directory, held): later}
    assert git(repo, "check-ignore", "-q", str(directory / STATE_FILE), check=False).returncode == 0
    [cassette_file] = files(directory)
    assert git(repo, "check-ignore", "-q", str(cassette_file), check=False).returncode == 1


def test_the_total_adds_up_the_hits_live_unused_and_aged_out_calls_of_every_test() -> None:
    miss = Miss(call_index=1, key="k", difference="path differs")
    report = RunReport(
        tests=[
            ReplayedTest(test_id="a", hits=2, misses=[miss], unused=["x/1.json.gz"]),
            ReplayedTest(test_id="b", hits=1, misses=[miss, miss], aged_out=["k1", "k2"]),
        ],
        rules=[VOLATILE],
    )

    lines = render(report)

    assert "total: 3 hit, 3 live, 1 unused, 2 aged out" in lines
    assert any(VOLATILE.placeholder in line for line in lines if line.startswith("rule used"))


def test_a_marked_cassette_a_later_run_hits_is_cleared_and_no_longer_counted(
    upstream: FakeUpstream, tmp_path: Path
) -> None:
    replayed_second_run(upstream, tmp_path)
    directory = tmp_path / "cassettes"
    [unasked] = [h for h in review.waiting(directory) if h.cassette.call_index == 3]
    write_state(directory, ReplayState(unreviewed_runs={unasked.name: 4}))

    with proxy_for(upstream, tmp_path, ReplayMode.replay) as proxy:
        passing_run(proxy, *FIRST)

    assert unasked.name not in [h.name for h in review.waiting(directory)]
    assert unasked.name not in read_state(directory).unreviewed_runs
    assert not load_cassette(directory / unasked.name).needs_review
    assert load_cassette(directory / unasked.name).review_reason == ""


def test_a_cassette_already_marked_is_still_reported_unused_with_its_reason_kept(
    upstream: FakeUpstream, tmp_path: Path
) -> None:
    _, first = replayed_second_run(upstream, tmp_path)
    directory = tmp_path / "cassettes"
    [marked] = [h for h in review.waiting(directory) if h.cassette.call_index == 3]
    reason = marked.cassette.review_reason

    with proxy_for(upstream, tmp_path, ReplayMode.replay) as proxy:
        passing_run(proxy, *SECOND)

    [test] = proxy.report().tests
    assert test.unused == [marked.name]
    assert load_cassette(directory / marked.name).review_reason == reason
