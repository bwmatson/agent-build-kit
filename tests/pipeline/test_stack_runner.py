"""Driving one unit from planned to open PR.

This is where every other piece is finally sequenced, and the sequence *is*
the guarantee. Almost all of these tests are about order and refusal rather
than output:

- nothing starts when the usage window is low,
- tests are written and committed before any implementation,
- the review pass only runs if there was something to review,
- tier 2 passes before anything is pushed,
- the commit status is posted after the push, never before,
- and a failure anywhere leaves no PR behind.

Side effects are injected, so these run in milliseconds and assert the shape
of the run rather than shelling out to Claude, git and gh.
"""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.pipeline.restack import HostMoved
from agent_build_kit.pipeline.stack_runner import Restacked, UnitRunner
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import IN_REVIEW
from tests.factories import stored_unit, unit
from tests.graph_driver import run_on_graph


class Recorder:
    """Stands in for every side effect, recording what happened in order."""

    tier1_output: str = ""

    def __init__(
        self,
        *,
        commits_from_impl: int = 1,
        tier2_ok: bool = True,
        tier1_ok: bool = True,
        close_error: str = "",
    ):
        self.events: list[str] = []
        self.prompts: list[str] = []
        self.commits_from_impl = commits_from_impl
        self.tier2_ok = tier2_ok
        self.tier1_ok = tier1_ok
        # Answers for successive tier 1 runs, in order; once spent, `tier1_ok`.
        self.tier1_results: list[tuple[bool, str]] = []
        self.pushed_shas: list[str] = []
        self.close_error = close_error
        self.closed: list[tuple[str, int, str]] = []
        self.logged: list[str] = []

    def claude(
        self,
        prompt: str,
        *,
        cwd: Path,
        resume_session: str = "",
        on_session: Callable[[str], None] | None = None,
    ) -> str:
        self.prompts.append(prompt)
        if "checks (lint" in prompt:
            self.events.append("claude:fix_checks")
        elif "Review asked for" in prompt or "review of this branch" in prompt:
            self.events.append("claude:rework")
        else:
            self.events.append("claude:tests" if "test tasks" in prompt else "claude:impl")
        return "done"

    verdicts: list[str] = []

    contexts: list[str]

    def review(
        self,
        *,
        cwd: Path,
        context: str = "",
        resume_session: str = "",
        on_session: Callable[[str], None] | None = None,
    ) -> str:
        """Takes `context` as the real review does: a fake that did not hid
        that the real one did not, and a review crashed in the field."""
        self.contexts = [*getattr(self, "contexts", []), context]
        self.events.append("review")
        return self.verdicts.pop(0) if self.verdicts else '{"approved": true, "feedback": ""}'

    made: int = 0

    def commit(self, message: str, *, cwd: Path) -> int:
        self.events.append(f"commit:{message.split(':')[0]}")
        count = 1 if "test" in message else self.commits_from_impl
        self.made += count
        return count

    def branch_commits(self, cwd: Path, base: str) -> int:
        """What is on the branch: every commit made so far."""
        return self.made

    def head(self, cwd: Path) -> str:
        """Moves with every commit, as a real HEAD does."""
        return f"sha-{self.made}"

    def tier1(self, *, cwd: Path, base: str = "main", whole_repo: bool = False) -> tuple[bool, str]:
        self.events.append("tier1:whole_repo" if whole_repo else "tier1")
        if self.tier1_results:
            return self.tier1_results.pop(0)
        return self.tier1_ok, self.tier1_output

    def tier2(self, *, cwd: Path) -> tuple[bool, str]:
        self.events.append("tier2")
        return self.tier2_ok, "## Tier 2 results\nfine"

    def push(self, branch: str, *, cwd: Path) -> str:
        self.events.append("push")
        self.pushed_shas.append("abc123")
        return "abc123"

    def open_pr(self, unit, *, body: str, base: str, cwd: Path, **bodies: str) -> int:
        self.events.append("pr")
        return 7

    def post_status(self, sha: str, ok: bool) -> None:
        self.events.append("status")

    def close_pr(self, unit, pr: int, reason: str) -> None:
        self.events.append("close")
        if self.close_error:
            raise RuntimeError(self.close_error)
        self.closed.append((unit.id, pr, reason))

    def log(self, message: str) -> None:
        self.logged.append(message)


@pytest.fixture
def runner(tmp_path: Path):
    def build(recorder: Recorder, *, may_start: bool = True, tier: str = "tier1") -> UnitRunner:
        store = UnitStore(tmp_path / "units.json")
        store.upsert([unit(tier=tier)])
        return UnitRunner(
            store=store,
            planning_repo=tmp_path / "meta",
            worktree=lambda u, base: tmp_path / "tree",
            may_start=lambda: (may_start, "usage fine" if may_start else "session at 88%"),
            run_claude=recorder.claude,
            run_rework=recorder.claude,
            run_review=recorder.review,
            run_rework_review=recorder.review,
            commit=recorder.commit,
            branch_commits=recorder.branch_commits,
            head=recorder.head,
            upstream_incomplete=lambda u: "",
            restack_onto=lambda **kw: None,
            run_tier1=recorder.tier1,
            run_tier2=recorder.tier2,
            push=recorder.push,
            open_pr=recorder.open_pr,
            post_status=recorder.post_status,
            close_pr=recorder.close_pr,
            log=recorder.log,
        )

    return build


def make_runner(store: UnitStore, recorder: Recorder, tmp_path: Path) -> UnitRunner:
    return UnitRunner(
        store=store,
        planning_repo=tmp_path / "meta",
        worktree=lambda u, base: tmp_path / "tree",
        may_start=lambda: (True, "usage fine"),
        run_claude=recorder.claude,
        run_rework=recorder.claude,
        run_review=recorder.review,
        run_rework_review=recorder.review,
        commit=recorder.commit,
        branch_commits=recorder.branch_commits,
        head=recorder.head,
        upstream_incomplete=lambda u: "",
        restack_onto=lambda **kw: None,
        run_tier1=recorder.tier1,
        run_tier2=recorder.tier2,
        push=recorder.push,
        open_pr=recorder.open_pr,
        post_status=recorder.post_status,
        close_pr=recorder.close_pr,
        log=recorder.log,
    )


def approving(_: str = "") -> str:
    return '{"approved": true, "feedback": ""}'


def rejecting(reason: str) -> str:
    return json.dumps({"approved": False, "feedback": reason})


class MovedOnceRecorder(Recorder):
    """A push that finds the host moved the branch, then holds on the second."""

    def __init__(self) -> None:
        super().__init__()
        self.pushes = 0
        self.bodies: list[dict[str, str]] = []

    def push(self, branch: str, *, cwd: Path) -> str:
        self.pushes += 1
        if self.pushes == 1:
            raise HostMoved("the host moved the branch; adopted its head")
        return "abc123"

    def open_pr(self, unit, *, body: str, base: str, cwd: Path, **bodies: str) -> int:
        self.bodies.append({"body": body, **bodies})
        return super().open_pr(unit, body=body, base=base, cwd=cwd)


class Gate:
    """A usage guard that says yes a set number of times, then no."""

    def __init__(self, yes: int) -> None:
        self.yes = yes

    def __call__(self) -> tuple[bool, str]:
        self.yes -= 1
        return (self.yes >= 0, "usage fine" if self.yes >= 0 else "session usage at 75%")


def _tasks_file(tmp_path: Path) -> Path:
    tasks = tmp_path / "meta" / "openspec" / "changes" / "add-marker" / "tasks.md"
    tasks.parent.mkdir(parents=True)
    tasks.write_text("## 1. [app] [tier1] G\n- [ ] 1.1 Test: a\n- [ ] 1.2 Do a\n")
    return tasks


class SelfCommitting(Recorder):
    """An agent that commits its own work, leaving the pipeline nothing."""

    def claude(self, prompt: str, *, cwd: Path, **session: Any) -> str:
        self.made += 1
        return super().claude(prompt, cwd=cwd, **session)

    def commit(self, message: str, *, cwd: Path) -> int:
        self.events.append(f"commit:{message.split(':')[0]}")
        return 0


def _bodies_sent(tmp_path: Path, *, linear: bool) -> dict[str, str]:
    """What the runner hands `open_pr` for a unit stacked on an open parent."""
    parent = stored_unit("add-marker/1", state=IN_REVIEW, pr=4, branch="spec/add-marker/1")
    child = unit("add-marker/2", depends_on=("add-marker/1",))
    store = UnitStore(tmp_path / "units.json")
    store.upsert([parent, child])
    sent: dict[str, str] = {}

    def open_pr(u, *, body: str, base: str, cwd: Path, stacked_body: str) -> int:
        sent.update(body=body, stacked_body=stacked_body)
        return 7

    runner = make_runner(store, Recorder(), tmp_path).model_copy(
        update={"open_pr": open_pr, "linear": lambda tree, base: linear}
    )
    run_on_graph(runner, child, base="spec/add-marker/1", graph=[parent, store.get(child.id)])
    return sent


def test_the_body_leaves_the_order_to_a_host_that_renders_stacks(tmp_path: Path) -> None:
    """Both bodies go to `open_pr`, which alone learns whether the host put
    the PR in a stack: the one for no stack states the order, the other
    leaves it to the host."""
    sent = _bodies_sent(tmp_path, linear=True)

    assert "Stacked on" in sent["body"]
    assert "Stacked on" not in sent["stacked_body"]


@pytest.mark.parametrize("which", ["body", "stacked_body"])
def test_a_branch_left_off_its_base_is_reported_as_not_linear(tmp_path: Path, which: str) -> None:
    """Checked in the tree by the runner, not assumed: whichever body the
    PR ends up with says the chain cannot merge until it is rebased."""
    assert "not linear" in _bodies_sent(tmp_path, linear=False)[which].lower()
    assert "not linear" not in _bodies_sent(tmp_path / "linear", linear=True)[which].lower()


def _once(result: Restacked) -> Callable[..., Restacked | None]:
    """A restack that moves the branch at the start of the run and finds it
    already on its base when asked again before the push."""
    answers = iter([result])
    return lambda **kw: next(answers, None)


def _restacked(**overrides) -> Restacked:
    fields: dict = {
        "onto_unit": "c/2",
        "onto_intent": "the MCP surface",
        "old_base": "a",
        "old_head": "b",
    }
    return Restacked(**{**fields, **overrides})


def _reviews_seen(recorder: Recorder) -> tuple[list[str], list[str]]:
    """(which reviewer, context given) for each review."""
    who: list[str] = []
    contexts: list[str] = []
    original = recorder.review

    def standard(*, cwd: Path, context: str = "") -> str:
        who.append("standard")
        contexts.append(context)
        return original(cwd=cwd)

    def rework(*, cwd: Path, context: str = "") -> str:
        who.append("rework")
        contexts.append(context)
        return original(cwd=cwd)

    recorder.standard_review, recorder.rework_review = standard, rework  # type: ignore[attr-defined]
    return who, contexts


def test_what_counts_as_accounting_for_a_test() -> None:
    from agent_build_kit.pipeline.stack_runner import PortedTest, check_test_decisions

    def d(name: str, decision: str, reason: str = "") -> PortedTest:
        return PortedTest(name=name, decision=decision, reason=reason)

    present = {"test_a", "test_b_v2"}
    assert check_test_decisions(["test_a"], [d("test_a", "keep")], present) == []
    assert (
        check_test_decisions(
            ["test_b"], [d("test_b", "adapt", "renamed to test_b_v2 for the new shape")], present
        )
        == []
    )
    assert check_test_decisions(["test_c"], [d("test_c", "retire", "moot")], present) == [
        "`test_c` retired without a reason naming the predecessor's change"
    ]
    assert check_test_decisions(["test_d"], [d("test_d", "keep")], present) == [
        "`test_d` is marked keep but is not in the tree"
    ]


def test_a_changed_test_cannot_be_answered_keep() -> None:
    from agent_build_kit.pipeline.stack_runner import PortedTest, check_test_decisions

    present = {"test_a"}
    kept = [PortedTest(name="test_a", decision="keep")]
    adapted = [PortedTest(name="test_a", decision="adapt", reason="relaxed to fit the new shape")]

    problems = check_test_decisions(["test_a"], kept, present, changed={"test_a"})
    assert problems == [
        "`test_a` is marked keep but differs from the previous work — mark it "
        "adapt and say what changed"
    ]
    assert check_test_decisions(["test_a"], adapted, present, changed={"test_a"}) == []
    assert check_test_decisions(["test_a"], [], present, changed={"test_a"}) == [
        "no decision for `test_a`, which differs from the previous work — mark it "
        "adapt and say what changed, or retire it with a reason"
    ]
    assert check_test_decisions(["test_b"], [], present=set(), changed={"test_b"}) == [
        "no decision for `test_b`, which is no longer in the tree — retire it with a reason "
        "naming what in the predecessor made it invalid, or mark it adapt and name the test "
        "that replaced it"
    ]


def test_only_the_uncertain_tests_need_a_decision() -> None:
    """A test the replay left alone is not asked about at all; one that
    vanished, or that survived in changed form, still must be."""
    from agent_build_kit.pipeline.stack_runner import tests_needing_decision

    # present and unchanged by the replay: no decision required
    assert tests_needing_decision(["test_a"], present={"test_a"}, changed=set()) == []
    # missing from the tree: still required
    assert tests_needing_decision(["test_b"], present=set(), changed=set()) == ["test_b"]
    # present, but the replay changed it: still required
    assert tests_needing_decision(["test_c"], present={"test_c"}, changed={"test_c"}) == ["test_c"]
    # a mix keeps only the uncertain ones
    assert tests_needing_decision(
        ["test_a", "test_b", "test_c"], present={"test_a", "test_c"}, changed={"test_c"}
    ) == ["test_b", "test_c"]


def test_the_silent_drop_guard_still_holds_over_the_narrowed_list() -> None:
    """Narrowing which tests must be accounted for must not narrow what makes
    an accounting wrong: a false keep or a bare retirement is still a problem
    once the test is one of the ones actually asked about."""
    from agent_build_kit.pipeline.stack_runner import (
        PortedTest,
        check_test_decisions,
        tests_needing_decision,
    )

    old_tests = ["test_a", "test_b"]
    present = {"test_a"}  # test_b vanished in the replay
    required = tests_needing_decision(old_tests, present=present, changed=set())

    claims_kept = [
        PortedTest(name="test_a", decision="keep"),
        PortedTest(name="test_b", decision="keep"),
    ]
    assert check_test_decisions(required, claims_kept, present) == [
        "`test_b` is marked keep but is not in the tree"
    ]

    bare_retirement = [
        PortedTest(name="test_a", decision="keep"),
        PortedTest(name="test_b", decision="retire", reason="moot"),
    ]
    assert check_test_decisions(required, bare_retirement, present) == [
        "`test_b` retired without a reason naming the predecessor's change"
    ]


def test_reviews_are_asked_to_sweep_and_to_say_what_done_looks_like() -> None:
    from agent_build_kit.pipeline.stack_runner import REVIEW_FEEDBACK_PROMPT
    from agent_build_kit.pipeline.wiring import REVIEW_PROMPT

    review, fix = " ".join(REVIEW_PROMPT.split()), " ".join(REVIEW_FEEDBACK_PROMPT.split())
    assert "Find everything in one pass" in review
    assert "Sweep the domain" in review
    assert "Say what done looks like" in review
    assert "look for others of the same kind" in fix
    assert "point by point" in fix


def test_reviews_check_that_tests_hold_the_code_to_the_real_system() -> None:
    """A change can pass every review with tests whose fakes encode the
    implementation's own assumptions: a fake counting a call as the effect
    the real one does not have, a fake returning plain values where the real
    API wraps them, hand-written events with none of the real system's
    metadata. All of those are bugs live, found in minutes by driving the
    real server."""
    from agent_build_kit.pipeline.wiring import REVIEW_PROMPT

    review = " ".join(REVIEW_PROMPT.split())
    assert "Check the tests against the real system" in review
    assert "would it still pass if the real" in review
    assert "protocol boundary" in review
    assert "recorded from the real system" in review


def test_test_writers_fake_at_the_boundary_and_record_real_fixtures() -> None:
    from agent_build_kit.pipeline.stack_runner import TESTS_PROMPT

    tests = " ".join(TESTS_PROMPT.split())
    assert "protocol boundary" in tests
    assert "recorded from the real system" in tests


def test_needs_human_only_counts_alongside_a_rejection() -> None:
    from agent_build_kit.pipeline.stack_runner import parse_verdict

    assert parse_verdict('{"approved": false, "feedback": "x", "needs_human": true}').needs_human
    assert not parse_verdict('{"approved": false, "feedback": "x"}').needs_human
    assert not parse_verdict("not json").needs_human


class CountingGate(Gate):
    """`Gate`, but remembering how many times it was asked — so a test can
    tell "the same check, reused" from "one more read than the boundary
    pattern already makes"."""

    def __init__(self, yes: int) -> None:
        super().__init__(yes)
        self.calls = 0

    def __call__(self) -> tuple[bool, str]:
        self.calls += 1
        return super().__call__()


# --- the checks before a review ------------------------------------------------
#
# A branch that does not lint, type-check or pass its tests is not worth a
# reviewer's time, and used to be found out only after the reviewer approved it.
# Now it goes back to the builder first, a bounded number of times.

FAILING = "ERROR implicit-any-empty-container\n  --> tests/test_x.py:3:5"


def checked_runner(
    tmp_path: Path, recorder: Recorder, **limits: int | None
) -> tuple[UnitRunner, UnitStore]:
    """A runner whose limits are the given ones; the suite's autouse fixture
    puts the config back afterwards."""
    from agent_build_kit import config as config_module

    current = config_module.active()
    config_module.activate(
        current.model_copy(update={"limits": current.limits.model_copy(update=limits)}),
        config_module.active_root(),
    )
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    return make_runner(store, recorder, tmp_path), store


# --- how many fix rounds, and when they count from -----------------------------
