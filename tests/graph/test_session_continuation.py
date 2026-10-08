"""A build node continues its role's session with a prompt of what is new, on the model the
session began on, and falls back to a new session with the full prompt
(docs/unit-graph.md, Session capture and resume).

The agent is a runtime behind the `AgentRuntime` seam, reached through the real
`build_run` and `build_run_review`: what a request carries is what is tested.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from agent_build_kit import config as config_module
from agent_build_kit.graph.state import SessionRole
from agent_build_kit.pipeline.run_log import RunLog
from agent_build_kit.pipeline.wiring import build_run, build_run_review
from agent_build_kit.runtimes import AgentRequest, AgentResult
from agent_build_kit.runtimes.base import SessionUnavailable
from tests.factories import unit
from tests.graph.agent_fakes import MODELS, distinct_models
from tests.graph.test_build_path import FAILING, build, once, restacked
from tests.graph_driver import fresh, position, tick
from tests.runner_fakes import Killed, Recorder, approving, rejecting
from tests.runtimes.stand_in import StandInRuntime

CHANGE_PATH = "openspec/changes/add-marker"
GROUPS = "group(s) 1"
REWORK_ASK = "the session registry leaks"
OLD_REF = "refs/spec-driven/pre-adapt/add-marker/1"


class Sessions(StandInRuntime):
    """A runtime that numbers the sessions it opens, continues one it is asked to, and
    answers a review with the next of `verdicts`. It refuses every continuation when
    `refuses` is set, and dies, as a power loss does, in request `die_on` once the
    session's id has been told."""

    name = "numbered"

    def __init__(
        self,
        *,
        resumes: bool = True,
        refuses: str = "",
        die_on: int = 0,
        verdicts: Sequence[str] = (),
    ) -> None:
        super().__init__(answer="done")
        self.supports_session_resume = resumes
        self.refuses = refuses
        self.die_on = die_on
        self.verdicts = list(verdicts)
        self.opened = 0

    @property
    def built(self) -> list[AgentRequest]:
        return [r for r in self.requests if r.role != "review"]

    @property
    def judged(self) -> list[AgentRequest]:
        return [r for r in self.requests if r.role == "review"]

    def run(self, request: AgentRequest) -> AgentResult:
        self.requests.append(request)
        if request.resume_session and self.refuses:
            raise SessionUnavailable(self.refuses)
        if request.resume_session:
            session = request.resume_session
        else:
            self.opened += 1
            session = f"sess-{self.opened}"
        if request.on_session:
            request.on_session(session)
        if len(self.requests) == self.die_on:
            raise Killed("power loss")
        reviewing = request.role == "review"
        answer = (self.verdicts.pop(0) if self.verdicts else approving()) if reviewing else "done"
        result = AgentResult(ok=True, text=answer, session_id=session)
        if request.on_result:
            request.on_result(result)
        return result


def reuse(*, build: bool) -> None:
    current = config_module.active()
    config_module.activate(
        current.model_copy(update={"session_reuse": {"build": build, "review": False}}),
        config_module.active_root(),
    )


def agents(runtime: Sessions) -> dict[str, Any]:
    """The three agent entry points over one runtime, as the real wiring builds them."""
    return {
        "run": build_run(runtime=runtime),
        "run_review": build_run_review(runtime=runtime),
        "run_rework_review": build_run_review(runtime=runtime, model=MODELS.rework_review),
    }


def failing_checks(recorder: Recorder) -> None:
    recorder.tier1_results = [(False, FAILING), (True, "")]


def logged(recorder: Recorder) -> str:
    return "\n".join(recorder.logged).lower()


def run_log(tmp_path: Path) -> RunLog:
    return RunLog(
        tmp_path / "unit-logs",
        unit(),
        step="build",
        model="m",
        base="main",
        started=datetime.now(UTC),
    )


def fix_request(runtime: Sessions) -> AgentRequest:
    """The build request that follows the tests' and the implementation's."""
    return runtime.built[2]


# --- fix_checks continues the build session ------------------------------------------


def test_fix_checks_resumes_the_build_session_with_the_failure_and_not_the_context(
    tmp_path: Path,
) -> None:
    distinct_models()
    recorder = fresh(tmp_path)
    failing_checks(recorder)
    runtime = Sessions()

    tick(tmp_path, recorder, **agents(runtime))

    tests, implement, fix = runtime.built
    assert tests.resume_session == ""
    assert fix.resume_session == "sess-1"
    assert fix.model == MODELS.implement, "the recorded model, not the rework one"
    assert FAILING in fix.prompt
    assert "check" in fix.prompt.lower(), "it is told to run the checks itself"
    assert CHANGE_PATH not in fix.prompt
    assert GROUPS not in fix.prompt
    assert implement.resume_session == "sess-1"


def test_with_reuse_off_fix_checks_starts_a_new_session_with_the_full_prompt_on_build_model(
    tmp_path: Path,
) -> None:
    distinct_models()
    reuse(build=False)
    recorder = fresh(tmp_path)
    failing_checks(recorder)
    runtime = Sessions()

    tick(tmp_path, recorder, **agents(runtime))

    *_, fix = runtime.built
    assert len(runtime.built) == 3
    assert fix.resume_session == ""
    assert fix.model == MODELS.implement, "not the rework model"
    assert FAILING in fix.prompt
    assert CHANGE_PATH in fix.prompt
    assert GROUPS in fix.prompt


def test_with_no_build_model_recorded_fix_checks_runs_on_the_configured_implement_model(
    tmp_path: Path,
) -> None:
    distinct_models()
    recorder = fresh(tmp_path)
    recorder.made = 2  # the unit enters with its work on the branch: no build node runs first
    failing_checks(recorder)
    runtime = Sessions()

    tick(tmp_path, recorder, branch_commits=lambda cwd, base: recorder.made, **agents(runtime))

    (fix, *_) = runtime.built
    assert FAILING in fix.prompt
    assert fix.resume_session == ""
    assert fix.model == MODELS.implement
    assert CHANGE_PATH in fix.prompt, "a cold start gets the full prompt"


# --- the ways a continuation is not possible ------------------------------------------


@pytest.mark.parametrize(
    ("runtime", "unreachable", "tried", "why"),
    [
        (Sessions(refuses="no conversation found with session id sess-1"), "", True, "found"),
        (Sessions(refuses="prompt is too long"), "", True, "too long"),
        (Sessions(resumes=False), "", False, "resume"),
        (Sessions(), "sha-2", False, "sha-2"),
    ],
    ids=["session-unavailable", "context-overflow", "runtime-cannot-resume", "head-unreachable"],
)
def test_a_session_that_cannot_be_continued_gives_a_new_one_with_the_full_prompt_and_says_why(
    tmp_path: Path, runtime: Sessions, unreachable: str, tried: bool, why: str
) -> None:
    distinct_models()
    recorder = fresh(tmp_path)
    failing_checks(recorder)

    tick(
        tmp_path,
        recorder,
        head_reachable=lambda tree, head: head != unreachable,
        run_log=run_log(tmp_path),
        **agents(runtime),
    )

    *_, last = runtime.built
    assert last.resume_session == ""
    assert last.model == MODELS.implement
    assert CHANGE_PATH in last.prompt and GROUPS in last.prompt and FAILING in last.prompt
    # the implement node continues the tests session; what is asked here is the fix node's attempt
    assert any(r.resume_session for r in runtime.built[2:-1]) is tried
    says = logged(recorder)
    assert "new session" in says
    assert why in says


class Switching(Sessions):
    """A runtime that is named `a` for the first two requests and `b` after."""

    name = "a"

    def run(self, request: AgentRequest) -> AgentResult:
        result = super().run(request)
        self.name = "a" if len(self.requests) < 2 else "b"
        return result


def test_a_session_another_runtime_recorded_is_not_continued_and_the_log_names_both(
    tmp_path: Path,
) -> None:
    distinct_models()
    recorder = fresh(tmp_path)
    failing_checks(recorder)
    runtime = Switching()

    tick(tmp_path, recorder, run_log=run_log(tmp_path), **agents(runtime))

    fix = fix_request(runtime)
    assert fix.resume_session == ""
    assert fix.model == MODELS.implement
    assert CHANGE_PATH in fix.prompt and GROUPS in fix.prompt and FAILING in fix.prompt
    says = logged(recorder)
    assert "new session" in says
    assert "belongs to a" in says and "runs on b" in says


def test_a_node_killed_mid_run_resumes_its_own_session_with_the_interruption_prompt(
    tmp_path: Path,
) -> None:
    distinct_models()
    recorder = fresh(tmp_path)
    failing_checks(recorder)
    runtime = Sessions(die_on=3)  # fix_checks, in the session it continued
    with pytest.raises(Killed):
        tick(tmp_path, recorder, **agents(runtime))
    assert runtime.built[2].resume_session == "sess-1"

    tick(tmp_path, recorder, **agents(runtime))

    again = runtime.built[3]
    assert again.resume_session == "sess-1"
    assert "interrupted" in again.prompt.lower()
    assert FAILING not in again.prompt, "the interruption prompt, not the continuation"


# --- review is its own session -----------------------------------------------------------


def test_review_never_resumes_in_a_second_round_or_from_a_build_session(tmp_path: Path) -> None:
    distinct_models()
    recorder = fresh(tmp_path)
    runtime = Sessions(verdicts=[rejecting(REWORK_ASK), approving()])

    tick(tmp_path, recorder, **agents(runtime))

    assert len(runtime.judged) == 2, "the reviews of both rounds"
    assert [r.resume_session for r in runtime.judged] == ["", ""]
    *_, rework = runtime.built
    assert rework.resume_session == "sess-1", "the author fixes what the judge found"
    assert rework.model == MODELS.implement, "a continuation runs on the model the session began on"
    assert REWORK_ASK in rework.prompt
    state = position(tmp_path).state
    assert state is not None
    assert state.sessions[SessionRole.REVIEW].session_id not in {"sess-1"}


# --- what moved since the session last spoke --------------------------------------------


def bumping(recorder: Recorder, *, moves: bool) -> Callable[..., tuple[bool, str]]:
    """Tier 1 as the recorder runs it, then a commit lands that no node made."""
    first = True

    def run_tier1(**kw: Any) -> tuple[bool, str]:
        nonlocal first
        result = recorder.tier1(**kw)
        if moves and first:
            recorder.made += 1
        first = False
        return result

    return run_tier1


def continuation(tmp_path: Path, *, moves: bool) -> str:
    distinct_models()
    where = tmp_path / ("moved" if moves else "still")
    where.mkdir()
    recorder = fresh(where)
    failing_checks(recorder)
    runtime = Sessions()
    tick(where, recorder, run_tier1=bumping(recorder, moves=moves), **agents(runtime))
    fix = fix_request(runtime)
    assert fix.resume_session == "sess-1"
    return fix.prompt


def test_a_moved_head_puts_the_two_hashes_first_with_no_log_or_diff(tmp_path: Path) -> None:
    moved = continuation(tmp_path, moves=True)
    still = continuation(tmp_path, moves=False)

    note = moved.split("\n\n")[0]
    assert "sha-2" in note and "sha-3" in note
    assert len(note) < 500, "two hashes and an instruction, not a log"
    assert moved.endswith(still), "the node's own prompt follows the note unchanged"


def test_equal_heads_add_no_note(tmp_path: Path) -> None:
    still = continuation(tmp_path, moves=False)

    assert "sha-" not in still
    assert FAILING in still


def test_after_adapts_reset_the_note_names_the_ref_holding_the_old_work(tmp_path: Path) -> None:
    distinct_models()
    recorder = fresh(tmp_path)
    runtime = Sessions()
    conflicts = iter([restacked(conflict="x", old_tests=())] * 2)

    def reset(tree: Path, onto: str, keep: str) -> None:
        recorder.made = 100  # the branch is on the new base

    build(
        tmp_path,
        recorder,
        base="spec/c/2",
        branch_commits=lambda cwd, base: recorder.made,
        restack_onto=lambda **kw: next(conflicts, None),
        reset_to=reset,
        tests_in=lambda tree: set(),
        tests_changed=lambda tree, ref: set(),
        **agents(runtime),
    )

    adapt = fix_request(runtime)
    assert adapt.resume_session == "sess-1"
    note = adapt.prompt.split("\n\n")[0]
    assert "sha-2" in note and "sha-100" in note
    assert OLD_REF in adapt.prompt


# --- which nodes continue which --------------------------------------------------------


def test_implement_continues_the_session_tests_started_with_what_is_new(tmp_path: Path) -> None:
    distinct_models()
    recorder = fresh(tmp_path)
    runtime = Sessions()

    tick(tmp_path, recorder, **agents(runtime))

    tests, implement = runtime.built
    assert tests.resume_session == ""
    assert CHANGE_PATH in tests.prompt, "a cold start gets the full prompt"
    assert implement.resume_session == "sess-1"
    assert implement.model == MODELS.implement
    assert "implement" in implement.prompt.lower()
    assert CHANGE_PATH not in implement.prompt
    assert GROUPS not in implement.prompt


def test_adapt_continues_the_build_session_and_keeps_the_contract_of_its_answer(
    tmp_path: Path,
) -> None:
    distinct_models()
    recorder = fresh(tmp_path)
    runtime = Sessions()
    conflicts = iter([restacked(conflict="the conflict text", old_tests=())] * 2)

    build(
        tmp_path,
        recorder,
        base="spec/c/2",
        branch_commits=lambda cwd, base: recorder.made,
        restack_onto=lambda **kw: next(conflicts, None),
        reset_to=lambda tree, onto, keep: None,
        tests_in=lambda tree: set(),
        tests_changed=lambda tree, ref: set(),
        **agents(runtime),
    )

    adapt = fix_request(runtime)
    assert adapt.resume_session == "sess-1"
    assert adapt.model == MODELS.implement, "the session's recorded model"
    for kept in ("c/2", "the conflict text", OLD_REF, "keep|adapt|retire"):
        assert kept in adapt.prompt
    assert CHANGE_PATH not in adapt.prompt
    assert GROUPS not in adapt.prompt


def test_a_unit_entering_at_adapt_starts_the_build_session_and_a_later_node_continues_it(
    tmp_path: Path,
) -> None:
    distinct_models()
    recorder = fresh(tmp_path)
    failing_checks(recorder)
    runtime = Sessions()

    build(
        tmp_path,
        recorder,
        base="spec/c/2",
        branch_commits=lambda cwd, base: 2 + recorder.made,
        restack_onto=once(restacked(conflict="x", old_tests=())),
        reset_to=lambda tree, onto, keep: None,
        tests_in=lambda tree: set(),
        tests_changed=lambda tree, ref: set(),
        **agents(runtime),
    )

    adapt, fix = runtime.built
    assert adapt.resume_session == ""
    assert CHANGE_PATH in adapt.prompt, "a cold start gets the full prompt"
    assert adapt.model == MODELS.rework
    assert fix.resume_session == "sess-1"
    assert fix.model == MODELS.rework, "the model the build session started on"
    assert FAILING in fix.prompt
