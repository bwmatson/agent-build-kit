"""The checks prompt, its continuation, the sentences about rerunning the checks and the output
convention tell a build agent to run the failing tests and the tests it changed, by file or test
id, and not the whole suite, and that a test that starts a local server on 127.0.0.1 cannot pass
inside its sandbox (spec: agent-test-commands)."""

from __future__ import annotations

import pytest

from agent_build_kit.pipeline.scratch import output_convention
from agent_build_kit.pipeline.stack_runner import CHECKS_CONTINUATION, CHECKS_PROMPT
from tests.prompt_text import flat

FIELDS = {"guidance": "", "feedback": "FAILED tests/test_a.py::test_a", "boundary": ""}
PROMPT = flat(
    CHECKS_PROMPT.format(commands="", change_dir="openspec/changes/c", groups="1", **FIELDS)
)
CONTINUATION = flat(CHECKS_CONTINUATION.format(**FIELDS))
BOTH = [pytest.param(PROMPT, id="prompt"), pytest.param(CONTINUATION, id="continuation")]


@pytest.mark.parametrize("text", BOTH)
def test_the_agent_is_told_to_run_the_failing_tests_by_file_or_test_id(text: str) -> None:
    assert "by file or test id" in text
    assert "the pipeline runs the whole suite" in text.lower()


@pytest.mark.parametrize("text", BOTH)
def test_the_agent_is_not_told_to_finish_only_when_every_test_passes(text: str) -> None:
    assert "finish only when all of them pass" not in text.lower()
    assert "and the tests before you finish" not in text.lower()


@pytest.mark.parametrize("text", BOTH)
def test_the_agent_is_told_a_local_server_test_cannot_pass_in_its_sandbox(text: str) -> None:
    assert "127.0.0.1" in text
    assert "not a defect" in text


@pytest.mark.parametrize("text", BOTH)
def test_the_rerun_sentence_does_not_send_the_agent_to_rerun_the_checks(text: str) -> None:
    assert "run the checks yourself" not in text.lower()


def test_the_output_convention_does_not_tell_the_agent_to_run_the_full_suite() -> None:
    text = flat(output_convention()).lower()

    assert "run the full suite once" not in text
    assert "the pipeline runs the whole suite" in text
