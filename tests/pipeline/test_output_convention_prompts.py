"""What the build, rework and resolver agents are told about long command output.

One packaged text, carried by every prompt that sends an agent to change code:
redirect a long command's output and exit status to `$ABK_OUT`, read it with
`tail`, `grep` or `sed -n`, never run a command again to see more of it, run the
full suite once per round and only the failing tests after a fix
(spec: command-output-to-files).
"""

import re

import pytest

from agent_build_kit.pipeline.restack import RESOLVE_PROMPT
from agent_build_kit.pipeline.scratch import output_convention
from agent_build_kit.pipeline.stack_runner import (
    IMPLEMENTATION_PROMPT,
    REVIEW_FEEDBACK_PROMPT,
    REWORK_PROMPT,
    TESTS_PROMPT,
)
from agent_build_kit.pipeline.wiring import REVIEW_PROMPT


def squeezed(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


PROMPTS = [
    pytest.param(TESTS_PROMPT, id="tests"),
    pytest.param(IMPLEMENTATION_PROMPT, id="implementation"),
    pytest.param(REWORK_PROMPT, id="rework"),
    pytest.param(REVIEW_FEEDBACK_PROMPT, id="review-feedback"),
    pytest.param(RESOLVE_PROMPT, id="resolver"),
]


def test_the_convention_states_each_rule() -> None:
    text = squeezed(output_convention()).lower()

    assert "$abk_out/" in text
    assert ".log" in text
    assert ".exit" in text
    assert "2>&1" in text
    for reader in ("tail", "grep", "sed -n"):
        assert reader in text
    assert re.search(r"(never|not) (run|rerun)[^.]*(again|rerun|more)", text)
    assert "once" in text
    assert "failed" in text or "failing" in text
    assert "suite" in text
    assert "last edit" in text
    assert "pytest" not in text
    assert "uv run" not in text


def test_the_convention_names_no_installation() -> None:
    text = output_convention()

    assert "/home/" not in text
    assert not re.search(r"\w+#\d+", text)


@pytest.mark.parametrize("prompt", PROMPTS)
def test_each_prompt_carries_the_convention(prompt: str) -> None:
    assert squeezed(output_convention()) in squeezed(prompt)


def test_the_convention_is_safe_to_put_in_a_format_string() -> None:
    """The prompts are format strings: braces in the shared text would break them."""
    text = output_convention()

    assert "{" not in text
    assert "}" not in text


def test_the_reviewer_is_told_to_run_its_own_commands() -> None:
    assert "own commands" in squeezed(REVIEW_PROMPT).lower()
