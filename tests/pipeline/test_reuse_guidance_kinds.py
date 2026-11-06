"""The reuse guidance has a source version and a test version, and each prompt carries the one it
needs (spec: test-reuse-guidance).

The tests prompt carries the test version; the implement and fix-checks prompts the source
version; a rework the source version, and the test version too when its group names a test file;
a continuation, a `no_code` or `refactor` group's implement prompt and a prompt that writes no
test carry no test version.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from agent_build_kit import profiles
from agent_build_kit.pipeline.group_mode import GroupMode
from agent_build_kit.pipeline.reuse_guidance import reuse_guidance
from agent_build_kit.pipeline.stack_runner import (
    CHECKS_PROMPT,
    IMPLEMENTATION_PROMPT,
    TESTS_PROMPT,
    write_tests_prompt,
)
from tests.graph.branch_fakes import prepared, titled
from tests.graph.test_build_path import build
from tests.prompt_text import filled, flat
from tests.runner_fakes import rejecting

FIELDS = {
    "commands": "",
    "guidance": "",
    "groups": "1",
    "change_dir": "openspec/changes/feature",
    "boundary": "",
    "changelog": "",
}

# What only the test version says: parametrise (T21), one fixture or helper per need (T8a, T21)
# and no test of a test (T22).
TEST_POINTS = (r"parametri[sz]e", r"\bT8a\b", r"\bT21\b", r"\bT22\b")


def source() -> str:
    return flat(reuse_guidance("source"))


def tests() -> str:
    return flat(reuse_guidance("tests"))


def carries_test_points(text: str) -> bool:
    return any(re.search(point, text, re.IGNORECASE) for point in TEST_POINTS)


# --- the two versions ---------------------------------------------------------------


def test_the_two_versions_are_different_texts() -> None:
    assert source() and tests()
    assert source() != tests()


def test_the_source_version_has_no_test_advice() -> None:
    text = source()

    assert source() != tests()
    assert not carries_test_points(text)
    assert "shared test support" not in text.lower()


def test_the_test_version_names_its_points_and_cites_the_standards() -> None:
    text = tests()

    assert re.search(r"parametri[sz]e", text, re.IGNORECASE)
    for standard in ("T8a", "T21", "T22"):
        assert re.search(rf"\b{standard}\b", text), standard
    assert re.search(r"same setup[^.]*several files[^.]*missing fixture", text, re.IGNORECASE)
    assert re.search(r"test (of|for) a test|subject is (another|a) test", text, re.IGNORECASE)


def test_the_test_version_points_to_the_placement_rule_and_does_not_restate_it() -> None:
    text = tests().lower()
    placement = flat(profiles.get("python-uv").prompt_words.placement).lower()

    assert "placement rule" in text
    assert "existing test file for the module" in placement
    assert "existing test file for the module" not in text
    assert "new test file is created only" not in text


def test_the_test_version_keeps_the_reuse_basics_for_test_support() -> None:
    text = tests().lower()

    assert source() != tests()
    assert "shared test support" in text
    assert "fixtures" in text


# --- which prompt carries which -----------------------------------------------------


def test_the_tests_prompt_carries_the_test_version_and_not_the_source_one() -> None:
    text = flat(write_tests_prompt(GroupMode.TESTS_AND_CODE, **FIELDS))

    assert source() != tests()
    assert tests() in text
    assert source() not in text


def test_the_unfilled_tests_prompt_carries_the_test_version() -> None:
    text = flat(filled(TESTS_PROMPT))

    assert source() != tests()
    assert tests() in text
    assert source() not in text


def test_the_tests_prompt_states_the_placement_rule_once() -> None:
    placement = profiles.get("python-uv").prompt_words.placement
    text = flat(filled(TESTS_PROMPT, placement=placement)).lower()

    assert "placement rule" in tests().lower()
    assert tests() in flat(filled(TESTS_PROMPT, placement=placement))
    assert text.count("existing test file for the module it exercises") == 1


@pytest.mark.parametrize("prompt", [IMPLEMENTATION_PROMPT, CHECKS_PROMPT], ids=["impl", "checks"])
def test_the_implement_and_fix_checks_prompts_carry_the_source_version_and_no_test_points(
    prompt: str,
) -> None:
    text = flat(filled(prompt))

    assert source() != tests()
    assert source() in text
    assert tests() not in text
    assert not carries_test_points(text)


def test_the_implementation_of_a_group_with_no_tests_step_carries_the_source_version_only() -> None:
    text = flat(
        IMPLEMENTATION_PROMPT.format(no_tests=True, **{**FIELDS, "commands": "", "changelog": ""})
    )

    assert source() != tests()
    assert source() in text
    assert tests() not in text
    assert not carries_test_points(text)


def test_a_tests_only_prompt_carries_the_test_version_and_says_its_tests_must_pass() -> None:
    text = flat(write_tests_prompt(GroupMode.TESTS_ONLY, **FIELDS))

    assert source() != tests()
    assert tests() in text
    assert source() not in text
    assert "must pass" in text


@pytest.mark.parametrize("mode", [GroupMode.NO_CODE, GroupMode.REFACTOR])
def test_a_group_with_no_tests_node_builds_no_prompt_with_the_test_version(
    mode: GroupMode,
) -> None:
    with pytest.raises(ValueError, match="tests"):
        write_tests_prompt(mode, **FIELDS)

    assert source() != tests()


# --- a rework --------------------------------------------------------------------------


REWORK_START = "Review asked for a change"


def reworked(tmp_path: Path, tasks: str) -> str:
    """The rework prompt of a unit whose group 1 has `tasks` for its tasks."""
    recorder, _ = prepared(tmp_path, groups={"add-marker": titled(1)})
    path = tmp_path / "meta" / "openspec" / "changes" / "add-marker" / "tasks.md"
    path.write_text(f"## 1. [app] [unit-test] G1\n\n{tasks}")
    recorder.verdicts = [rejecting("rename it")]

    build(tmp_path, recorder, **recorder.overrides(tmp_path))

    return flat(next(p for p in recorder.prompts if REWORK_START in p))


def test_a_rework_whose_group_names_a_test_file_carries_both_versions(tmp_path: Path) -> None:
    text = reworked(
        tmp_path,
        "- [ ] 1.1 Test: `tests/pipeline/test_marker.py` — the marker\n- [ ] 1.2 Do the marker\n",
    )

    assert source() != tests()
    assert source() in text
    assert tests() in text


def test_a_rework_whose_group_names_no_test_file_carries_the_source_version_only(
    tmp_path: Path,
) -> None:
    text = reworked(
        tmp_path,
        "- [ ] 1.1 Test: the marker\n- [ ] 1.2 Do the marker in `src/marker.py`\n",
    )

    assert source() != tests()
    assert source() in text
    assert tests() not in text
    assert not carries_test_points(text)
