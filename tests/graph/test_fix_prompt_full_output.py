"""An e2e-test fix prompt names the file holding the full output, and does not tell the agent
to rerun live tests it cannot run; a unit-test prompt is as it always was.

The saved feedback is rendered through the rework node, with the agent a runtime behind
the `AgentRuntime` seam: the first prompt of a new session, and the continuation of the
build session when session reuse is on.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.graph.state import EventKind, ResumeEvent
from agent_build_kit.pipeline.e2e import E2eResult, build_snapshot
from agent_build_kit.pipeline.stack_runner import CHECKS_CONTINUATION, CHECKS_PROMPT
from agent_build_kit.pipeline.unit_store import FeedbackSource, RequeueReason
from tests.factories import unit
from tests.graph.agent_fakes import distinct_models
from tests.graph.test_session_continuation import Sessions, agents, reuse
from tests.graph_driver import fresh, tick

UNIT = unit().id
LOG = "runs/e2e-output/unit-1.log"
UNIT_TEST_FEEDBACK = "unit-test failed:\nFAILED tests/test_foo.py::test_foo"
RUN_YOURSELF = "run the checks yourself"
NO_RERUN = "cannot rerun"


def e2e_feedback(*, output_file: str = LOG, withheld: bool = False) -> str:
    result = E2eResult(
        sha="abcdef0123",
        passed=3,
        failed=1,
        skipped=0,
        duration_seconds=1.5,
        command="uv run pytest -m local_stack",
        output="output line\nTAIL FAILED tests/test_bar.py::test_bar",
        output_file=output_file,
        output_withheld=withheld,
    )
    return f"e2e-test failed:\n{build_snapshot(result)}"


def failed_twice(first: str, second: str, *, withheld: bool = False) -> str:
    """Two failures saved as the node saves the second: added to the first's feedback."""
    latest = e2e_feedback(output_file=second, withheld=withheld)
    return f"{e2e_feedback(output_file=first)}\n\n{latest}"


def reworked(tmp_path: Path, feedback: str, source: FeedbackSource, *, resumes: bool) -> str:
    """The prompt the rework of a unit with this saved failure sends: the continuation of
    its build session when `resumes`, else the full prompt of a new one."""
    distinct_models()
    reuse(build=resumes)
    recorder = fresh(tmp_path)
    runtime = Sessions()
    tick(tmp_path, recorder, **agents(runtime))
    recorder.store.set_feedback(UNIT, feedback, source=source)
    event = ResumeEvent(
        kind=EventKind.REQUEUE, reason="requeue", requeue=RequeueReason.FROM_FAILURE
    )
    tick(tmp_path, recorder, event=event, **agents(runtime))
    tick(tmp_path, recorder, **agents(runtime))
    last = runtime.built[-1]
    assert bool(last.resume_session) is resumes
    return last.prompt


@pytest.mark.parametrize("resumes", [False, True], ids=["prompt", "continuation"])
def test_an_e2e_failure_with_a_file_names_it_and_says_the_live_tests_cannot_be_rerun(
    tmp_path: Path, resumes: bool
) -> None:
    prompt = reworked(tmp_path, e2e_feedback(), FeedbackSource.E2E, resumes=resumes)

    assert LOG in prompt.split("---")[-1], "named in the instruction, past the feedback"
    assert "cut short" in prompt
    assert "grep" in prompt and "sed" in prompt
    assert NO_RERUN in prompt
    assert RUN_YOURSELF not in " ".join(prompt.lower().split())


@pytest.mark.parametrize("resumes", [False, True], ids=["prompt", "continuation"])
@pytest.mark.parametrize("withheld", [True, False], ids=["withheld", "no-file"])
def test_an_e2e_failure_without_a_readable_file_names_none_and_says_it_cannot_be_rerun(
    tmp_path: Path, withheld: bool, resumes: bool
) -> None:
    feedback = e2e_feedback(output_file=LOG if withheld else "", withheld=withheld)

    prompt = reworked(tmp_path, feedback, FeedbackSource.E2E, resumes=resumes)

    after = prompt.split("---")[-1]
    assert LOG not in after
    assert "cut short" in after
    assert NO_RERUN in after
    assert RUN_YOURSELF not in " ".join(prompt.lower().split())


FIRST, SECOND = "runs/e2e-output/unit-1-a.log", "runs/e2e-output/unit-1-b.log"


@pytest.mark.parametrize("resumes", [False, True], ids=["prompt", "continuation"])
def test_a_second_e2e_failure_names_the_latest_runs_file(tmp_path: Path, resumes: bool) -> None:
    prompt = reworked(tmp_path, failed_twice(FIRST, SECOND), FeedbackSource.E2E, resumes=resumes)

    after = prompt.split("---")[-1]
    assert SECOND in after
    assert FIRST not in after


@pytest.mark.parametrize("resumes", [False, True], ids=["prompt", "continuation"])
def test_a_withheld_latest_run_names_no_file_even_when_an_older_one_was_readable(
    tmp_path: Path, resumes: bool
) -> None:
    feedback = failed_twice(FIRST, SECOND, withheld=True)

    prompt = reworked(tmp_path, feedback, FeedbackSource.E2E, resumes=resumes)

    after = prompt.split("---")[-1]
    assert FIRST not in after and SECOND not in after
    assert NO_RERUN in after


@pytest.mark.parametrize("resumes", [False, True], ids=["prompt", "continuation"])
def test_a_unit_test_failure_keeps_the_instruction_to_run_the_checks_yourself(
    tmp_path: Path, resumes: bool
) -> None:
    template = CHECKS_CONTINUATION if resumes else CHECKS_PROMPT
    assert "{rerun}" in template, "the sentence is the advice's, which unit-test leaves as it was"
    prompt = reworked(tmp_path, UNIT_TEST_FEEDBACK, FeedbackSource.UNIT_TEST, resumes=resumes)

    old = (
        "Run the checks yourself first: the output above may be cut short"
        if resumes
        else "The output may be cut short; run the checks yourself to see all of it."
    )
    assert old in " ".join(prompt.split())
    assert NO_RERUN not in prompt
    assert "e2e-output" not in prompt


def test_both_templates_take_the_rerun_advice_in_place_of_the_sentence() -> None:
    for template in (CHECKS_PROMPT, CHECKS_CONTINUATION):
        assert "{rerun}" in template
        assert RUN_YOURSELF not in template.lower().replace("\n", " ")
