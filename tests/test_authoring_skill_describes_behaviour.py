"""The authoring skill tells authors to describe behaviour (spec: dry-guidance)."""

from tests.exclusions import examples, raw_section
from tests.prompt_text import flat


def section() -> str:
    return flat(raw_section()).lower()


def test_a_task_names_code_only_when_the_name_is_a_contract() -> None:
    text = section()

    assert "function, class or constant" in text
    assert "only when the name is a contract" in text
    assert "public api" in text


def test_add_a_helper_that_does_x_is_replaced_by_what_must_be_true() -> None:
    text = section()

    assert "add a helper that does x" in text
    assert "what must be true" in text


def test_there_is_a_good_and_a_bad_example() -> None:
    kinds = [example.split(":")[0] for example in examples()]

    assert kinds == ["- good", "- bad"]
