"""Which recorded calls a run counts as replayed, for the rate the acceptance test reports."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.replay.models import Cassette, UpstreamKind
from agent_build_kit.replay.report import Miss, ReplayedTest
from agent_build_kit.replay.store import cassette_name
from tests.replay.support import replayed_cassettes, waiting_cassette

TEST_ID = "tests/x.py::test_it"


def recorded(count: int) -> list[Cassette]:
    return [
        waiting_cassette(
            TEST_ID, index, path=f"/call/{index}", needs_review=False, kind=UpstreamKind.llm
        )
        for index in range(count)
    ]


def test_a_recorded_call_no_call_asked_for_is_not_counted_as_replayed(tmp_path: Path) -> None:
    held = recorded(2)
    test = ReplayedTest(
        test_id=TEST_ID,
        hits=1,
        misses=[Miss(call_index=0, key="live-key", difference="path differs")],
        unused=[cassette_name(tmp_path, held[1])],
    )

    assert replayed_cassettes(held, tmp_path, test) == [held[0]]


def test_a_matching_call_too_old_to_answer_is_not_counted_as_replayed(tmp_path: Path) -> None:
    held = recorded(2)
    test = ReplayedTest(test_id=TEST_ID, hits=1, aged_out=[held[0].key])

    assert replayed_cassettes(held, tmp_path, test) == [held[1]]


def test_every_recorded_call_asked_for_is_counted(tmp_path: Path) -> None:
    held = recorded(3)

    assert replayed_cassettes(held, tmp_path, ReplayedTest(test_id=TEST_ID, hits=3)) == held
