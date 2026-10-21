"""What the review prompt asks for when the brief is on (spec: review-brief)."""

from pathlib import Path

from agent_build_kit.pipeline.wiring import build_run_review
from tests.factories import activate_with
from tests.runtimes.stand_in import StandInRuntime


def prompt(tmp_path: Path, *, brief: bool) -> str:
    activate_with(review={"brief": brief})
    runtime = StandInRuntime()
    build_run_review(runtime=runtime)(cwd=tmp_path)
    return " ".join(runtime.request.prompt.split()).lower()


def test_the_prompt_asks_for_the_focus_list_and_its_four_reasons(tmp_path: Path) -> None:
    text = prompt(tmp_path, brief=True)

    assert "`focus`" in text
    for reason in ("boundary", "behaviour change", "hard to undo", "thin test coverage"):
        assert reason in text


def test_the_prompt_asks_for_the_skippable_list_with_a_reason_each(tmp_path: Path) -> None:
    text = prompt(tmp_path, brief=True)

    assert "`skippable`" in text
    assert "reason" in text.split("`skippable`", 1)[1]


def test_the_prompt_says_a_list_may_be_empty(tmp_path: Path) -> None:
    text = prompt(tmp_path, brief=True)

    assert "empty list" in text


def test_with_the_brief_off_the_prompt_does_not_ask_for_the_lists(tmp_path: Path) -> None:
    off = prompt(tmp_path, brief=False)
    on = prompt(tmp_path, brief=True)

    assert "`focus`" not in off
    assert "`skippable`" not in off
    assert off != on
    assert all(sentence in on for sentence in off.split(". ")), "the rest of the prompt is kept"
