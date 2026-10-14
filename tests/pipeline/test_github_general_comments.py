"""On a host that lists a person's general comment only with the pull request (its conversation),
not among the review notes, the comment still reaches the rework tagged and a reply to it posts
as a comment quoting it, never to the inline-reply call."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_build_kit.forges import PullRequest
from agent_build_kit.pipeline import events
from agent_build_kit.pipeline.pr_replies import build_post_replies
from agent_build_kit.pipeline.unit_store import ReworkKind, UnitStore
from agent_build_kit.pipeline.units import IN_REVIEW
from tests.factories import stored_unit as unit
from tests.forges.stand_in import StandInForge, lookup

UNIT = "add-marker/1"
COMMENT_ID = "IC_kwDOAAAAAc4AAAAB"
BODY = "Please make one_pass the default, and say in the readme why the old default was kept"
PULL = PullRequest(
    number=7,
    head="spec/add-marker/1",
    base="main",
    state="open",
    # Comment ids first, then review ids, as `GitHubForge._view` lists them.
    conversation=(COMMENT_ID, "PRR_1"),
    comment_bodies=(BODY,),
)


@pytest.fixture
def store(tmp_path: Path) -> UnitStore:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit(UNIT)])
    store.set_state(UNIT, IN_REVIEW, pr=7, branch="spec/add-marker/1")
    return store


def test_a_conversation_comment_reaches_every_reader_tagged(store: UnitStore) -> None:
    host = StandInForge(prs=[PULL])
    fetch = events.build_fetch_comments(for_repo=lookup(host))

    found = {c.id: c for c in fetch("example/app", 7, "spec/add-marker/1")}
    events.on_rework(
        7,
        repo="app",
        reason="comment",
        rework=ReworkKind.COMMENT,
        pull=PULL,
        store=store,
        fetch_review=lambda number: events.Review(lines=[], ids=()),
    )

    assert found[COMMENT_ID].words == f"[comment {COMMENT_ID}] {BODY}"
    assert store.get(UNIT).feedback == f"[comment {COMMENT_ID}] {BODY}"


def test_a_reply_to_a_conversation_comment_quotes_it_and_is_not_an_inline_reply(
    tmp_path: Path,
) -> None:
    host = StandInForge(prs=[PULL], notes=[])
    answer = json.dumps({"replies": [{"comment_id": COMMENT_ID, "body": "Done."}], "summary": ""})

    build_post_replies(root=tmp_path, for_repo=lookup(host), log=lambda line: None)(
        repo="app", pr=7, answer_text=answer, sha="0123456789abcdef"
    )

    assert host.replies == []
    [comment] = host.comments
    assert comment.startswith(f"Re: {BODY[:60]}")
    assert "Done." in comment
