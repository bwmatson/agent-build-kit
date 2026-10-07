"""A rework asks the host again for the reviewer's words just before it pushes, and
addresses any person's comment it was not given, in the same push."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Collection
from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.forges import PullRequest, RepoId, ReviewNote
from agent_build_kit.graph.checkpointer import open_checkpointer, unit_graphs_path
from agent_build_kit.graph.state import EventKind, Node, ResumeEvent
from agent_build_kit.graph.unit import seed_thread, thread_position
from agent_build_kit.pipeline.events import build_fetch_comments
from agent_build_kit.pipeline.pr_poller import FAILING_CHECKS_REASON, Poller
from agent_build_kit.pipeline.pr_replies import (
    MARKER,
    build_post_replies,
    given_comments,
    ignored,
    record_given_comments,
)
from agent_build_kit.pipeline.stack_runner import Restacked
from agent_build_kit.pipeline.units import UnitState, branch_name
from tests.factories import unit
from tests.forges.stand_in import StandInForge, lookup
from tests.graph_driver import fresh, tick
from tests.runner_fakes import Killed, Recorder

SLUG = "example/app"


class Host(StandInForge):
    """The stand-in forge, counting what the pipeline asks of it, and able to fail the read."""

    def __init__(self, **options: Any) -> None:
        super().__init__(**options)
        self.reads = 0
        self.failing = False
        self.prefixes: list[str] = []

    def review_notes(self, repo: RepoId, pr: int) -> list[ReviewNote]:
        self.reads += 1
        if self.failing:
            raise RuntimeError("502 Bad Gateway")
        return list(self.notes)

    def list_prs(self, repo: RepoId, *, head_prefix: str = "") -> list[PullRequest]:
        self.reads += 1
        self.prefixes.append(head_prefix)
        if self.failing:
            raise RuntimeError("502 Bad Gateway")
        return super().list_prs(repo, head_prefix=head_prefix)


def note(
    id: str, body: str, *, live: bool = True, path: str = "src/app.py", line: int = 3
) -> ReviewNote:
    return ReviewNote(id=id, body=body, path=path, line=line if live else None, live=live)


def said(*notes: ReviewNote) -> str:
    return "\n".join(f"[comment {n.id}] {n.path}:{n.line} — {n.body}" for n in notes)


class Scene:
    """A unit built and waiting in review, with a host whose notes change as the
    rework's agent runs: `arrives[i]` lands on the host during the i-th agent run."""

    def __init__(
        self,
        tmp_path: Path,
        *,
        delivered: Collection[ReviewNote] = (),
        arrives: list[list[ReviewNote]] | None = None,
        own: Collection[str] = (),
        top_level: list[list[tuple[str, str]]] | None = None,
        tier: str = "tier1",
        conversation: tuple[str, ...] = ("c1",),
    ) -> None:
        self.tmp_path = tmp_path
        self.arrives = list(arrives or [])
        # Conversation comments (id, body) landing on the pull request during the i-th agent run.
        self.top_level = list(top_level or [])
        self.runs = 0
        self.before: list[str] = []
        self.recorder: Recorder = fresh(tmp_path)
        self.host = Host(
            prs=[
                PullRequest(
                    number=7,
                    head="spec/add-marker/1",
                    base="main",
                    state="open",
                    conversation=conversation,
                )
            ],
            existing=7,
        )
        self.overrides: dict[str, Any] = dict(
            tier=tier,
            run_rework=self.agent,
            fetch_comments=build_fetch_comments(
                for_repo=lookup(self.host), own=lambda repo, pr: set(own)
            ),
            record_given=lambda repo, pr, ids: record_given_comments(tmp_path, SLUG, pr, ids),
            reply=build_post_replies(
                root=tmp_path, for_repo=lookup(self.host), log=self.recorder.log
            ),
        )
        tick(tmp_path, self.recorder, **self.overrides)
        self.reads_of_the_first_build = self.host.reads
        self.delivered = list(delivered)
        self.host.notes = list(self.delivered)
        self.review_ids_of(self.delivered)

    def review_ids_of(self, notes: Collection[ReviewNote]) -> None:
        """On GitHub an inline comment also creates a review with no body, and the poller
        lists its id in the conversation after the comments'. The comment bodies are left."""
        pr = self.host.prs[0]
        reviews = tuple(f"rv-{n.id}" for n in notes)
        self.host.prs[0] = pr.model_copy(update={"conversation": (*pr.conversation, *reviews)})

    def listed(self) -> tuple[str, ...]:
        """Every id on the pull request now: what a dispatch that read it now was built from."""
        return (*self.host.prs[0].conversation, *(n.id for n in self.host.notes))

    def move_base_once(self) -> None:
        """The next time the branch is moved onto its base, the move is clean."""
        moves = [Restacked(onto_unit="", onto_intent="", old_base="main", old_head="sha-0")]
        self.overrides["restack_onto"] = lambda **kw: moves.pop() if moves else None

    def agent(self, prompt: str, **kwargs: Any) -> str:
        """Answers each `[comment N]` it was given, then the host gets what arrives."""
        self.recorder.claude(prompt, **kwargs)
        if self.runs < len(self.arrives):
            self.host.notes = [*self.host.notes, *self.arrives[self.runs]]
            self.review_ids_of(self.arrives[self.runs])
        if self.runs < len(self.top_level):
            pr = self.host.prs[0]
            added = self.top_level[self.runs]
            self.host.prs[0] = pr.model_copy(
                update={
                    "conversation": (*(i for i, _ in added), *pr.conversation),
                    "comment_bodies": (*pr.comment_bodies, *(b for _, b in added)),
                }
            )
        self.runs += 1
        ids = re.findall(r"\[comment (\w+)\]", prompt)
        replies = [{"comment_id": i, "body": f"done {i}"} for i in ids]
        return json.dumps({"replies": replies, "summary": ""})

    def rework(self) -> None:
        """The delivery of the reviewer's words, then the run that works on them."""
        event = ResumeEvent(
            kind=EventKind.REWORK,
            reason="comment",
            feedback=said(*self.delivered),
            from_person=True,
            comment_ids=self.listed(),
        )
        self.recorder.logged.clear()
        self.before = list(self.recorder.events)
        tick(self.tmp_path, self.recorder, event=event, **self.overrides)
        tick(self.tmp_path, self.recorder, **self.overrides)

    @property
    def since(self) -> list[str]:
        return self.recorder.events[len(self.before) :]

    @property
    def agent_runs(self) -> int:
        return self.since.count("claude:rework")

    @property
    def pushes(self) -> int:
        return self.since.count("push")


def test_a_comment_added_while_the_rework_runs_is_addressed_and_one_push_carries_all_three(
    tmp_path: Path,
) -> None:
    first, second = note("n1", "remove this line"), note("n2", "rename that", line=9)
    third = note("n3", "and drop this one too", line=12)
    scene = Scene(tmp_path, delivered=[first, second], arrives=[[third]])

    scene.rework()

    assert scene.agent_runs == 2
    assert "and drop this one too" in scene.recorder.prompts[-1]
    assert scene.pushes == 1
    last_agent = len(scene.since) - 1 - scene.since[::-1].index("claude:rework")
    assert scene.since.index("push") > last_agent, "pushed after the last agent run"
    assert "review" in scene.since[last_agent:], "reviewed again before the push"


def test_nothing_new_pushes_with_no_extra_agent_run(tmp_path: Path) -> None:
    scene = Scene(tmp_path, delivered=[note("n1", "remove this line")], arrives=[[]])

    scene.rework()

    assert scene.agent_runs == 1
    assert scene.pushes == 1


def test_the_loop_returns_to_the_rework_for_each_pass_of_new_comments_and_ends_when_they_stop(
    tmp_path: Path,
) -> None:
    scene = Scene(
        tmp_path,
        delivered=[note("n1", "remove this line")],
        arrives=[[note("n2", "also this", line=5)], [note("n3", "and this", line=8)], []],
    )

    scene.rework()

    assert scene.agent_runs == 3, "the delivered comments, then two passes of new ones"
    assert scene.pushes == 1, "the third check found nothing and pushed"
    assert "also this" in scene.recorder.prompts[-2]
    assert "and this" in scene.recorder.prompts[-1]


def test_a_new_comment_the_host_marks_outdated_is_still_addressed(tmp_path: Path) -> None:
    stale = note("n2", "this whole block can go", live=False)
    scene = Scene(tmp_path, delivered=[note("n1", "remove this line")], arrives=[[stale]])

    scene.rework()

    assert scene.agent_runs == 2
    assert "this whole block can go" in scene.recorder.prompts[-1]


def test_a_note_on_the_pull_request_at_delivery_live_or_outdated_is_not_given_again(
    tmp_path: Path,
) -> None:
    live = note("n1", "remove this line")
    outdated = note("n2", "answered before", live=False)
    scene = Scene(tmp_path, delivered=[live, outdated], arrives=[[]])

    scene.rework()

    assert scene.agent_runs == 1
    assert scene.pushes == 1
    assert scene.recorder.prompts[-1].count("answered before") == 1, "given once, with the delivery"


def test_the_pipelines_own_reply_is_not_a_new_comment(tmp_path: Path) -> None:
    marked = note("r9", f"done n1\n\n<sub>spec-driven rework</sub>\n{MARKER}")
    recorded = ReviewNote(id="o1", body="Posted by the pipeline without its marker")
    scene = Scene(
        tmp_path,
        delivered=[note("n1", "remove this line")],
        arrives=[[marked, recorded]],
        own={"o1"},
    )

    scene.rework()

    assert scene.agent_runs == 1
    assert scene.pushes == 1


def test_each_addressed_comments_thread_gets_its_reply_after_the_push(tmp_path: Path) -> None:
    scene = Scene(
        tmp_path,
        delivered=[note("n1", "remove this line"), note("n2", "rename that", line=9)],
        arrives=[[note("n3", "and drop this one too", line=12)]],
    )

    scene.rework()

    assert {note_id for note_id, _ in scene.host.replies} == {"n1", "n2", "n3"}
    assert scene.pushes == 1


def test_a_failing_second_read_is_logged_and_the_work_pushes(tmp_path: Path) -> None:
    scene = Scene(tmp_path, delivered=[note("n1", "remove this line")], arrives=[[]])
    run = scene.agent

    def failing_after_the_agent(prompt: str, **kwargs: Any) -> str:
        answer = run(prompt, **kwargs)
        scene.host.failing = True
        return answer

    scene.overrides["run_rework"] = failing_after_the_agent

    scene.rework()

    assert scene.agent_runs == 1
    assert scene.pushes == 1
    assert any("502" in line for line in scene.recorder.logged), "the failure is logged"


def test_a_unit_with_no_pull_request_makes_no_request_for_comments(tmp_path: Path) -> None:
    scene = Scene(tmp_path)

    assert scene.reads_of_the_first_build == 0
    assert "push" in scene.recorder.events


def test_a_comment_added_during_a_rework_whose_branch_moved_onto_a_new_base_is_still_read(
    tmp_path: Path,
) -> None:
    scene = Scene(
        tmp_path,
        delivered=[note("n1", "remove this line")],
        arrives=[[note("n3", "and drop this one too", line=12)]],
    )
    scene.move_base_once()

    scene.rework()

    assert "tier1" in scene.since, "the clean move was checked again"
    assert scene.agent_runs == 2
    assert "and drop this one too" in scene.recorder.prompts[-1]
    assert scene.pushes == 1
    assert scene.since.index("push") > len(scene.since) - 1 - scene.since[::-1].index(
        "claude:rework"
    )


def test_a_top_level_comment_added_during_the_rework_reaches_the_second_agent_run(
    tmp_path: Path,
) -> None:
    scene = Scene(
        tmp_path,
        delivered=[note("n1", "remove this line")],
        top_level=[[("c2", "please also add a docstring")]],
    )

    scene.rework()

    assert scene.agent_runs == 2
    assert "please also add a docstring" in scene.recorder.prompts[-1]
    assert scene.pushes == 1


def test_comments_recorded_by_an_earlier_run_are_not_kept_when_a_rework_is_delivered(
    tmp_path: Path,
) -> None:
    scene = Scene(tmp_path)
    late = note("n5", "one more thing", line=20)
    scene.host.notes = [late]
    # An earlier run held with ids recorded as seen; n5 was not among them.
    stale = thread_state(tmp_path).model_copy(update={"seen_comments": ("c1", "n1")})
    asyncio.run(seed(tmp_path, stale))
    event = ResumeEvent(
        kind=EventKind.REWORK,
        reason="comment",
        feedback=said(late),
        from_person=True,
        comment_ids=scene.listed(),
    )
    scene.before = list(scene.recorder.events)

    tick(tmp_path, scene.recorder, event=event, **scene.overrides)
    tick(tmp_path, scene.recorder, **scene.overrides)

    assert scene.agent_runs == 1
    assert [i for i, _ in scene.host.replies].count("n5") == 1


def test_a_rework_after_new_comments_cut_short_once_the_agent_committed_does_not_run_again(
    tmp_path: Path,
) -> None:
    scene = Scene(
        tmp_path,
        delivered=[note("n1", "remove this line")],
        arrives=[[note("n3", "and drop this one too", line=12)]],
    )
    run = scene.agent

    def agent(prompt: str, **kwargs: Any) -> str:
        answer = run(prompt, **kwargs)
        if scene.runs == 2:
            scene.recorder.kill_after = "commit:fix"
        return answer

    scene.overrides["run_rework"] = agent
    event = ResumeEvent(
        kind=EventKind.REWORK,
        reason="comment",
        feedback=said(*scene.delivered),
        from_person=True,
        comment_ids=scene.listed(),
    )
    scene.before = list(scene.recorder.events)
    tick(tmp_path, scene.recorder, event=event, **scene.overrides)
    with pytest.raises(Killed):
        tick(tmp_path, scene.recorder, **scene.overrides)
    assert scene.agent_runs == 2, "the delivered words, then the late comment"

    tick(tmp_path, scene.recorder, **scene.overrides)

    assert scene.agent_runs == 2, "the step was not run again on resume"
    assert scene.pushes == 1


def test_the_pull_request_is_looked_up_by_the_units_branch(tmp_path: Path) -> None:
    scene = Scene(tmp_path, delivered=[note("n1", "remove this line")], arrives=[[]])

    scene.rework()

    assert scene.host.prefixes
    assert set(scene.host.prefixes) == {branch_name(unit())}


def test_a_tier2_unit_moved_onto_a_new_base_still_reads_comments_before_it_pushes(
    tmp_path: Path,
) -> None:
    scene = Scene(
        tmp_path,
        delivered=[note("n1", "remove this line")],
        arrives=[[note("n3", "and drop this one too", line=12)]],
        tier="tier2",
    )
    scene.move_base_once()

    scene.rework()

    assert "tier2" in scene.since
    assert scene.agent_runs == 2
    assert "and drop this one too" in scene.recorder.prompts[-1]
    assert scene.pushes == 1


def test_a_comment_posted_after_delivery_but_before_the_thread_runs_is_addressed_in_the_push(
    tmp_path: Path,
) -> None:
    scene = Scene(tmp_path, delivered=[note("n1", "remove this line")])
    event = ResumeEvent(
        kind=EventKind.REWORK,
        reason="comment",
        feedback=said(*scene.delivered),
        from_person=True,
        comment_ids=scene.listed(),
    )
    scene.before = list(scene.recorder.events)
    tick(tmp_path, scene.recorder, event=event, **scene.overrides)
    # The thread waits for a slot; a person comments meanwhile.
    scene.host.notes = [*scene.host.notes, note("n2", "one more thing", line=20)]

    tick(tmp_path, scene.recorder, **scene.overrides)

    assert scene.agent_runs == 2
    assert "one more thing" in scene.recorder.prompts[-1]
    assert scene.pushes == 1


def polled(scene: Scene, tmp_path: Path) -> tuple[Poller, list[str]]:
    seen: list[str] = []

    def dispatch(event: str, number: int, **kwargs: Any) -> bool:
        seen.append(event)
        return True

    poller = Poller(
        repo="app",
        state_path=tmp_path / "poll.json",
        dispatch=dispatch,
        list_prs=lambda: scene.host.list_prs(scene.host.repo_id()),
        ignore=lambda number: ignored(tmp_path, SLUG, number),
    )
    return poller, seen


def test_the_poller_does_not_report_a_comment_the_run_addressed_before_its_push(
    tmp_path: Path,
) -> None:
    scene = Scene(
        tmp_path,
        delivered=[note("n1", "remove this line")],
        top_level=[[("c3", "please also add a docstring")]],
    )
    poller, seen = polled(scene, tmp_path)
    poller.poll()
    scene.rework()
    assert scene.agent_runs == 2

    poller.poll()

    assert seen == [], "c3 was given to the agent in this push"


def test_the_poller_still_reports_a_comment_posted_after_the_last_check(tmp_path: Path) -> None:
    scene = Scene(
        tmp_path,
        delivered=[note("n1", "remove this line")],
        top_level=[[("c3", "please also add a docstring")]],
    )
    poller, seen = polled(scene, tmp_path)
    poller.poll()
    scene.rework()
    pr = scene.host.prs[0]
    scene.host.prs[0] = pr.model_copy(update={"conversation": (*pr.conversation, "c4")})

    poller.poll()

    assert seen == ["rework"]


def comment_arrives(scene: Scene, comment_id: str, body: str) -> None:
    """A person's conversation comment lands on the pull request."""
    pr = scene.host.prs[0]
    scene.host.prs[0] = pr.model_copy(
        update={
            "conversation": (comment_id, *pr.conversation),
            "comment_bodies": (*pr.comment_bodies, body),
        }
    )


def test_a_requeued_rework_does_not_hide_a_comment_it_was_never_given_from_the_poller(
    tmp_path: Path,
) -> None:
    scene = Scene(tmp_path, delivered=[note("n1", "remove this line")])
    poller, seen = polled(scene, tmp_path)
    poller.poll()
    # A requeue with no thread: the feedback was fixed when it was requeued.
    tick(tmp_path, scene.recorder, event=ResumeEvent(kind=EventKind.CLOSED), **scene.overrides)
    scene.recorder.store.set_feedback(unit().id, said(*scene.delivered), from_person=True)
    scene.recorder.store.set_state(unit().id, UnitState.PLANNED, note="rework requested: comment")
    # Posted after the requeue, before the node runs.
    comment_arrives(scene, "c5", "please also add a docstring")

    tick(tmp_path, scene.recorder, **scene.overrides)

    assert "c5" not in ignored(tmp_path, SLUG, 7)
    poller.poll()
    assert seen == ["rework"], "the poller reports it, as the agent was never given it"


def test_a_failing_checks_rework_does_not_hide_a_comment_it_was_never_given_from_the_poller(
    tmp_path: Path,
) -> None:
    scene = Scene(tmp_path, delivered=[note("n1", "remove this line")])
    poller, seen = polled(scene, tmp_path)
    poller.poll()
    # Posted after the poller's list, before the delivery reads the comments.
    comment_arrives(scene, "c5", "please also add a docstring")
    event = ResumeEvent(
        kind=EventKind.REWORK,
        reason=f"{FAILING_CHECKS_REASON}: tier1",
        feedback=f"{FAILING_CHECKS_REASON}: tier1\n\nboom",
        from_person=False,
    )
    tick(tmp_path, scene.recorder, event=event, **scene.overrides)

    tick(tmp_path, scene.recorder, **scene.overrides)

    assert "c5" not in ignored(tmp_path, SLUG, 7)
    poller.poll()
    assert seen == ["rework"], "the CI agent never saw it, so the poller reports it"


def test_a_comment_posted_after_the_poller_listed_it_is_addressed_not_taken_as_given(
    tmp_path: Path,
) -> None:
    scene = Scene(tmp_path, delivered=[note("n1", "remove this line")])
    poller, seen = polled(scene, tmp_path)
    poller.poll()
    listed = scene.listed()
    # Posted after the poller's list and the dispatch's reads, before the delivery tick.
    comment_arrives(scene, "c5", "please also add a docstring")
    event = ResumeEvent(
        kind=EventKind.REWORK,
        reason="comment",
        feedback=said(*scene.delivered),
        from_person=True,
        comment_ids=listed,
    )
    scene.before = list(scene.recorder.events)
    tick(tmp_path, scene.recorder, event=event, **scene.overrides)

    tick(tmp_path, scene.recorder, **scene.overrides)

    assert scene.agent_runs == 2
    assert "please also add a docstring" in scene.recorder.prompts[-1]
    assert scene.pushes == 1
    assert "c5" in given_comments(tmp_path, SLUG, 7)
    poller.poll()
    assert seen == [], "c5 was addressed in this push"


def test_a_note_arriving_during_a_rework_on_a_pull_request_with_no_comments_is_addressed(
    tmp_path: Path,
) -> None:
    scene = Scene(tmp_path, conversation=(), arrives=[[note("n1", "please rename this")]])
    event = ResumeEvent(
        kind=EventKind.REWORK,
        reason=f"{FAILING_CHECKS_REASON}: tier1",
        feedback=f"{FAILING_CHECKS_REASON}: tier1\n\nboom",
        from_person=False,
    )
    scene.before = list(scene.recorder.events)
    tick(tmp_path, scene.recorder, event=event, **scene.overrides)

    tick(tmp_path, scene.recorder, **scene.overrides)

    assert scene.runs == 2, "the CI fix, then the note that arrived while it ran"
    assert "please rename this" in scene.recorder.prompts[-1]
    assert scene.pushes == 1


def test_an_inline_comment_addressed_before_the_push_is_not_reported_as_a_second_rework(
    tmp_path: Path,
) -> None:
    scene = Scene(
        tmp_path,
        delivered=[note("n1", "remove this line")],
        arrives=[[note("n3", "and drop this one too", line=12)]],
    )
    poller, seen = polled(scene, tmp_path)
    poller.poll()

    scene.rework()

    assert scene.agent_runs == 2
    assert scene.pushes == 1
    assert "rv-n3" in scene.host.prs[0].conversation
    poller.poll()
    assert seen == [], "n3 and the review GitHub made for it were both given"


def thread_state(tmp_path: Path) -> Any:
    async def read() -> Any:
        async with open_checkpointer(unit_graphs_path(tmp_path / "state")) as saver:
            return (await thread_position(saver, unit().id)).state

    return asyncio.run(read())


async def seed(tmp_path: Path, state: Any) -> None:
    async with open_checkpointer(unit_graphs_path(tmp_path / "state")) as saver:
        await seed_thread(saver, state, as_node=Node.AWAIT_REVIEW)
