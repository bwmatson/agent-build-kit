"""A review comment that contradicts a requirement of the unit's change is flagged in its
thread and not acted on (spec: ui-review). The review store, the repository and the posting
path are real; the rework agent is a stand-in that answers as the prompt asks."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.events import build_fetch_review
from agent_build_kit.pipeline.pr_replies import MARKER, build_post_replies
from agent_build_kit.pipeline.stack_runner import REWORK_PROMPT
from agent_build_kit.pipeline.ui_review import ui_notes_of, ui_reply_writer, unit_patch_of
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.serve.review import ReviewStore
from tests.conftest import make_installation
from tests.factories import git
from tests.forges.stand_in import StandInForge, lookup
from tests.review_repo import rev, seed_branches
from tests.serving import seed_pipeline

UNIT = "feature/2"
PR = 12
REQUIREMENT = "Approve SHALL record the approval without merging anything"
CONTRADICTION = "Approve should merge the pull request too"


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


def comment_thread(inst: Installation) -> str:
    tip = rev(inst.checkouts["app"], "spec/feature/2")
    return (
        reviews(inst)
        .add_thread(
            UNIT,
            path="two.py",
            side="new",
            line=3,
            start_line=None,
            commit=tip,
            body=CONTRADICTION,
        )
        .id
    )


def rework_prompt(inst: Installation) -> str:
    store = UnitStore(inst.state_dir / "units.json")
    fetch = build_fetch_review(
        for_repo=lookup(StandInForge()),
        extra_notes=ui_notes_of(inst, store),
        patch_of=unit_patch_of(inst, store),
    )
    feedback = "\n".join(fetch("app", PR).lines)
    return REWORK_PROMPT.format(
        groups="1",
        change_dir="/planning/openspec/changes/feature",
        feedback=feedback,
        pr=PR,
        boundary="",
        changelog="",
    )


def test_the_rework_is_given_the_comment_and_told_to_flag_a_contradiction_not_act_on_it(
    inst: Installation,
) -> None:
    thread = comment_thread(inst)

    prompt = rework_prompt(inst)

    assert f"[comment {thread}] two.py:3 — {CONTRADICTION}" in prompt
    assert "contradicts a requirement of this change is not acted on" in prompt
    assert "in your reply to that comment's thread" in prompt


def test_the_flag_the_agent_replies_with_is_written_into_the_thread_it_answers(
    inst: Installation,
) -> None:
    thread = comment_thread(inst)
    store = UnitStore(inst.state_dir / "units.json")
    flag = f"This contradicts the requirement that {REQUIREMENT}; left as it is."
    answer = json.dumps({"replies": [{"comment_id": thread, "body": flag}], "summary": ""})
    forge = StandInForge()
    post = build_post_replies(
        root=inst.state_dir,
        for_repo=lookup(forge),
        log=lambda _: None,
        ui_replies=ui_reply_writer(inst.state_dir, store),
    )
    repo = inst.checkouts["app"]
    before = git(repo, "rev-parse", "spec/feature/2").strip()

    post(repo="app", pr=PR, answer_text=answer, sha="0123456789abcdef")

    (stored,) = reviews(inst).read(UNIT).threads
    assert len(stored.replies) == 1
    assert REQUIREMENT in stored.replies[0].body and MARKER in stored.replies[0].body
    assert not stored.resolved, "left for the reviewer to confirm"
    assert forge.replies == [], "nothing reaches the host"
    assert git(repo, "rev-parse", "spec/feature/2").strip() == before, "the branch is unchanged"
