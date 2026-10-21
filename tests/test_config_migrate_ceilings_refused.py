"""The `max_unit_lines` move refuses, naming the key, when it cannot edit safely."""

from __future__ import annotations

import re

import pytest

from agent_build_kit.config_migrate import ConfigMigrateError, migrate

# name -> (text, a pattern for what the message names, a pattern for the reason it gives)
CASES = {
    "full ceiling already set to another value": (
        "global_limits:\n  max_unit_lines: 900\nreview:\n  ceilings:\n    full: 800\n",
        r"max_unit_lines|review\.ceilings\.full",
        r"already|different|both",
    ),
    "value on the next line": (
        "global_limits:\n  max_unit_lines:\n    900\n",
        r"max_unit_lines",
        r"more than one line",
    ),
    "anchor on the value": (
        "global_limits:\n  max_unit_lines: &cap 900\n",
        r"max_unit_lines",
        r"anchor|alias",
    ),
    "several documents": (
        "global_limits:\n  max_unit_lines: 900\n---\nversion: 1\n",
        r"max_unit_lines",
        r"several documents",
    ),
    "result would not load": (
        "global_limits:\n  max_unit_lines: 900\nreview:\n  ceilings:\n    light: 800\n",
        r"max_unit_lines|review\.ceilings",
        r"load|differ|order|above|below|light",
    ),
}


@pytest.mark.parametrize("name", CASES)
def test_each_is_refused_with_the_key_and_a_reason(name: str) -> None:
    text, key, reason = CASES[name]

    with pytest.raises(ConfigMigrateError) as refused:
        migrate(text)

    assert re.search(key, str(refused.value)), str(refused.value)
    assert re.search(reason, str(refused.value), re.IGNORECASE), str(refused.value)


def test_a_result_with_ceilings_out_of_order_says_to_raise_light_and_auto() -> None:
    text = "global_limits:\n  max_unit_lines: 3000\n"

    with pytest.raises(ConfigMigrateError) as refused:
        migrate(text)

    assert "review.ceilings.light" in str(refused.value)
    assert "review.ceilings.auto" in str(refused.value)
