"""Which recorded cassettes a live call replaced, for the supersede check of the acceptance.

The report comes out of a real run of the proxy, in which a superseded cassette is marked
`needs_review` and is not listed as unused."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.replay.models import Cassette
from agent_build_kit.replay.report import ReplayedTest
from agent_build_kit.replay.store import cassette_name, read_cassettes
from tests.replay.fake_upstream import FakeUpstream
from tests.replay.support import replaced_cassettes
from tests.replay.test_replay_report import replayed_second_run


def second_run(
    upstream: FakeUpstream, tmp_path: Path
) -> tuple[list[Cassette], ReplayedTest, list[Cassette]]:
    """The cassettes before the run, its report, and the cassettes the run left."""
    before, proxy = replayed_second_run(upstream, tmp_path)
    [test] = proxy.report().tests
    return before, test, read_cassettes(tmp_path / "cassettes")


def live_at(after: list[Cassette], before: list[Cassette], index: int) -> Cassette:
    """The cassette the run's live call at `index` wrote."""
    old = {c.key for c in before}
    return next(c for c in after if c.call_index == index and c.key not in old)


def test_the_cassette_a_live_call_superseded_is_returned_though_the_report_lists_it_as_used_up(
    upstream: FakeUpstream, tmp_path: Path
) -> None:
    before, test, after = second_run(upstream, tmp_path)
    superseded = next(c for c in before if c.call_index == 0)

    found = replaced_cassettes(before, test, live_at(after, before, 0))

    assert found == [superseded]
    # The real run marks it superseded, and so does not list it as unused.
    marked = next(c for c in after if c.key == superseded.key)
    assert marked.review_reason.startswith("superseded by a live call")
    assert cassette_name(tmp_path / "cassettes", superseded) not in test.unused
    assert superseded.key not in test.asked


def test_a_cassette_at_another_index_is_not_a_replaced_one(
    upstream: FakeUpstream, tmp_path: Path
) -> None:
    before, test, after = second_run(upstream, tmp_path)

    found = replaced_cassettes(before, test, live_at(after, before, 0))

    assert [c.call_index for c in found] == [0]


def test_a_cassette_of_another_upstream_at_the_same_index_is_not_a_replaced_one(
    upstream: FakeUpstream, tmp_path: Path
) -> None:
    before, test, after = second_run(upstream, tmp_path)
    other = next(c for c in before if c.call_index == 0).model_copy(
        update={"upstream": "index", "key": "another-upstream-key"}
    )

    found = replaced_cassettes([*before, other], test, live_at(after, before, 0))

    assert other not in found
    assert [c.upstream for c in found] == [before[0].upstream]


def test_a_cassette_a_call_asked_for_is_not_a_replaced_one(
    upstream: FakeUpstream, tmp_path: Path
) -> None:
    before, test, after = second_run(upstream, tmp_path)
    hit = next(c for c in before if c.call_index == 2)
    live = live_at(after, before, 0).model_copy(update={"call_index": 2, "key": "live-key"})

    assert hit.key in test.asked
    assert replaced_cassettes([hit], test, live) == []
