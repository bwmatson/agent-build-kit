"""The tests and review prompts follow the group mode (spec: group-build-modes)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.pipeline.group_mode import GroupMode
from agent_build_kit.pipeline.stack_runner import tests_prompt
from agent_build_kit.pipeline.wiring import build_run_review
from tests.factories import activate_with
from tests.prompt_text import flat
from tests.runtimes.stand_in import StandInRuntime

FIELDS = {
    "commands": "",
    "guidance": "",
    "groups": "1",
    "change_dir": "openspec/changes/feature",
    "boundary": "",
    "changelog": "",
}


def tests_text(mode: GroupMode) -> str:
    return flat(tests_prompt(mode, **FIELDS)).lower()


def review_text(tmp_path: Path, modes: dict[str, GroupMode] | None) -> str:
    activate_with(review={"enabled": True})
    runtime = StandInRuntime()
    build_run_review(runtime=runtime)(cwd=tmp_path, group_modes=modes)
    return flat(runtime.request.prompt).lower()


def test_a_tests_and_code_tests_prompt_carries_the_standards_and_says_tests_must_fail() -> None:
    text = tests_text(GroupMode.TESTS_AND_CODE)

    assert "protocol boundary" in text
    assert "recorded from the real system" in text
    assert "which must fail" in text


def test_a_tests_only_tests_prompt_says_there_is_no_implementation_and_tests_must_pass() -> None:
    text = tests_text(GroupMode.TESTS_ONLY)

    assert "builds no implementation" in text
    assert "must pass" in text
    assert "must fail" not in text


@pytest.mark.parametrize("mode", [GroupMode.NO_CODE, GroupMode.REFACTOR])
def test_a_group_with_no_tests_node_has_no_tests_prompt(mode: GroupMode) -> None:
    with pytest.raises(ValueError, match="tests"):
        tests_prompt(mode, **FIELDS)


def test_a_no_code_review_prompt_carries_no_test_standard(tmp_path: Path) -> None:
    text = review_text(tmp_path, {"feature/1": GroupMode.NO_CODE})

    assert "hold the tests to the determinism rules" not in text
    assert "check the tests against the real system" not in text
    assert "documents" in text
    assert "configuration" in text


def test_a_refactor_review_prompt_asks_what_must_be_unchanged(tmp_path: Path) -> None:
    text = review_text(tmp_path, {"feature/1": GroupMode.REFACTOR})

    for unchanged in ("behaviour", "public surface", "output", "configuration"):
        assert unchanged in text
    assert "unchanged" in text


def test_a_review_prompt_with_no_modes_keeps_the_test_standards(tmp_path: Path) -> None:
    text = review_text(tmp_path, None)

    assert "hold the tests to the determinism rules" in text
    assert "check the tests against the real system" in text


def test_a_mixed_unit_review_prompt_names_the_group_each_rule_is_for(tmp_path: Path) -> None:
    text = review_text(
        tmp_path, {"feature/1": GroupMode.TESTS_AND_CODE, "feature/2": GroupMode.REFACTOR}
    )

    assert "feature/1" in text
    assert "feature/2" in text
    assert "check the tests against the real system" in text
    assert "unchanged" in text
