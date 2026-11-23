"""What the migration cannot edit safely is refused with the key and a reason."""

from __future__ import annotations

import re

import pytest

from agent_build_kit.config_migrate import ConfigMigrateError, migrate

# name -> (text, a pattern for the key the message names, a pattern for the reason it gives)
CASES = {
    "flow-style block": ("limits: {max_units_in_progress: 5}\n", r"limits", r"flow"),
    "block that is one value": ("limits: 5\n", r"limits", r"mapping|block"),
    "value on several lines": (
        "limits:\n  max_units_in_progress:\n    5\n",
        r"max_units_in_progress",
        r"line",
    ),
    "anchor on a moved key": (
        "limits:\n  max_units_in_progress: &n 5\n",
        r"max_units_in_progress|limits",
        r"anchor",
    ),
    "merge key": (
        "base: &base\n  max_units_in_progress: 5\nlimits:\n  <<: *base\n",
        r"max_units_in_progress|limits|<<",
        r"merge|anchor|alias",
    ),
    "alias of a block anchored elsewhere": (
        "base: &b\n  max_units_in_progress: 5\nlimits: *b\n",
        r"limits",
        r"anchor|alias",
    ),
    "anchored block": (
        "limits: &l\n  max_units_in_progress: 5\n",
        r"limits",
        r"anchor|alias",
    ),
    "project_limits indented differently": (
        "project_limits:\n    max_concurrent_stacks: 2\nlimits:\n  max_units_in_progress: 5\n",
        r"project_limits",
        r"indent",
    ),
    "project_limits in flow style": (
        "project_limits: {max_concurrent_stacks: 2}\nlimits:\n  max_units_in_progress: 5\n",
        r"project_limits",
        r"flow",
    ),
    "limits and global_limits": (
        "limits:\n  max_units_in_progress: 5\nglobal_limits:\n  min_unit_lines: 400\n",
        r"(?s)(?=.*\blimits\b)(?=.*global_limits)",
        r"both|together",
    ),
    "already in project_limits": (
        "project_limits:\n  max_units_in_progress: 3\nlimits:\n  max_units_in_progress: 5\n",
        r"max_units_in_progress",
        r"project_limits",
    ),
    "text that does not parse": ("limits: [unclosed\n", r"", r"pars"),
    "several documents": (
        "limits:\n  max_units_in_progress: 5\n---\nother: 1\n",
        r"",
        r"document",
    ),
}


@pytest.mark.parametrize("name", CASES)
def test_each_is_refused_with_the_key_and_a_reason(name: str) -> None:
    text, key, reason = CASES[name]

    with pytest.raises(ConfigMigrateError) as refused:
        migrate(text)

    message = str(refused.value)
    assert re.search(key, message)
    assert re.search(reason, message, re.IGNORECASE)
