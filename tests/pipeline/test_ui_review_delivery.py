"""A UI review reaches the agent through the pipeline's own fetches, and the agent's replies to
it go back into the UI (spec: ui-review, pr-polling).

The repository, the review store and the unit store are real; the host is a stand-in.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_build_kit.forges import ReviewNote
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.events import build_fetch_comments, build_fetch_review
from agent_build_kit.pipeline.pr_replies import MARKER, build_post_replies
from agent_build_kit.pipeline.ui_review import (
    ui_notes_of,
    ui_reply_writer,
    unit_patch_of,
)
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.serve.review import ReviewStore
from tests.conftest import make_installation
from tests.forges.stand_in import StandInForge, lookup
from tests.review_repo import rev, seed_branches
from tests.serving import seed_pipeline

UNIT = "feature/2"
PR = 12


@pytest.fixture
def inst(tmp_path: Path) -> Installation:
    installation = make_installation(tmp_path / "planning")
    seed_pipeline(installation)
    seed_branches(installation)
    return installation


def reviews(inst: Installation) -> ReviewStore:
    directory = inst.state_dir / "reviews"
    directory.mkdir(parents=True, exist_ok=True)
    return ReviewStore(directory)


def thread_on_line(inst: Installation, line: int, body: str) -> str:
    tip = rev(inst.checkouts["app"], "spec/feature/2")
    return (
        reviews(inst)
        .add_thread(
            UNIT,
            path="two.py",
            side="new",
            line=line,
            start_line=None,
            commit=tip,
            body=body,
        )
        .id
    )


def test_the_review_fetch_holds_host_and_ui_notes_each_with_its_hunk_and_the_summary(
    inst: Installation,
) -> None:
    store = UnitStore(inst.state_dir / "units.json")
    thread = thread_on_line(inst, 3, "why?")
    reviews(inst).decide(UNIT, round=1, decision="request_changes", summary="split this up")
    host = ReviewNote(id="901", body="rename it", path="two.py", line=5)
    fetch = build_fetch_review(
        for_repo=lookup(StandInForge(notes=[host])),
        extra_notes=ui_notes_of(inst, store),
        patch_of=unit_patch_of(inst, store),
    )

    review = fetch("app", PR)

    assert len(review.lines) == 3
    on_host, ui, summary = review.lines
    ui_head, *ui_hunk = ui.splitlines()
    assert ui_head == f"[comment {thread}] two.py:3 — why?"
    assert ui_hunk[0].startswith("@@")
    assert [line for line in ui_hunk if line.endswith("<- comment")] == ["+two line 3  <- comment"]
    host_head, *host_hunk = on_host.splitlines()
    assert host_head == "[comment 901] two.py:5 — rename it"
    assert [line for line in host_hunk if line.endswith("<- comment")] == [
        "+two line 5  <- comment"
    ]
    assert summary == "split this up"
    assert {thread, "901", "ui-decision-1"} <= set(review.ids)


def test_a_pull_request_with_no_ui_review_is_fetched_as_the_host_has_it(
    inst: Installation,
) -> None:
    store = UnitStore(inst.state_dir / "units.json")
    host = ReviewNote(id="901", body="rename it", path="two.py", line=5)
    fetch = build_fetch_review(
        for_repo=lookup(StandInForge(notes=[host])),
        extra_notes=ui_notes_of(inst, store),
        patch_of=unit_patch_of(inst, store),
    )

    (line, *rest) = fetch("app", PR).lines[0].splitlines()

    assert line == "[comment 901] two.py:5 — rename it"
    assert rest, "the host's note carries its hunk too"


def test_a_ui_comment_made_during_a_rework_is_one_the_rework_can_be_checked_against(
    inst: Installation,
) -> None:
    store = UnitStore(inst.state_dir / "units.json")
    thread = thread_on_line(inst, 3, "why?")
    fetch = build_fetch_comments(
        for_repo=lookup(StandInForge()),
        extra_notes=ui_notes_of(inst, store),
        patch_of=unit_patch_of(inst, store),
    )

    found = {c.id: c for c in fetch("app", PR, "spec/feature/2")}

    assert found[thread].words.startswith(f"[comment {thread}] two.py:3 — why?")
    assert not found[thread].own


def test_a_reply_to_a_ui_comment_lands_in_its_thread_and_never_goes_to_the_host(
    inst: Installation,
) -> None:
    store = UnitStore(inst.state_dir / "units.json")
    thread = thread_on_line(inst, 3, "why?")
    forge = StandInForge()
    answer = json.dumps(
        {
            "replies": [
                {"comment_id": thread, "body": "Renamed it"},
                {"comment_id": "901", "body": "Done on the host"},
            ]
        }
    )
    post = build_post_replies(
        root=inst.state_dir,
        for_repo=lookup(forge),
        log=lambda _: None,
        ui_replies=ui_reply_writer(inst.state_dir, store),
    )

    owed = post(repo="app", pr=PR, answer_text=answer, sha="0123456789abcdef")

    (stored,) = reviews(inst).read(UNIT).threads
    assert len(stored.replies) == 1
    assert "Renamed it" in stored.replies[0].body and MARKER in stored.replies[0].body
    assert [note for note, _ in forge.replies] == ["901"]
    assert owed == ""
