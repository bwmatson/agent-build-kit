"""What the test step and the stub check loop tell the test agent (spec: stub-check-loop)."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.pipeline.unit_store import FeedbackSource
from tests.factories import activate_with
from tests.graph.stub_loop_fakes import StubLoop, stubbed_build
from tests.graph.test_build_path import build
from tests.graph_driver import fresh as fresh_store
from tests.prompt_text import flat

SAVED = "tests/test_x.py:1:8: F401 `os` imported but unused"


def first_tests_prompt(tmp_path: Path) -> str:
    recorder = StubLoop(fresh_store(tmp_path).store)
    build(tmp_path, recorder, **recorder.overrides(tmp_path))
    return flat(recorder.prompts[0]).lower()


def test_the_tests_prompt_of_a_stubbed_build_says_what_the_stubs_must_pass(
    tmp_path: Path,
) -> None:
    stubbed_build()

    prompt = first_tests_prompt(tmp_path)

    assert "lint, format and types" in prompt
    assert "stubs hold no logic" in prompt or "stubs contain no logic" in prompt
    assert "do not run the new tests" in prompt
    assert "run the new tests, which must fail" not in prompt


def test_the_tests_prompt_of_a_build_that_is_not_stubbed_is_as_it_was(tmp_path: Path) -> None:
    stubbed_build()
    stubbed = first_tests_prompt(tmp_path / "stubbed")
    activate_with(builders={"per_group_commits": False})

    plain = first_tests_prompt(tmp_path / "plain")

    assert "types" in stubbed
    assert "run the new tests, which must fail" in plain
    assert "types" not in plain


def test_the_fix_prompt_of_a_requeued_stop_carries_the_output_and_the_rules(
    tmp_path: Path,
) -> None:
    stubbed_build()
    recorder = StubLoop(fresh_store(tmp_path).store, checks=[(False, SAVED), (True, "")])
    recorder.asked = 1
    recorder.store.set_feedback("add-marker/1", SAVED, source=FeedbackSource.STUB_CHECKS)

    build(tmp_path, recorder, **recorder.overrides(tmp_path))

    (fix,) = recorder.fix_prompts
    prompt = flat(fix)
    assert SAVED in prompt
    assert "do not suppress a rule or loosen a type" in prompt
    assert "do not change what the tests assert" in prompt
