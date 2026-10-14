"""A rework that made no commit and answered no comment posts nothing to the pull request; its
summary goes to the run log. One that changed code posts its summary as before."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent_build_kit.forges import PullRequest, RepoId, ReviewNote
from agent_build_kit.graph.state import EventKind, ResumeEvent
from agent_build_kit.pipeline.events import build_fetch_comments
from agent_build_kit.pipeline.pr_replies import build_post_replies, record_given_comments
from tests.forges.stand_in import StandInForge, lookup
from tests.graph_driver import fresh, tick

SLUG = "example/app"
SUMMARY = "rebased, no changes"
COMMENT = ReviewNote(id="n1", body="Rebase it please.", path="src/app.py", line=3, live=True)


class Host(StandInForge):
    def review_notes(self, repo: RepoId, pr: int) -> list[ReviewNote]:
        return list(self.notes)


def rework(tmp_path: Path, *, commits: bool) -> tuple[Host, list[str]]:
    """A rework of one comment whose agent answers with no replies and `SUMMARY`: the host, and
    what the run logged."""
    tmp_path.mkdir(parents=True)
    recorder = fresh(tmp_path)
    host = Host(
        prs=[PullRequest(number=7, head="spec/add-marker/1", base="main", state="open")],
        existing=7,
    )

    def agent(prompt: str, **kwargs: Any) -> str:
        answer = recorder.claude(prompt, **kwargs)
        if recorder.events[-1] != "claude:rework":
            return answer
        return json.dumps({"replies": [], "summary": SUMMARY})

    def commit(message: str, **kwargs: Any) -> int:
        # A rework's own commit is the one titled `fix:`; without it the agent changed nothing.
        if message.startswith("fix:") and not commits:
            return 0
        return recorder.commit(message, **kwargs)

    overrides: dict[str, Any] = dict(
        run=agent,
        commit=commit,
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
    return host, recorder.logged


def test_a_rework_with_no_commit_and_no_replies_is_silent_and_one_that_committed_posts(
    tmp_path: Path,
) -> None:
    silent, logged = rework(tmp_path / "silent", commits=False)

    assert silent.comments == [] and silent.replies == []
    assert any(SUMMARY in line for line in logged), "the summary is in the run log"

    committed, _ = rework(tmp_path / "committed", commits=True)

    assert [SUMMARY in comment for comment in committed.comments] == [True]
