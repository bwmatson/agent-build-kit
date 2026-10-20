"""Which recorded cassettes a live call replaced, for the supersede check of the acceptance."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.replay.models import Cassette, UpstreamKind
from agent_build_kit.replay.report import ReplayedTest
from agent_build_kit.replay.store import cassette_name
from tests.replay.support import replaced_cassettes, waiting_cassette

TEST_ID = "tests/x.py::test_it"


def cassette(upstream: str, kind: UpstreamKind, path: str, index: int = 10) -> Cassette:
    return waiting_cassette(TEST_ID, index, path=path, needs_review=False, kind=kind).model_copy(
        update={"upstream": upstream}
    )


def test_a_cassette_of_another_upstream_at_the_same_index_is_not_a_replaced_one(
    tmp_path: Path,
) -> None:
    old_model = cassette("model", UpstreamKind.llm, "/v1/messages")
    index_call = cassette("index", UpstreamKind.deterministic, "/pytest/")
    live = cassette("model", UpstreamKind.llm, "/v1/messages?other")
    # The index call was asked again and replayed; only the old model call was left unused.
    unused = [cassette_name(tmp_path, old_model)]
    test = ReplayedTest(test_id=TEST_ID, unused=unused)

    assert replaced_cassettes([old_model, index_call], tmp_path, test, live) == [old_model]


def test_an_unused_cassette_of_another_upstream_at_the_same_index_is_not_a_replaced_one(
    tmp_path: Path,
) -> None:
    unused_index_call = cassette("index", UpstreamKind.deterministic, "/pytest/")
    live = cassette("model", UpstreamKind.llm, "/v1/messages")
    test = ReplayedTest(test_id=TEST_ID, unused=[cassette_name(tmp_path, unused_index_call)])

    assert replaced_cassettes([unused_index_call], tmp_path, test, live) == []


def test_a_cassette_of_the_same_upstream_that_a_call_asked_for_is_not_a_replaced_one(
    tmp_path: Path,
) -> None:
    asked = cassette("model", UpstreamKind.llm, "/v1/messages")
    live = cassette("model", UpstreamKind.llm, "/v1/messages?other")

    assert replaced_cassettes([asked], tmp_path, ReplayedTest(test_id=TEST_ID), live) == []


def test_a_cassette_at_another_index_is_not_a_replaced_one(tmp_path: Path) -> None:
    elsewhere = cassette("model", UpstreamKind.llm, "/v1/messages", index=3)
    live = cassette("model", UpstreamKind.llm, "/v1/messages?other")
    test = ReplayedTest(test_id=TEST_ID, unused=[cassette_name(tmp_path, elsewhere)])

    assert replaced_cassettes([elsewhere], tmp_path, test, live) == []
