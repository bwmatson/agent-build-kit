"""The authoring skill tells authors to describe behaviour (spec: dry-guidance)."""

import re

from agent_build_kit import skills


def section() -> str:
    """The squeezed, lower-cased text of the authoring skill from its behaviour guidance on."""
    text = " ".join(skills.source("abk-authoring").split())
    held = re.search(r"describes? behaviou?r.*", text, re.IGNORECASE)
    assert held, "the authoring skill does not tell authors a task describes behaviour"
    return held.group(0).lower()


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
    text = section()

    assert re.search(r"\bgood\b", text)
    assert re.search(r"\bbad\b", text)
