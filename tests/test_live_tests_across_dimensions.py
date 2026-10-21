"""The kit's live tests are written once across a dimension's values: `telemetry_local` is
registered, no two live tests differ in name only by a value, a value-neutral name holds no
value token, and the documents and skills say so (spec: e2e-dimensions)."""

from __future__ import annotations

import re
import tomllib

import pytest

from tests.live_tag_drift import DIMENSIONS, collected, find_live_modules, value_name_drift
from tests.prompt_text import flat
from tests.runtime_tag_collection import ROOT

HEADER = "import pytest\n\npytestmark = pytest.mark.local_stack\n"
MERGE = "merge into one parametrized test"


def named(pytester: pytest.Pytester, **modules: str) -> list[str]:
    return value_name_drift(collected(pytester, **modules), DIMENSIONS)


def parametrized(name: str, *values: str, dimension: str = "runtime") -> str:
    params = ", ".join(f'pytest.param("{v}", marks=pytest.mark.{dimension}_{v})' for v in values)
    return (
        f'{HEADER}\n\n@pytest.mark.parametrize("value", [{params}])\ndef {name}(value):\n    pass\n'
    )


def tagged(name: str, marker: str) -> str:
    return f"{HEADER}\n\n@pytest.mark.{marker}\ndef {name}():\n    pass\n"


def test_telemetry_local_is_registered_beside_telemetry_otel() -> None:
    options = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["pytest"]["ini_options"]
    names = {m.split(":")[0].strip() for m in options["markers"]}

    assert {"telemetry_otel", "telemetry_local"} <= names


def test_no_two_live_tests_of_the_kit_differ_in_name_only_by_a_dimension_value(
    pytester: pytest.Pytester,
) -> None:
    modules = find_live_modules(ROOT / "tests")
    assert modules
    items, _ = pytester.inline_genitems(*(str(m) for m in modules))

    assert items
    assert value_name_drift(items, DIMENSIONS) == []


def test_two_tests_whose_names_differ_only_by_a_runtime_value_are_told_to_merge(
    pytester: pytest.Pytester,
) -> None:
    found = named(
        pytester,
        test_a=tagged("test_acp_gets_the_override", "runtime_acp"),
        test_b=tagged("test_claude_code_gets_the_override", "runtime_claude_code"),
    )

    assert len(found) == 1
    assert MERGE in found[0]
    assert "test_acp_gets_the_override" in found[0]
    assert "test_claude_code_gets_the_override" in found[0]


def test_two_tests_whose_names_differ_only_by_a_telemetry_value_are_told_to_merge(
    pytester: pytest.Pytester,
) -> None:
    found = named(
        pytester,
        test_a=tagged("test_trace_is_found_in_otel_sink", "telemetry_otel"),
        test_b=tagged("test_trace_is_found_in_local_sink", "telemetry_local"),
    )

    assert len(found) == 1
    assert MERGE in found[0]


def test_tests_with_different_names_are_not_told_to_merge(pytester: pytest.Pytester) -> None:
    found = named(
        pytester,
        test_a=tagged("test_lists_the_session", "runtime_acp"),
        test_b=tagged("test_builds_a_unit", "runtime_claude_code"),
    )

    assert found == []


def test_a_value_neutral_test_over_the_runtimes_is_not_named(pytester: pytest.Pytester) -> None:
    found = named(pytester, test_a=parametrized("test_gets_the_override", "claude_code", "acp"))

    assert found == []


def test_a_value_neutral_name_holding_a_value_token_is_named_when_another_test_carries_it(
    pytester: pytest.Pytester,
) -> None:
    found = named(
        pytester,
        test_a=parametrized("test_acp_gets_the_override", "claude_code", "acp"),
        test_b=tagged("test_lists_the_session", "runtime_acp"),
    )

    assert len(found) == 1
    assert "test_acp_gets_the_override" in found[0]
    assert "acp" in found[0]


def test_a_value_token_is_allowed_in_the_name_of_the_only_test_carrying_the_value(
    pytester: pytest.Pytester,
) -> None:
    found = named(pytester, test_a=parametrized("test_acp_gets_the_override", "claude_code", "acp"))

    assert found == []


def test_a_token_is_a_whole_underscore_delimited_word(pytester: pytest.Pytester) -> None:
    found = named(
        pytester,
        test_a=parametrized("test_placard_is_shown", "claude_code", "acp"),
        test_b=tagged("test_lists_the_session", "runtime_acp"),
    )

    assert found == []


def test_a_telemetry_token_is_found_in_a_neutral_name(pytester: pytest.Pytester) -> None:
    found = named(
        pytester,
        test_a=parametrized(
            "test_local_sink_has_the_trace", "otel", "local", dimension="telemetry"
        ),
        test_b=tagged("test_other_local_check", "telemetry_local"),
    )

    assert len(found) == 1
    assert "test_local_sink_has_the_trace" in found[0]


def test_a_test_that_is_not_live_is_not_checked(pytester: pytest.Pytester) -> None:
    plain = "import pytest\n\n\n@pytest.mark.runtime_{v}\ndef test_{v}_gets_it():\n    pass\n"
    found = named(pytester, test_a=plain.format(v="acp"), test_b=plain.format(v="claude_code"))

    assert found == []


DOCS = flat((ROOT / "docs" / "configuration.md").read_text())
SKILLS = ROOT / "src" / "agent_build_kit" / "skills"


@pytest.mark.parametrize("term", ["e2e_dimensions", "e2e_available"])
def test_the_configuration_document_documents(term: str) -> None:
    assert term in DOCS


def test_the_configuration_document_puts_e2e_available_in_the_machine_local_overlay() -> None:
    assert re.search(r"e2e_available[^.]*abk\.local\.yaml|abk\.local\.yaml[^.]*e2e_available", DOCS)


def test_the_configuration_document_states_the_writing_convention() -> None:
    assert re.search(r"one parametrized test[^.]*(name|value)", DOCS)
    assert MERGE in DOCS or "differ only by" in DOCS


@pytest.mark.parametrize("skill", ["abk-config", "abk-authoring"])
@pytest.mark.parametrize("term", ["e2e_dimensions", "e2e_available"])
def test_the_skill_mentions(skill: str, term: str) -> None:
    assert term in (SKILLS / skill / "SKILL.md").read_text()


def test_the_runtimes_document_mentions_the_dimensions() -> None:
    assert "e2e_dimensions" in flat((ROOT / "docs" / "agent-runtimes.md").read_text())
