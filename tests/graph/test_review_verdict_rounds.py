"""How a unit's review loop ends, on the graph engine.

A reviewer can approve, approve with follow-ups, refuse, or run out of rounds.
These tests hand the loop each verdict shape through the review run's raw JSON
reply, and check what becomes of the unit: the round note each reviewer is
given, where deferred follow-ups are recorded and who sees them, and what a
unit whose rounds run out leaves for a person.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.config import active
from agent_build_kit.pipeline.unit_store import Cause
from agent_build_kit.pipeline.units import HELD, IN_REVIEW, PLANNED
from tests.factories import unit
from tests.graph.test_build_path import build, fresh
from tests.graph_driver import position, run_on_graph, tick
from tests.runner_fakes import Killed, Recorder, approving, make_runner

FOLLOW_UPS = Path("openspec") / "changes" / "add-marker" / "follow-ups.md"
LOCK = "Name the lock after what it guards"


def flat(text: str) -> str:
    return " ".join(text.split())


def verdict(**fields: object) -> str:
    return json.dumps({"approved": False, "feedback": "", **fields})


def approval_with(*items: object) -> str:
    return json.dumps({"approved": True, "feedback": "", "follow_ups": list(items)})


def optional(point: str) -> dict[str, str]:
    return {"kind": "optional", "point": point}


def capturing(recorder: Recorder, bodies: list[str]) -> Callable[..., int]:
    def open_pr(u: Any, *, body: str, base: str, cwd: Path, **stacked: str) -> int:
        bodies.append(body)
        return recorder.open_pr(u, body=body, base=base, cwd=cwd, **stacked)

    return open_pr


def recorded(tmp_path: Path) -> str:
    path = tmp_path / "meta" / FOLLOW_UPS
    return path.read_text() if path.exists() else ""


# --- the round note ---------------------------------------------------------------


def test_every_round_is_told_its_number_what_is_left_and_what_running_out_costs(
    tmp_path: Path,
) -> None:
    """A reviewer that knows the cost can weigh a residual nit against losing a
    correct implementation."""
    total = active().limits.max_review_rounds
    recorder = fresh(tmp_path)
    recorder.verdicts = [verdict(feedback="the lock is not released on error")] * total

    build(tmp_path, recorder)

    assert len(recorder.contexts) == total
    for number, context in enumerate(recorder.contexts, start=1):
        note = flat(context).lower()
        assert f"round {number} of {total}" in note, "the first round is told too"
        assert f"{total - number} remaining" in note
        assert "not merged" in note, "what ending without approval costs"
        assert "starts from nothing" not in note, "the work is pushed and held, not discarded"


def test_the_final_round_says_it_is_final(tmp_path: Path) -> None:
    total = active().limits.max_review_rounds
    recorder = fresh(tmp_path)
    recorder.verdicts = [verdict(feedback="still no")] * total

    build(tmp_path, recorder)

    assert "final round" in flat(recorder.contexts[-1]).lower()
    assert all("final round" not in flat(c).lower() for c in recorder.contexts[:-1])


# --- approve with follow-ups ----------------------------------------------------------


def test_an_approval_with_follow_ups_approves_and_records_them_against_the_change(
    tmp_path: Path,
) -> None:
    """One optional observation is worth recording, not another round. Recorded
    where the change's next unit and the PR's reviewer see it, not in a log."""
    recorder = fresh(tmp_path)
    recorder.store.upsert([unit("add-marker/2", groups=(2,))])
    recorder.verdicts = [approval_with(optional(LOCK))]
    bodies: list[str] = []

    outcome = build(tmp_path, recorder, open_pr=capturing(recorder, bodies))

    assert outcome.status == "open"
    assert recorder.events.count("review") == 1, "no further round"
    assert "claude:rework" not in recorder.events
    stored = recorder.store.get(unit().id)
    assert stored.state == IN_REVIEW
    assert stored.approved, "approved at the reviewed commit"
    assert LOCK in recorded(tmp_path)
    assert LOCK in bodies[0]

    later = Recorder(recorder.store)
    run_on_graph(
        make_runner(recorder.store, later, tmp_path),
        recorder.store.get("add-marker/2"),
        base="spec/add-marker/1",
    )
    assert LOCK in later.prompts[0], "the change's next unit is built knowing what was left"
    assert LOCK in later.prompts[1], "the implementation prompt needs the same note"


def test_the_last_rounds_findings_outlive_the_push_that_clears_the_rounds(tmp_path: Path) -> None:
    """The review tab reads them once the unit has a pull request: the rounds are
    cleared by then, and the approving round was never one of them."""
    recorder = fresh(tmp_path)
    finding = {"file": "src/marker.py", "line": 7, "summary": "name the lock", "required": False}
    recorder.verdicts = [json.dumps({"approved": True, "feedback": "", "findings": [finding]})]

    outcome = tick(tmp_path, recorder)

    assert outcome.status == "open"
    state = position(tmp_path).state
    assert state is not None
    assert state.review_rounds == ()
    assert [
        (f["id"], f["file"], f["line"], f["summary"], f["required"]) for f in state.last_findings
    ] == [("1.1", "src/marker.py", 7, "name the lock", False)]


def test_an_unreadable_follow_up_item_blocks_rather_than_being_dropped(tmp_path: Path) -> None:
    """An item with an extra key fails validation. Dropping it silently would
    let `approved: true` through over whatever it was trying to say."""
    recorder = fresh(tmp_path)
    recorder.verdicts = [
        approval_with({"kind": "correctness", "point": "the lock leaks", "file": "a.py"}),
        approving(),
    ]

    outcome = build(tmp_path, recorder)

    assert recorder.events.count("review") == 2, "not approved on the strength of the bad item"
    rework_prompt = next(p for p in recorder.prompts if "review of this branch" in p)
    assert "the lock leaks" in rework_prompt, "the point survives, even though the shape did not"
    assert outcome.status == "open"


def test_a_bare_string_follow_up_also_blocks_rather_than_being_dropped(tmp_path: Path) -> None:
    recorder = fresh(tmp_path)
    recorder.verdicts = [
        json.dumps({"approved": True, "feedback": "", "follow_ups": ["fix the lock"]}),
        approving(),
    ]

    outcome = build(tmp_path, recorder)

    assert recorder.events.count("review") == 2
    rework_prompt = next(p for p in recorder.prompts if "review of this branch" in p)
    assert "fix the lock" in rework_prompt
    assert outcome.status == "open"


def test_a_follow_up_survives_a_later_push_that_does_not_repeat_it(tmp_path: Path) -> None:
    """A follow-up is deferred once, not repeated on every later verdict, so the
    PR reviewer must still see it after a rework or a plain approval."""
    recorder = fresh(tmp_path)
    recorder.verdicts = [approval_with(optional(LOCK))]
    bodies: list[str] = []
    build(tmp_path, recorder, open_pr=capturing(recorder, bodies))
    assert LOCK in bodies[0]

    recorder.store.set_feedback(unit().id, "tidy the error message")
    recorder.verdicts = [approving()]
    build(tmp_path, recorder, open_pr=capturing(recorder, bodies))

    assert len(bodies) == 2
    assert LOCK in bodies[1], "a later push must not lose an earlier round's follow-up"


def test_repeating_the_same_follow_up_does_not_duplicate_its_record(tmp_path: Path) -> None:
    recorder = fresh(tmp_path)
    recorder.verdicts = [approval_with(optional(LOCK))]
    build(tmp_path, recorder)

    recorder.store.set_feedback(unit().id, "tidy something else")
    recorder.verdicts = [approval_with(optional(LOCK))]
    build(tmp_path, recorder)

    text = recorded(tmp_path)
    assert text.count(LOCK) == 1
    assert text.count(f"## From `{unit().id}`") == 1


def test_a_failure_after_approval_and_before_the_push_leaves_no_follow_up_block(
    tmp_path: Path,
) -> None:
    """Recorded only after the push succeeds: a follow-up for work that never
    left the machine would describe nothing real. Tier 1 runs before review on
    the graph, so the failure after approval is tier 2's."""
    recorder = fresh(tmp_path, tier2_ok=False)
    recorder.store.upsert([unit(tier="tier2")])
    recorder.verdicts = [approval_with(optional(LOCK))]

    outcome = build(tmp_path, recorder)

    assert outcome.status == "failed"
    assert "push" not in recorder.events
    assert f"## From `{unit().id}`" not in recorded(tmp_path)


# --- what may not be deferred ----------------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "point"),
    [
        ("correctness", "the lock is not released when the build raises"),
        ("test_passes_regardless", "test_release passes whether or not release() is called"),
        ("missing_test", "task 1.2 asks for a test of the timeout and there is none"),
        ("policy", "the build step pushes with --force, which the command policy forbids"),
    ],
)
def test_a_follow_up_that_may_not_wait_blocks_the_approval(
    tmp_path: Path, kind: str, point: str
) -> None:
    """Deferral is for work that can wait, not for work that is inconvenient."""
    recorder = fresh(tmp_path)
    recorder.verdicts = [approval_with({"kind": kind, "point": point}), approving()]

    outcome = build(tmp_path, recorder)

    assert recorder.events.count("review") == 2, "the first verdict did not approve"
    assert "claude:rework" in recorder.events
    rework_prompt = next(p for p in recorder.prompts if "review of this branch" in p)
    assert point in rework_prompt, "sent back as blocking"
    assert point not in recorded(tmp_path)
    assert outcome.status == "open"


def test_a_follow_up_that_may_not_wait_is_never_approved_on_the_last_round(
    tmp_path: Path,
) -> None:
    total = active().limits.max_review_rounds
    recorder = fresh(tmp_path)
    recorder.verdicts = [
        approval_with({"kind": "correctness", "point": "the cache is never invalidated"})
    ] * total

    outcome = build(tmp_path, recorder)

    assert outcome.status == "held"
    assert recorder.store.get(unit().id).approved == ""


# --- spent rounds and a stop before the push ---------------------------------------------


def test_spent_rounds_keep_the_units_recorded_follow_ups_in_the_pr_body(tmp_path: Path) -> None:
    total = active().limits.max_review_rounds
    recorder = fresh(tmp_path)
    recorder.verdicts = [approval_with(optional(LOCK))]
    build(tmp_path, recorder)

    recorder.store.set_feedback(unit().id, "tidy the error message")
    recorder.verdicts = [verdict(feedback="the timeout is still wrong")] * total
    bodies: list[str] = []
    outcome = build(tmp_path, recorder, open_pr=capturing(recorder, bodies))

    assert outcome.status == "held"
    assert recorder.store.get(unit().id).state == HELD
    assert "the timeout is still wrong" in bodies[-1]
    assert LOCK in bodies[-1], "the follow-up is not lost with the body's replacement"


def test_a_unit_that_stops_between_approval_and_push_keeps_its_follow_ups(
    tmp_path: Path,
) -> None:
    """The follow-ups belong to the approval, not to the run that got it: a
    unit that dies after review resumes with no review to repeat them."""
    recorder = fresh(tmp_path)
    recorder.verdicts = [approval_with(optional(LOCK))]
    dying = {"armed": True}

    def stops_once_reviewed(u: Any) -> tuple[Cause, str] | None:
        if dying["armed"] and recorder.events.count("review"):
            dying["armed"] = False
            raise Killed("power loss between approval and push")
        return None

    with pytest.raises(Killed):
        build(tmp_path, recorder, upstream_incomplete=stops_once_reviewed)
    assert "push" not in recorder.events
    assert LOCK not in recorded(tmp_path), "nothing is recorded ahead of the push"

    bodies: list[str] = []
    outcome = build(tmp_path, recorder, open_pr=capturing(recorder, bodies))

    assert outcome.status == "open"
    assert recorder.events.count("review") == 1, "resumed past the review"
    assert recorded(tmp_path).count(LOCK) == 1
    assert LOCK in bodies[0]


def test_a_multi_line_follow_up_is_recorded_and_read_back_as_one_item(tmp_path: Path) -> None:
    point = "Rename the lock:\nit guards the registry,\n- not the tick"
    recorder = fresh(tmp_path)
    recorder.verdicts = [approval_with(optional(point), optional("  \n "))]
    bodies: list[str] = []

    build(tmp_path, recorder, open_pr=capturing(recorder, bodies))

    lines = [line for line in recorded(tmp_path).splitlines() if line.startswith("- ")]
    assert lines == [f"- {flat(point)}"]
    later = bodies[0].split("Left for later", 1)[1]
    items = [line for line in later.splitlines() if line.startswith("- ")]
    assert len(items) == 1
    assert all(part in items[0] for part in ("Rename the lock:", "registry,", "not the tick"))


# --- an escalation and the last gate -------------------------------------------------


def test_an_escalation_with_no_earlier_round_is_an_ordinary_rejection(tmp_path: Path) -> None:
    """A class escalation needs an earlier round to be another instance of.
    Round one has none, so the verdict goes to rework instead of holding the
    unit with nothing behind it."""
    recorder = fresh(tmp_path)
    recorder.verdicts = [
        verdict(
            feedback="this pattern cannot be enumerated",
            escalate="class",
            reasoning="a list of spellings for this cannot be complete",
        ),
        approving(),
    ]

    outcome = build(tmp_path, recorder)

    assert recorder.events.count("review") == 2, "round one did not hold the unit"
    assert "claude:rework" in recorder.events
    assert outcome.status == "open"
    assert recorder.store.get(unit().id).state != HELD


def test_spending_the_rounds_still_checks_the_last_gate_before_a_push(tmp_path: Path) -> None:
    """A base that moved underneath the build would put the parent's old commits
    in this unit's diff; running out of rounds must not skip the gate before the push."""
    total = active().limits.max_review_rounds
    recorder = fresh(tmp_path)
    recorder.verdicts = [verdict(feedback="still no")] * total

    outcome = build(
        tmp_path,
        recorder,
        upstream_incomplete=lambda u: (
            (Cause.BASE_CHANGED, "its base moved while the rounds ran")
            if recorder.events.count("review") >= total
            else None
        ),
    )

    assert outcome.status == "held"
    assert "push" not in recorder.events
    assert "pr" not in recorder.events
    stored = recorder.store.get(unit().id)
    assert stored.state == PLANNED
    assert "still no" in stored.feedback, "the last round's points survive the hold"
