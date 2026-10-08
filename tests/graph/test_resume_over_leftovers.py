"""A node killed while its agent was editing resumes over what the agent left, and a
dirty tree that is not the node's own parks the unit (docs/unit-graph.md, Durability).

The worktree, the commit and the branch count are the real ones over a real git
repository; the agent is a runtime behind the seam that writes files and dies once.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.graph.state import EventKind, Node, ResumeEvent
from agent_build_kit.pipeline.shell import git_out
from agent_build_kit.pipeline.stack_runner import LEFTOVERS_NOTE, RunOutcome, RunStatus
from agent_build_kit.pipeline.unit_store import Cause
from agent_build_kit.pipeline.wiring import INTERRUPTED_PROMPT
from agent_build_kit.runtimes.base import AgentInterrupted, AgentRateLimited
from tests.factories import unit
from tests.graph.test_build_path import build
from tests.graph.test_remaining_paths import Adapting, decisions
from tests.graph_driver import fresh, position, tick
from tests.leftovers_driver import LEFTOVER, Habitat, Hands
from tests.runner_fakes import Killed, Recorder, rejecting

STRAY = "stray.txt"
UNIT = unit().id


def killed_in(tmp_path: Path, step: str, **hands: Any) -> tuple[Habitat, Recorder]:
    """A unit whose agent died in `step`, mid-edit, in a real worktree."""
    runtime = Hands(die_in=step, **hands)
    habitat = Habitat(tmp_path, runtime)
    recorder = fresh(tmp_path)
    if step == "rework":
        recorder.verdicts = [rejecting("rename it")]
    if step == "fix_checks":
        recorder.tier1_results = [(False, "E501 line too long")]
    with pytest.raises(type(runtime.dies)):
        tick(tmp_path, recorder, **habitat.overrides())
    return habitat, recorder


def resumed(tmp_path: Path, habitat: Habitat, recorder: Recorder) -> RunOutcome:
    return tick(tmp_path, recorder, **habitat.overrides())


# --- 1.0 the record of a started run -------------------------------------------------


@pytest.mark.parametrize(
    "step, node",
    [
        ("tests", Node.TESTS),
        ("implement", Node.IMPLEMENT),
        ("fix_checks", Node.FIX_CHECKS),
        ("rework", Node.REWORK),
    ],
)
def test_a_killed_agent_node_leaves_its_own_name_in_the_thread(
    tmp_path: Path, step: str, node: Node
) -> None:
    killed_in(tmp_path, step)

    stopped = position(tmp_path)
    assert stopped.next == (node,)
    assert stopped.state is not None
    assert stopped.state.running_node == node.value


@pytest.mark.parametrize(
    "hands",
    [
        dict(sessions=False),
        dict(names_session_first=False),
    ],
    ids=["runtime-names-no-session", "killed-before-the-session-is-named"],
)
def test_the_record_does_not_depend_on_the_runtime_naming_a_session(
    tmp_path: Path, hands: dict[str, Any]
) -> None:
    killed_in(tmp_path, "implement", **hands)

    stopped = position(tmp_path)
    assert stopped.state is not None
    assert stopped.state.session_id == ""
    assert stopped.state.running_node == "implement"


def test_the_record_is_cleared_when_the_node_completes(tmp_path: Path) -> None:
    habitat, recorder = killed_in(tmp_path, "tests")
    state = position(tmp_path).state
    assert state is not None and state.running_node == "tests", "left behind by the kill"

    resumed(tmp_path, habitat, recorder)

    finished = position(tmp_path).state
    assert finished is not None
    assert finished.running_node == ""


def test_a_node_reached_but_not_started_has_no_record(tmp_path: Path) -> None:
    habitat, recorder = killed_in(tmp_path, "tests")
    state = position(tmp_path).state
    assert state is not None and state.running_node == "tests"

    # The tests node finishes; the usage guard refuses the implement node.
    allowed = iter([True, False])
    resumed_but_waiting = tick(
        tmp_path,
        recorder,
        may_start=lambda: (next(allowed, False), "window"),
        **habitat.overrides(),
    )

    assert resumed_but_waiting.status == RunStatus.PAUSED
    waiting = position(tmp_path)
    assert waiting.next == (Node.IMPLEMENT,)
    assert waiting.state is not None
    assert waiting.state.running_node == ""


# --- 1.1 a resumed session is told nothing extra ---------------------------------------


def test_a_rework_killed_mid_edit_resumes_its_session_over_its_own_file(tmp_path: Path) -> None:
    habitat, recorder = killed_in(tmp_path, "rework")

    outcome = resumed(tmp_path, habitat, recorder)

    assert outcome.status == RunStatus.OPEN
    assert recorder.store.get(UNIT).state == "in_review"
    resume = habitat.runtime.after_death()[0]
    assert resume.resume_session, "the recorded session was continued"
    assert resume.prompt == INTERRUPTED_PROMPT, "no leftover note for a session that holds the edit"
    assert habitat.commits_on_branch()[-1].startswith("fix:")
    assert LEFTOVER in habitat.files_in("fix:"), "in the rework's own commit"
    assert (habitat.tree / LEFTOVER).exists()
    assert len(habitat.commits_on_branch()) == 3, "tests, implementation, rework: no WIP commit"


# --- 1.2 a new session is handed the leftovers -----------------------------------------


@pytest.mark.parametrize(
    "hands",
    [
        dict(sessions=False),
        dict(names_session_first=False),
        dict(resumes=False),
        dict(refuses="no conversation found with session id sess-2"),
    ],
    ids=[
        "runtime-names-no-session",
        "killed-before-the-session-is-named",
        "runtime-cannot-resume",
        "session-refused",
    ],
)
def test_a_new_session_over_leftovers_is_told_they_are_an_interrupted_runs_work(
    tmp_path: Path, hands: dict[str, Any]
) -> None:
    habitat, recorder = killed_in(tmp_path, "implement", **hands)

    outcome = resumed(tmp_path, habitat, recorder)

    assert outcome.status == RunStatus.OPEN
    fresh_start = habitat.runtime.after_death()[-1]
    assert fresh_start.resume_session == ""
    note = fresh_start.prompt.lower()
    assert LEFTOVER in fresh_start.prompt
    assert "uncommitted" in note
    assert "interrupted run" in note
    assert "diff" in note, "to be reviewed against the diff"
    assert "discard them" not in note
    assert (habitat.tree / LEFTOVER).exists(), "still in the tree"
    assert LEFTOVER in habitat.files_in("feat:"), "committed with the node's commit"
    assert [s.split(":")[0] for s in habitat.commits_on_branch()] == ["test", "feat"]


def test_a_refused_session_is_tried_with_the_interruption_prompt_alone_first(
    tmp_path: Path,
) -> None:
    habitat, recorder = killed_in(
        tmp_path, "implement", refuses="no conversation found with session id sess-2"
    )

    resumed(tmp_path, habitat, recorder)

    refused, fresh_start = habitat.runtime.after_death()
    assert refused.resume_session
    assert refused.prompt == INTERRUPTED_PROMPT
    assert LEFTOVER not in refused.prompt
    assert LEFTOVER in fresh_start.prompt


def test_a_long_list_of_leftovers_is_capped_in_the_prompt(tmp_path: Path) -> None:
    habitat, recorder = killed_in(tmp_path, "implement", sessions=False, extra=60)

    resumed(tmp_path, habitat, recorder)

    prompt = habitat.runtime.after_death()[-1].prompt
    assert "leftover-00.txt" in prompt
    assert "leftover-59.txt" not in prompt
    assert (habitat.tree / "leftover-59.txt").exists(), "capped in the prompt, not in the tree"
    assert "leftover-59.txt" in habitat.files_in("feat:")


# --- 1.3 a limit or a timeout kills the run the same way --------------------------------


LIMITS = [
    AgentRateLimited("usage limit reached", resets_at=datetime(2030, 1, 1, tzinfo=UTC)),
    AgentInterrupted("the agent timed out"),
]


@pytest.mark.parametrize("dies", LIMITS, ids=["rate-limited", "timed-out"])
def test_a_rework_killed_by_a_limit_or_a_timeout_resumes_its_session(
    tmp_path: Path, dies: BaseException
) -> None:
    habitat, recorder = killed_in(tmp_path, "rework", dies=dies)

    outcome = resumed(tmp_path, habitat, recorder)

    assert outcome.status == RunStatus.OPEN
    resume = habitat.runtime.after_death()[0]
    assert resume.resume_session and resume.prompt == INTERRUPTED_PROMPT
    assert LEFTOVER in habitat.files_in("fix:")
    assert recorder.store.get(UNIT).state == "in_review"


@pytest.mark.parametrize("dies", LIMITS, ids=["rate-limited", "timed-out"])
def test_an_implement_killed_by_a_limit_or_a_timeout_resumes_in_a_new_session(
    tmp_path: Path, dies: BaseException
) -> None:
    habitat, recorder = killed_in(tmp_path, "implement", dies=dies, sessions=False)

    outcome = resumed(tmp_path, habitat, recorder)

    assert outcome.status == RunStatus.OPEN
    assert LEFTOVER in habitat.runtime.after_death()[-1].prompt
    assert LEFTOVER in habitat.files_in("feat:")
    assert recorder.store.get(UNIT).state != "failed"


def test_a_kill_at_a_clean_boundary_resumes_unchanged(tmp_path: Path) -> None:
    habitat, recorder = killed_in(tmp_path, "implement", edits=False)
    state = position(tmp_path).state
    assert state is not None and state.running_node == "implement", "started, nothing written"
    assert git_out(habitat.tree, "status", "--porcelain") == ""

    outcome = resumed(tmp_path, habitat, recorder)

    assert outcome.status == RunStatus.OPEN
    resume = habitat.runtime.after_death()[0]
    assert resume.resume_session and resume.prompt == INTERRUPTED_PROMPT
    assert [s.split(":")[0] for s in habitat.commits_on_branch()] == ["test", "feat"]


# --- 1.4 a tree that is not the node's own parks the unit --------------------------------


def parked(tmp_path: Path, recorder: Recorder, habitat: Habitat, outcome: RunOutcome) -> None:
    """The unit is held for its tree, not failed, and the tree is as it was left."""
    assert outcome.status == RunStatus.HELD
    stored = recorder.store.get(UNIT)
    assert stored.state != "failed"
    assert stored.cause is Cause.DIRTY_WORKTREE
    words = f"{stored.note}\n{outcome.detail}".lower()
    assert STRAY in words, "the paths are named"
    assert "commit or remove" in words, "a person is asked to"
    assert (habitat.tree / STRAY).read_text() == "mine\n", "nothing was cleaned"
    assert git_out(habitat.tree, "status", "--porcelain").split() == ["??", STRAY]


def edit_by_hand(habitat: Habitat) -> None:
    (habitat.tree / STRAY).write_text("mine\n")


def rework_event() -> ResumeEvent:
    return ResumeEvent(
        kind=EventKind.REWORK, reason="comment", feedback="rename it", from_person=True
    )


def test_a_hand_edit_on_a_unit_that_was_not_killed_parks_it(tmp_path: Path) -> None:
    habitat = Habitat(tmp_path, Hands())
    recorder = fresh(tmp_path)
    assert tick(tmp_path, recorder, **habitat.overrides()).status == RunStatus.OPEN
    asked = len(habitat.runtime.requests)
    edit_by_hand(habitat)
    tick(tmp_path, recorder, event=rework_event(), **habitat.overrides())

    outcome = tick(tmp_path, recorder, **habitat.overrides())

    parked(tmp_path, recorder, habitat, outcome)
    assert len(habitat.runtime.requests) == asked, "no agent was started over it"


def test_a_dirty_tree_at_a_node_that_runs_no_agent_parks_the_unit(tmp_path: Path) -> None:
    habitat = Habitat(tmp_path, Hands())
    recorder = fresh(tmp_path)
    ran = {"checks": 0}

    def killed_checks(**kwargs: Any) -> tuple[bool, str]:
        ran["checks"] += 1
        raise Killed("power loss")

    with pytest.raises(Killed):
        tick(tmp_path, recorder, **habitat.overrides(), run_tier1=killed_checks)
    assert position(tmp_path).next == (Node.CHECKS,)
    edit_by_hand(habitat)

    outcome = resumed(tmp_path, habitat, recorder)

    parked(tmp_path, recorder, habitat, outcome)
    assert ran["checks"] == 1, "checks did not run over it"


def test_an_edit_on_a_unit_waiting_at_an_agent_node_that_never_started_parks_it(
    tmp_path: Path,
) -> None:
    habitat = Habitat(tmp_path, Hands())
    recorder = fresh(tmp_path)
    waiting = tick(tmp_path, recorder, may_start=lambda: (False, "window"), **habitat.overrides())
    assert waiting.status == RunStatus.PAUSED
    edit_by_hand(habitat)

    outcome = resumed(tmp_path, habitat, recorder)

    parked(tmp_path, recorder, habitat, outcome)
    assert habitat.runtime.requests == [], "no agent was started over it"


def test_a_requeue_after_the_tree_is_cleaned_resumes_the_unit(tmp_path: Path) -> None:
    habitat = Habitat(tmp_path, Hands())
    recorder = fresh(tmp_path)
    tick(tmp_path, recorder, may_start=lambda: (False, "window"), **habitat.overrides())
    edit_by_hand(habitat)
    parked(tmp_path, recorder, habitat, resumed(tmp_path, habitat, recorder))
    (habitat.tree / STRAY).unlink()

    tick(
        tmp_path,
        recorder,
        event=ResumeEvent(kind=EventKind.REQUEUE, reason="resume"),
        **habitat.overrides(),
    )
    outcome = resumed(tmp_path, habitat, recorder)

    assert outcome.status == RunStatus.OPEN
    assert [s.split(":")[0] for s in habitat.commits_on_branch()] == ["test", "feat"]
    assert recorder.store.get(UNIT).state == "in_review"


# --- 1.5 the commit order and the approved-commit gate are unchanged -----------------------


def test_a_tests_nodes_leftovers_are_committed_as_tests(tmp_path: Path) -> None:
    habitat, recorder = killed_in(tmp_path, "tests", sessions=False)

    outcome = resumed(tmp_path, habitat, recorder)

    assert outcome.status == RunStatus.OPEN
    assert [s.split(":")[0] for s in habitat.commits_on_branch()] == ["test", "feat"]
    assert LEFTOVER in habitat.files_in("test:")
    assert LEFTOVER not in habitat.files_in("feat:")
    assert "implement.txt" in habitat.files_in("feat:")


def test_a_head_that_changed_since_the_approval_is_reviewed_again(tmp_path: Path) -> None:
    runtime = Hands(die_in="rework")
    habitat = Habitat(tmp_path, runtime)
    recorder = fresh(tmp_path)
    assert tick(tmp_path, recorder, **habitat.overrides()).status == RunStatus.OPEN
    assert recorder.events.count("review") == 1
    approved_head = git_out(habitat.tree, "rev-parse", "HEAD")

    tick(tmp_path, recorder, event=rework_event(), **habitat.overrides())
    with pytest.raises(Killed):
        tick(tmp_path, recorder, **habitat.overrides())
    outcome = resumed(tmp_path, habitat, recorder)

    assert outcome.status == RunStatus.OPEN
    assert git_out(habitat.tree, "rev-parse", "HEAD") != approved_head
    assert LEFTOVER in habitat.files_in("fix:")
    assert recorder.events.count("review") == 2, "the new head was reviewed, not waved through"


# --- 1.6 a review's leftovers are not its own; a requeue resumes at the parked node ---------


def cleaned_and_requeued(tmp_path: Path, habitat: Habitat, recorder: Recorder) -> RunOutcome:
    (habitat.tree / STRAY).unlink()
    return requeued(tmp_path, habitat, recorder)


def requeued(tmp_path: Path, habitat: Habitat, recorder: Recorder) -> RunOutcome:
    tick(
        tmp_path,
        recorder,
        event=ResumeEvent(kind=EventKind.REQUEUE, reason="resume"),
        **habitat.overrides(),
    )
    return resumed(tmp_path, habitat, recorder)


def test_a_review_killed_with_a_dirty_tree_parks_the_unit_at_review(tmp_path: Path) -> None:
    habitat = Habitat(tmp_path, Hands())
    recorder = fresh(tmp_path)

    def killed_review(**kwargs: Any) -> str:
        edit_by_hand(habitat)
        raise Killed("power loss")

    with pytest.raises(Killed):
        tick(tmp_path, recorder, **habitat.overrides(), run_review=killed_review)
    stopped = position(tmp_path).state
    assert stopped is not None and stopped.running_node == Node.REVIEW.value
    asked = len(habitat.runtime.requests)

    outcome = resumed(tmp_path, habitat, recorder)

    parked(tmp_path, recorder, habitat, outcome)
    assert len(habitat.runtime.requests) == asked, "no agent was started over it"
    assert not any(LEFTOVERS_NOTE[:20] in r.prompt for r in habitat.runtime.requests)
    assert recorder.events.count("review") == 0, "nothing judged the tree"


def test_a_requeue_after_a_park_at_implement_runs_implement(tmp_path: Path) -> None:
    habitat = Habitat(tmp_path, Hands())
    recorder = fresh(tmp_path)
    window = [0, False]  # guard calls so far, and whether it is open now

    def may_start() -> tuple[bool, str]:
        window[0] += 1
        return (window[0] == 1 or bool(window[1]), "window")

    paused = tick(tmp_path, recorder, may_start=may_start, **habitat.overrides())
    assert paused.status == RunStatus.PAUSED
    assert [s.split(":")[0] for s in habitat.commits_on_branch()] == ["test"]
    edit_by_hand(habitat)
    window[1] = True
    parked(
        tmp_path,
        recorder,
        habitat,
        tick(tmp_path, recorder, may_start=may_start, **habitat.overrides()),
    )

    outcome = cleaned_and_requeued(tmp_path, habitat, recorder)

    assert outcome.status == RunStatus.OPEN
    assert [s.split(":")[0] for s in habitat.commits_on_branch()] == ["test", "feat"]
    assert "implement.txt" in habitat.files_in("feat:")


def test_a_requeue_after_the_edits_were_committed_by_hand_still_runs_implement(
    tmp_path: Path,
) -> None:
    habitat = Habitat(tmp_path, Hands())
    recorder = fresh(tmp_path)
    window = [0, False]  # guard calls so far, and whether it is open now

    def may_start() -> tuple[bool, str]:
        window[0] += 1
        return (window[0] == 1 or bool(window[1]), "window")

    tick(tmp_path, recorder, may_start=may_start, **habitat.overrides())
    edit_by_hand(habitat)
    window[1] = True
    parked(
        tmp_path,
        recorder,
        habitat,
        tick(tmp_path, recorder, may_start=may_start, **habitat.overrides()),
    )
    asked = len(habitat.runtime.requests)
    git_out(habitat.tree, "add", STRAY)
    git_out(habitat.tree, "commit", "-m", "chore: by hand")

    outcome = requeued(tmp_path, habitat, recorder)

    assert outcome.status == RunStatus.OPEN
    assert len(habitat.runtime.requests) > asked, "the implement agent ran after the requeue"
    assert [s.split(":")[0] for s in habitat.commits_on_branch()] == ["test", "chore", "feat"]
    assert "implement.txt" in habitat.files_in("feat:")


def test_a_requeue_after_a_park_at_rework_keeps_the_feedback(tmp_path: Path) -> None:
    habitat = Habitat(tmp_path, Hands())
    recorder = fresh(tmp_path)
    assert tick(tmp_path, recorder, **habitat.overrides()).status == RunStatus.OPEN
    edit_by_hand(habitat)
    tick(tmp_path, recorder, event=rework_event(), **habitat.overrides())
    parked(tmp_path, recorder, habitat, tick(tmp_path, recorder, **habitat.overrides()))
    asked = len(habitat.runtime.requests)

    outcome = cleaned_and_requeued(tmp_path, habitat, recorder)

    assert outcome.status == RunStatus.OPEN
    rework = habitat.runtime.requests[asked:]
    assert rework and "rename it" in rework[0].prompt, "the person's request reached the agent"
    assert any(s.startswith("fix:") for s in habitat.commits_on_branch())


def test_a_requeue_before_the_tree_is_clean_leaves_the_unit_parked(tmp_path: Path) -> None:
    habitat = Habitat(tmp_path, Hands())
    recorder = fresh(tmp_path)
    window = [0, False]  # guard calls so far, and whether it is open now

    def may_start() -> tuple[bool, str]:
        window[0] += 1
        return (window[0] == 1 or bool(window[1]), "window")

    def tick_on(**more: Any) -> RunOutcome:
        return tick(tmp_path, recorder, may_start=may_start, **more, **habitat.overrides())

    def requeue() -> RunOutcome:
        return tick_on(event=ResumeEvent(kind=EventKind.REQUEUE, reason="resume"))

    def still_parked() -> None:
        stored = recorder.store.get(UNIT)
        assert stored.state == "held"
        assert stored.cause is Cause.DIRTY_WORKTREE
        stopped = position(tmp_path)
        assert stopped.next == (Node.HELD,)
        assert stopped.state is not None
        assert stopped.state.parked_node == Node.IMPLEMENT.value
        assert (habitat.tree / STRAY).read_text() == "mine\n"

    tick_on()
    edit_by_hand(habitat)
    window[1] = True
    parked(tmp_path, recorder, habitat, tick_on())
    # A requeue already in the thread's state, then a park at implement again.
    (habitat.tree / STRAY).unlink()
    window[1] = False
    requeue()
    edit_by_hand(habitat)
    window[1] = True
    parked(tmp_path, recorder, habitat, tick_on())

    requeue()
    still_parked()
    requeue()
    still_parked()

    (habitat.tree / STRAY).unlink()
    requeue()
    outcome = tick_on()

    assert outcome.status == RunStatus.OPEN
    assert [s.split(":")[0] for s in habitat.commits_on_branch()] == ["test", "feat"]
    assert recorder.store.get(UNIT).state == "in_review"


def test_a_killed_adapt_leaves_its_name_and_resumes_the_port(tmp_path: Path) -> None:
    recorder = fresh(tmp_path)
    adapting = Adapting(
        recorder,
        [decisions(("test_click", "keep", ""))],
        old_tests=("test_click",),
        present={"test_click"},
    )
    overrides = adapting.overrides()
    port = overrides["run_rework"]
    dies = [True]

    def run_rework(prompt: str, **kw: Any) -> str:
        if dies:
            dies.pop()
            raise Killed("power loss")
        return port(prompt, **kw)

    overrides["run_rework"] = run_rework

    with pytest.raises(Killed):
        build(tmp_path, recorder, base="spec/c/2", **overrides)

    stopped = position(tmp_path)
    assert stopped.next == (Node.ADAPT,)
    assert stopped.state is not None
    assert stopped.state.running_node == Node.ADAPT.value

    outcome = build(tmp_path, recorder, base="spec/c/2", **overrides)

    assert outcome.status == RunStatus.OPEN
    assert "commit:adapt" in recorder.events
