"""The reuse guidance has a source version and a test version, and each prompt carries the one it
needs (spec: test-reuse-guidance).

The tests prompt carries the test version; the implement and fix-checks prompts the source
version; a rework the source version, and the test version too when its group names a test file;
a continuation, a `no_code` or `refactor` group's implement prompt and a prompt that writes no
test carry no test version.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

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
from agent_build_kit.pipeline.standards_guidance import standards_guidance
from agent_build_kit.pipeline.unit_store import FeedbackSource
from tests.factories import unit
from tests.graph.branch_fakes import prepared, titled
from tests.graph.test_build_path import build
from tests.graph.test_rework_guidance import requeue
from tests.graph_driver import fresh, tick
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

SOURCE = flat(reuse_guidance("source"))
TESTS = flat(reuse_guidance("tests"))


def carries_test_points(text: str) -> bool:
    """Whether the reuse note in `text` has test advice; the standards table, which names the
    same standards, is a separate part of the prompt and is left out."""
    note = text.replace(flat(standards_guidance()), "")
    return any(re.search(point, note, re.IGNORECASE) for point in TEST_POINTS)


# --- the two versions ---------------------------------------------------------------


def test_the_two_versions_are_different_texts() -> None:
    assert SOURCE and TESTS
    assert SOURCE != TESTS


def test_the_source_version_has_no_test_advice() -> None:
    assert not carries_test_points(SOURCE)
    assert "shared test support" not in SOURCE.lower()


def test_the_test_version_names_its_points_and_cites_the_standards() -> None:
    assert re.search(r"parametri[sz]e", TESTS, re.IGNORECASE)
    for standard in ("T8a", "T21", "T22"):
        assert re.search(rf"\b{standard}\b", TESTS), standard
    assert re.search(r"same setup[^.]*several files[^.]*missing fixture", TESTS, re.IGNORECASE)
    assert re.search(r"test (of|for) a test|subject is (another|a) test", TESTS, re.IGNORECASE)


def test_the_test_version_points_to_the_placement_rule() -> None:
    assert "placement rule" in TESTS.lower()


@pytest.mark.parametrize("name", profiles.names())
def test_the_test_version_does_not_restate_a_profiles_placement_rule(name: str) -> None:
    placement = flat(profiles.get(name).prompt_words.placement).lower()
    # The rule's sentences, less its "Placement (T2, ...):" label; a profile with no rule has none.
    sentences = [s.strip() for s in placement.split("):", 1)[-1].split(".")]

    for sentence in filter(None, sentences):
        assert sentence not in TESTS.lower()


def test_the_test_version_keeps_the_reuse_basics_for_test_support() -> None:
    text = TESTS.lower()

    assert "shared test support" in text
    assert "fixtures" in text


# --- which prompt carries which -----------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        flat(write_tests_prompt(GroupMode.TESTS_AND_CODE, **FIELDS)),
        flat(filled(TESTS_PROMPT)),
    ],
    ids=["written", "unfilled"],
)
def test_the_tests_prompt_carries_the_test_version_and_not_the_source_one(text: str) -> None:
    assert TESTS in text
    assert SOURCE not in text


def test_the_tests_prompt_states_the_placement_rule_once() -> None:
    placement = profiles.get("python-uv").prompt_words.placement
    text = flat(filled(TESTS_PROMPT, placement=placement))

    assert "placement rule" in TESTS.lower()
    assert TESTS in text
    assert text.lower().count("existing test file for the module it exercises") == 1


@pytest.mark.parametrize("prompt", [IMPLEMENTATION_PROMPT, CHECKS_PROMPT], ids=["impl", "checks"])
def test_the_implement_and_fix_checks_prompts_carry_the_source_version_and_no_test_points(
    prompt: str,
) -> None:
    text = flat(filled(prompt))

    assert SOURCE in text
    assert TESTS not in text
    assert not carries_test_points(text)


def test_the_implementation_of_a_group_with_no_tests_step_carries_the_source_version_only() -> None:
    text = flat(IMPLEMENTATION_PROMPT.format(no_tests=True, **FIELDS))

    assert SOURCE in text
    assert TESTS not in text
    assert not carries_test_points(text)


def test_a_tests_only_prompt_carries_the_test_version_and_says_its_tests_must_pass() -> None:
    text = flat(write_tests_prompt(GroupMode.TESTS_ONLY, **FIELDS))

    assert TESTS in text
    assert SOURCE not in text
    assert "must pass" in text


@pytest.mark.parametrize("mode", [GroupMode.NO_CODE, GroupMode.REFACTOR])
def test_a_group_with_no_tests_step_builds_no_tests_prompt(mode: GroupMode) -> None:
    with pytest.raises(ValueError, match="tests"):
        write_tests_prompt(mode, **FIELDS)


# --- a rework --------------------------------------------------------------------------


REWORK_START = "A review of this branch asked for changes"


FEEDBACK_REWORK_START = "Review asked for a change to the work already on this branch"
TEST_NAMED = (
    "- [ ] 1.1 Test: `tests/pipeline/test_marker.py` — the marker\n- [ ] 1.2 Do the marker\n"
)
NO_TEST_NAMED = "- [ ] 1.1 Test: the marker\n- [ ] 1.2 Do the marker in `src/marker.py`\n"


def write_group_tasks(tmp_path: Path, tasks: str) -> None:
    path = tmp_path / "meta" / "openspec" / "changes" / "add-marker" / "tasks.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"## 1. [app] [unit-test] G1\n\n{tasks}")


def review_loop_rework(tmp_path: Path, tasks: str) -> str:
    """The review loop's rework prompt for a unit whose group 1 has `tasks` for its tasks."""
    recorder, _ = prepared(tmp_path, groups={"add-marker": titled(1)})
    write_group_tasks(tmp_path, tasks)
    recorder.verdicts = [rejecting("rename it")]

    build(tmp_path, recorder, **recorder.overrides(tmp_path))

    return next(p for p in map(flat, recorder.prompts) if REWORK_START in p)


def requeue_rework(tmp_path: Path, tasks: str) -> str:
    """The rework prompt of a requeued unit with saved review feedback, whose group 1 has
    `tasks` for its tasks."""
    recorder = fresh(tmp_path)
    tick(tmp_path, recorder)
    write_group_tasks(tmp_path, tasks)
    recorder.store.set_feedback(unit().id, "rename it", source=FeedbackSource.REVIEW)
    prompts: list[str] = []

    def agent(prompt: str, **kwargs: Any) -> str:
        prompts.append(prompt)
        return recorder.claude(prompt, **kwargs)

    tick(tmp_path, recorder, event=requeue(""))
    tick(tmp_path, recorder, run=agent)

    [prompt] = prompts
    assert prompt.startswith(FEEDBACK_REWORK_START)
    return flat(prompt)


REWORKS = pytest.mark.parametrize(
    "rework", [review_loop_rework, requeue_rework], ids=["review-loop", "requeue"]
)


@REWORKS
def test_a_rework_whose_group_names_a_test_file_carries_both_versions(
    tmp_path: Path, rework: Callable[[Path, str], str]
) -> None:
    text = rework(tmp_path, TEST_NAMED)

    assert SOURCE in text
    assert TESTS in text


@REWORKS
def test_a_rework_whose_group_names_no_test_file_carries_the_source_version_only(
    tmp_path: Path, rework: Callable[[Path, str], str]
) -> None:
    text = rework(tmp_path, NO_TEST_NAMED)

    assert SOURCE in text
    assert TESTS not in text
    assert not carries_test_points(text)
