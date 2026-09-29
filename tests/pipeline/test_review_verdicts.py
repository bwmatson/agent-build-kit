"""How a unit's review loop ends.

A verdict used to say "approved" or "not yet", and running out of rounds threw
the unit's work away. These tests hand the loop each verdict shape a reviewer
can now give — approve with follow-ups, escalate an open-ended class, escalate
a repeated disagreement — and check what becomes of a unit whose rounds run
out: its branch pushed, its open points on the PR, the unit held for a person.

The reviewer is faked at its boundary: the raw JSON reply the review run
returns, which the loop parses.
"""

import json
from pathlib import Path

import pytest

from agent_build_kit.config import active
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import HELD, IN_REVIEW
from tests.factories import unit
from tests.pipeline.test_stack_runner import Recorder, make_runner

FOLLOW_UPS = Path("openspec") / "changes" / "add-marker" / "follow-ups.md"


def _flat(text: str) -> str:
    return " ".join(text.split())


def _verdict(**fields: object) -> str:
    return json.dumps({"approved": False, "feedback": "", **fields})


def _capturing_prs(runner, bodies: list[str]):
    def open_pr(unit, *, body: str, base: str, cwd: Path) -> int:
        bodies.append(body)
        return runner.open_pr(unit, body=body, base=base, cwd=cwd)

    return runner.model_copy(update={"open_pr": open_pr})


# 1.1 — the round note


def test_every_round_is_told_its_number_what_is_left_and_what_running_out_costs(
    tmp_path: Path,
) -> None:
    """A reviewer that knows the cost can weigh a residual nit against losing a
    correct implementation — the judgement it is already asked to make."""
    total = active().limits.max_review_rounds
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    recorder = Recorder()
    recorder.verdicts = [_verdict(feedback="the lock is not released on error")] * total

    make_runner(store, recorder, tmp_path).run(unit(), base="main", graph=[])

    assert len(recorder.contexts) == total
    for number, context in enumerate(recorder.contexts, start=1):
        note = _flat(context).lower()
        assert f"round {number} of {total}" in note, "the first round is told too"
        assert f"{total - number} remaining" in note
        assert "not merged" in note, "what ending without approval costs"


def test_the_final_round_says_it_is_final(tmp_path: Path) -> None:
    total = active().limits.max_review_rounds
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    recorder = Recorder()
    recorder.verdicts = [_verdict(feedback="still no")] * total

    make_runner(store, recorder, tmp_path).run(unit(), base="main", graph=[])

    assert "final round" in _flat(recorder.contexts[-1]).lower()
    assert all("final round" not in _flat(c).lower() for c in recorder.contexts[:-1])


# 1.2 — approve with follow-ups


def test_an_approval_with_follow_ups_approves_and_records_them_against_the_change(
    tmp_path: Path,
) -> None:
    """One optional observation is worth recording, not worth another round.
    Recorded where the change's next unit and the PR's reviewer see it, not
    only in a log."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit(), unit("add-marker/2", groups=(2,))])
    recorder = Recorder()
    recorder.verdicts = [
        json.dumps(
            {
                "approved": True,
                "feedback": "",
                "needs_human": False,
                "follow_ups": [{"kind": "optional", "point": "Name the lock after what it guards"}],
            }
        )
    ]
    bodies: list[str] = []
    runner = _capturing_prs(make_runner(store, recorder, tmp_path), bodies)

    outcome = runner.run(unit(), base="main", graph=[])

    assert outcome.status == "open"
    assert recorder.events.count("review") == 1, "no further round"
    assert "claude:rework" not in recorder.events
    assert store.get(unit().id).state == IN_REVIEW
    assert store.get(unit().id).approved, "approved at the reviewed commit"

    recorded = tmp_path / "meta" / FOLLOW_UPS
    assert "Name the lock after what it guards" in recorded.read_text()
    assert "Name the lock after what it guards" in bodies[0]

    later = Recorder()
    make_runner(store, later, tmp_path).run(
        store.get("add-marker/2"), base="spec/add-marker/1", graph=[]
    )
    assert "Name the lock after what it guards" in later.prompts[0], (
        "the change's next unit is built knowing what was left"
    )


def test_the_reviewer_is_told_what_it_may_defer_and_when_to_escalate() -> None:
    from agent_build_kit.pipeline.wiring import REVIEW_PROMPT

    review = _flat(REVIEW_PROMPT)
    for field in ('"follow_ups"', '"escalate"', '"reasoning"'):
        assert field in review, f"the reply format carries {field}"
    for kind in ("correctness", "test_passes_regardless", "missing_test", "policy"):
        assert kind in review, f"{kind} is named as never deferrable"
    assert '"class"' in review
    assert '"disagreement"' in review


# 1.3 — what may not be deferred


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
    """Deferral is for work that can wait, not for work that is inconvenient:
    wrong behaviour, a test that tests nothing, a missing test the task asked
    for and anything the policy forbids go back to the builder."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    recorder = Recorder()
    recorder.verdicts = [
        json.dumps(
            {"approved": True, "feedback": "", "follow_ups": [{"kind": kind, "point": point}]}
        ),
        '{"approved": true, "feedback": ""}',
    ]
    runner = make_runner(store, recorder, tmp_path)

    outcome = runner.run(unit(), base="main", graph=[])

    assert recorder.events.count("review") == 2, "the first verdict did not approve"
    assert "claude:rework" in recorder.events
    rework_prompt = next(p for p in recorder.prompts if "review of this branch" in p)
    assert point in rework_prompt, "sent back as blocking"
    recorded = tmp_path / "meta" / FOLLOW_UPS
    assert not recorded.exists() or point not in recorded.read_text()
    assert outcome.status == "open"


def test_a_follow_up_that_may_not_wait_is_never_approved_on_the_last_round(
    tmp_path: Path,
) -> None:
    total = active().limits.max_review_rounds
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    recorder = Recorder()
    blocked = json.dumps(
        {
            "approved": True,
            "feedback": "",
            "follow_ups": [{"kind": "correctness", "point": "the cache is never invalidated"}],
        }
    )
    recorder.verdicts = [blocked] * total

    outcome = make_runner(store, recorder, tmp_path).run(unit(), base="main", graph=[])

    assert outcome.status == "held"
    assert store.get(unit().id).approved == ""


# 1.4 — escalations


def test_an_open_ended_class_holds_the_unit_with_the_reasoning(tmp_path: Path) -> None:
    """Each round finds another way to reach the same forbidden effect. The
    list cannot be finished, so another round spent on the next instance is
    wasted; the approach needs changing, and that is a person's call."""
    reasoning = (
        "Round 1 found global options, this round finds quoted refspecs: a list of "
        "spellings for a push cannot be complete. The approach needs changing."
    )
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    recorder = Recorder()
    recorder.verdicts = [
        _verdict(feedback="`git -c x=y push` bypasses the pattern"),
        _verdict(
            feedback="`git push 'HEAD:main'` bypasses the pattern",
            escalate="class",
            reasoning=reasoning,
        ),
    ]

    outcome = make_runner(store, recorder, tmp_path).run(unit(), base="main", graph=[])

    assert outcome.status == "held"
    assert recorder.events.count("review") == 2, "no round spent on the next instance"
    assert recorder.events.count("claude:rework") == 1
    stored = store.get(unit().id)
    assert stored.state == HELD
    assert reasoning in stored.feedback, "the record says the approach needs changing"
    assert "The approach needs changing" in stored.history[-1]["note"]
    assert stored.approved == ""
    assert "push" not in recorder.events


def test_a_point_raised_again_after_the_builder_declined_it_holds_the_unit(
    tmp_path: Path,
) -> None:
    """A third exchange of prose is the least likely thing to settle it."""
    builder = (
        "Declined: the registry is only touched from the tick's thread, so a lock adds nothing."
    )
    reviewer = "The poller also writes the registry, from its own thread."
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    recorder = Recorder()
    recorder.verdicts = [
        _verdict(feedback="Guard the registry with a lock."),
        _verdict(
            feedback="Guard the registry with a lock.",
            escalate="disagreement",
            reasoning=reviewer,
        ),
    ]
    runner = make_runner(store, recorder, tmp_path).model_copy(
        update={"run_rework": lambda prompt, *, cwd: builder}
    )

    outcome = runner.run(unit(), base="main", graph=[])

    assert outcome.status == "held"
    assert recorder.events.count("review") == 2, "no third exchange"
    stored = store.get(unit().id)
    assert stored.state == HELD
    assert builder in stored.feedback, "the builder's position is on the record"
    assert reviewer in stored.feedback, "and the reviewer's"
    assert "disagree" in stored.history[-1]["note"].lower()
    assert stored.approved == ""


# 1.5 — spent rounds


def test_spent_rounds_push_the_branch_report_the_points_and_hold_the_unit(
    tmp_path: Path,
) -> None:
    """A person inherits a branch and a list, not an abandoned worktree."""
    total = active().limits.max_review_rounds
    tasks = tmp_path / "meta" / "openspec" / "changes" / "add-marker" / "tasks.md"
    tasks.parent.mkdir(parents=True)
    tasks.write_text("## 1. [app] [tier1] G\n- [ ] 1.1 Test: a\n- [ ] 1.2 Do a\n")
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    recorder = Recorder()
    recorder.verdicts = [
        _verdict(feedback="the child's branch lock is taken before RUNNING is written")
    ] * total
    statuses: list[bool] = []
    bodies: list[str] = []
    runner = _capturing_prs(
        make_runner(store, recorder, tmp_path).model_copy(
            update={"post_status": lambda sha, ok: statuses.append(ok)}
        ),
        bodies,
    )

    outcome = runner.run(unit(), base="main", graph=[])

    assert outcome.status == "held"
    assert recorder.events.count("review") == total
    assert "push" in recorder.events, "the branch is pushed, not left in a worktree"
    assert recorder.events.index("push") < recorder.events.index("pr")
    assert "the child's branch lock is taken before RUNNING is written" in bodies[-1]

    stored = store.get(unit().id)
    assert stored.state == HELD
    assert stored.approved == "", "nothing is marked approved"
    assert True not in statuses, "no passing status for unapproved work"
    assert "- [x]" not in tasks.read_text(), "no task is recorded as done"
