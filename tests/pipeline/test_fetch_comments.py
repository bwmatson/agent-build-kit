"""`build_fetch_comments` reads a pull request the way the host builds it: the conversation
lists comment ids then review ids, and only the comments carry bodies."""

from __future__ import annotations

from agent_build_kit.forges import PullRequest, ReviewNote
from agent_build_kit.pipeline.events import build_fetch_comments, note_words, review_lines
from agent_build_kit.pipeline.pr_replies import MARKER
from tests.forges.stand_in import StandInForge, lookup


def test_conversation_comments_carry_their_bodies_and_reviews_carry_none() -> None:
    forge = StandInForge(
        prs=[
            PullRequest(
                number=7,
                head="spec/add-marker/1",
                base="main",
                state="open",
                # Comment ids first, then review ids, as `GitHubForge._view` lists them.
                conversation=("c1", "c2", "c3", "rv1", "rv2"),
                comment_bodies=("please add a docstring", f"done\n{MARKER}", "posted by us"),
            )
        ],
        notes=[ReviewNote(id="n1", body="remove this line", path="src/app.py", line=3)],
    )
    fetch = build_fetch_comments(for_repo=lookup(forge), own=lambda repo, pr: {"c3"})

    found = {c.id: c for c in fetch("example/app", 7, "spec/add-marker/1")}

    assert found["c1"].words == "please add a docstring"
    assert not found["c1"].own
    assert found["c2"].own, "a body carrying the marker is the pipeline's"
    assert found["c3"].own, "an id the pipeline recorded is the pipeline's"
    assert found["rv1"].words == "" and found["rv2"].words == ""
    assert found["n1"].words == "[comment n1] src/app.py:3 — remove this line"
    assert not found["n1"].own


def test_a_note_reads_the_same_whichever_way_it_reaches_the_agent() -> None:
    anchored = ReviewNote(id="n1", body="rename it", path="src/app.py", line=9)
    unanchored = ReviewNote(id="n2", body="overall: split this up")
    pathless = ReviewNote(id="n3", body="here", line=4)
    notes = [anchored, unanchored, pathless]

    assert review_lines(notes) == [note_words(n) for n in notes]
    assert note_words(unanchored) == "overall: split this up"
    assert note_words(pathless) == "[comment n3] ?:4 — here"
