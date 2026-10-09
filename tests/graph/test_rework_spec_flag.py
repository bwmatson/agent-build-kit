"""A review comment that contradicts the unit's change is answered in its own thread with the
flag and not acted on until the reviewer confirms: the rework prompt says so, and the reply
the agent writes goes out through the replies path every rework answer takes.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent_build_kit.forges import PullRequest, RepoId, ReviewNote
from agent_build_kit.graph.state import EventKind, ResumeEvent
from agent_build_kit.pipeline.events import build_fetch_comments
from agent_build_kit.pipeline.pr_replies import build_post_replies, record_given_comments
from agent_build_kit.pipeline.stack_runner import REWORK_CONTINUATION
from tests.forges.stand_in import StandInForge, lookup
from tests.graph_driver import fresh, tick

SLUG = "example/app"
REQUIREMENT = "The registry is written through its journal"
COMMENT = ReviewNote(
    id="n1",
    body="Write the registry file directly, the journal is overkill.",
    path="src/app.py",
    line=3,
    live=True,
)
FLAG = f"Flag: this contradicts the requirement '{REQUIREMENT}'. Not changed until you confirm."


class Host(StandInForge):
    def review_notes(self, repo: RepoId, pr: int) -> list[ReviewNote]:
        return list(self.notes)


def test_a_conflicting_comment_is_flagged_in_its_thread_and_the_prompt_says_to(
    tmp_path: Path,
) -> None:
    recorder = fresh(tmp_path)
    host = Host(
        prs=[PullRequest(number=7, head="spec/add-marker/1", base="main", state="open")],
        existing=7,
    )
    prompts: list[str] = []

    def agent(prompt: str, **kwargs: Any) -> str:
        answer = recorder.claude(prompt, **kwargs)
        if recorder.events[-1] != "claude:rework":
            return answer
        prompts.append(prompt)
        return json.dumps({"replies": [{"comment_id": "n1", "body": FLAG}], "summary": ""})

    overrides: dict[str, Any] = dict(
        run=agent,
        fetch_comments=build_fetch_comments(for_repo=lookup(host), own=lambda repo, pr: set()),
        record_given=lambda repo, pr, ids: record_given_comments(tmp_path, SLUG, pr, ids),
        reply=build_post_replies(root=tmp_path, for_repo=lookup(host), log=recorder.log),
    )
    tick(tmp_path, recorder, **overrides)
    host.notes = [COMMENT]
    event = ResumeEvent(
        kind=EventKind.REWORK,
        reason="comment",
        feedback=f"[comment n1] src/app.py:3 — {COMMENT.body}",
        from_person=True,
        comment_ids=("n1",),
    )

    tick(tmp_path, recorder, event=event, **overrides)
    tick(tmp_path, recorder, **overrides)

    [prompt] = prompts
    lowered = prompt.lower()
    assert "contradict" in lowered, "the prompt names the case"
    assert "flag" in lowered and "thread" in lowered, "answered in its thread with the flag"
    assert "confirm" in lowered, "and left until the reviewer confirms"
    assert [(note_id, REQUIREMENT in body) for note_id, body in host.replies] == [("n1", True)]


def test_a_rework_that_continues_the_session_carries_the_same_instruction() -> None:
    prompt = REWORK_CONTINUATION.format(feedback="[comment n1] x", pr=7, changelog="").lower()

    assert "contradict" in prompt
    assert "flag" in prompt and "thread" in prompt and "confirm" in prompt
