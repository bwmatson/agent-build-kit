"""The authoring skill tells authors to describe behaviour (spec: dry-guidance)."""

import re

from agent_build_kit import skills
from tests.prompt_text import flat

HEADING = "## Describe behaviour, not names"


def raw_section() -> str:
    """The skill's section about describing behaviour, up to the next heading."""
    text = skills.source("abk-authoring")
    assert HEADING in text, "the authoring skill has no section about describing behaviour"
    return re.split(r"^## ", text.split(HEADING, 1)[1], maxsplit=1, flags=re.MULTILINE)[0]


def section() -> str:
    return flat(raw_section()).lower()


def examples() -> list[str]:
    return [
        line.lower()
        for line in raw_section().splitlines()
        if re.match(r"- (good|bad):", line, re.I)
    ]


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


def test_the_section_names_no_installation_language_tool_or_path() -> None:
    text = raw_section()

    assert text.strip()
    assert not re.search(r"\w+#\d+|/home/|github\.com", text)
    assert not re.search(r"\.(py|ts|tsx|js|go|rs|java|rb|md|toml|lock)\b", text)
    assert not re.search(r"\b(agent[-_]build[-_]kit|abk)\b", text, re.IGNORECASE)
    for tool in ("pytest", "uv ", "npm", "ruff", "cargo", "pip", "jest", "vitest"):
        assert tool not in text


def test_the_examples_use_no_language_specific_syntax() -> None:
    held = examples()

    assert held
    for example in held:
        assert not re.search(r"\b(def|function|fn|func|class|const|let|var|import)\s", example)
        assert not re.search(r"\w+\([^)]*\)\s*(->|=>|\{|:)", example)
