"""What an `[e2e-test]` unit's builder is told: the first-build prompts say the unit holds tests
and test support only, and the rework prompt after a failed e2e-test step or a scope stop says
to fix a test fault in place and to report a product fault as a `product-defect` block, editing
no product code (spec: e2e-group-scope)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.pipeline.unit_store import FeedbackSource
from tests.e2e_scope_fakes import NEW, OLD
from tests.graph.test_e2e_scope_guard import (
    PRODUCT,
    PRODUCT_BASE,
    PRODUCT_CHANGED,
    TEST,
    UNIT,
    Scoped,
    group,
)

SCOPE_NOTE = "tests and test support only"
FAILED_E2E = f"FAILED {TEST}::test_stream - assert 200 == 500\n1 failed in 3.10s"


def reworked_with(tmp_path: Path, source: FeedbackSource, feedback: str = FAILED_E2E) -> str:
    """The prompt of the rework an e2e unit gets for saved feedback of `source`."""
    scoped = Scoped(tmp_path, PRODUCT_CHANGED, base_files=PRODUCT_BASE)
    scoped.build()
    scoped.recorder.store.set_feedback(UNIT, feedback, source=source)
    scoped.recorder.prompts.clear()

    scoped.build()

    [prompt] = scoped.recorder.prompts
    return prompt


@pytest.mark.parametrize("source", [FeedbackSource.E2E, FeedbackSource.SCOPE])
def test_the_rework_prompt_tells_a_product_fault_from_a_test_fault(
    source: FeedbackSource, tmp_path: Path
) -> None:
    prompt = reworked_with(tmp_path, source)

    lowered = prompt.lower()
    assert "in place" in lowered, "a test or helper fault is fixed where it is"
    assert "do not edit product code" in lowered
    assert "```product-defect" in prompt or "`product-defect`" in prompt
    for field in ("test", "files", "reproduction", "sketch", "repo"):
        assert f'"{field}"' in prompt, f"the block's {field} field is described"


def test_the_prompt_for_a_unit_test_failure_is_as_before(tmp_path: Path) -> None:
    unit_test = reworked_with(tmp_path / "unit", FeedbackSource.UNIT_TEST, "lint: unused import")
    e2e = reworked_with(tmp_path / "e2e", FeedbackSource.E2E)

    assert "product-defect" in e2e, "the e2e prompt carries the instruction"
    assert "product-defect" not in unit_test
    assert "do not edit product code" not in unit_test.lower()


def test_the_first_build_prompts_of_an_e2e_unit_carry_the_scope_note_and_a_unit_test_units_do_not(
    tmp_path: Path,
) -> None:
    e2e = Scoped(tmp_path / "e2e", {TEST: NEW}, base_files={TEST: OLD})
    e2e.build()
    plain = Scoped(
        tmp_path / "plain",
        {PRODUCT: "x = 1\n"},
        groups=(group(1, tier="unit-test"),),
        tier="unit-test",
    )
    plain.build()

    tests_prompt, implementation_prompt, *_ = e2e.recorder.prompts
    assert "test tasks" in tests_prompt, "the tests prompt came first"
    for prompt in (tests_prompt, implementation_prompt):
        assert SCOPE_NOTE in prompt
    tests_prompt, implementation_prompt, *_ = plain.recorder.prompts
    for prompt in (tests_prompt, implementation_prompt):
        assert SCOPE_NOTE not in prompt
