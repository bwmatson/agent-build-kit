"""The usage-limits rename refuses, naming the key, what it cannot edit safely."""

from __future__ import annotations

import re

import pytest

from agent_build_kit.config_migrate import ConfigMigrateError, migrate

# name -> (text, a pattern for the key the message names, a pattern for the reason it gives)
CASES = {
    "old and new spelling in one runtime": (
        "runtimes:\n  claude_code:\n    limits: {}\n    usage_limits: {}\n",
        r"limits",
        r"both|together",
    ),
    "old and new spelling in one account": (
        "runtimes:\n  claude_code:\n    accounts:\n      kit:\n        limits: {}\n"
        "        usage_limits: {}\n",
        r"limits",
        r"both|together",
    ),
    "anchor on the key": (
        "runtimes:\n  claude_code:\n    limits: &w\n      session: {}\n",
        r"limits",
        r"anchor|alias",
    ),
    "alias as the value": (
        "base: &w\n  session: {}\nruntimes:\n  claude_code:\n    limits: *w\n",
        r"limits",
        r"anchor|alias",
    ),
    "anchor on an account's key": (
        "runtimes:\n  claude_code:\n    accounts:\n      kit:\n        limits: &w {}\n",
        r"limits",
        r"anchor|alias",
    ),
    "merge key in the runtime": (
        "base: &base\n  limits:\n    session: {}\nruntimes:\n  claude_code:\n    <<: *base\n",
        r"runtimes|<<|limits",
        r"merge|anchor|alias",
    ),
    "flow-style runtime": (
        "runtimes:\n  claude_code: {limits: {session: {}}}\n",
        r"claude_code|limits",
        r"flow",
    ),
    "flow-style accounts": (
        "runtimes:\n  claude_code:\n    accounts: {kit: {limits: {}}}\n",
        r"accounts|limits",
        r"flow",
    ),
    "quoted key": (
        'runtimes:\n  claude_code:\n    "limits":\n      session: {}\n',
        r"limits",
        r"quoted",
    ),
    "block brought in by an alias": (
        "runtimes:\n  claude_code: &rt\n    limits: {}\n  other: *rt\n",
        r"runtimes\.(claude_code|other)",
        r"merge|alias|anchor",
    ),
    "several documents": (
        "runtimes:\n  claude_code:\n    limits: {}\n---\nversion: 1\n",
        r"abk\.yaml",
        r"several documents",
    ),
}


@pytest.mark.parametrize("name", CASES)
def test_each_is_refused_with_the_key_and_a_reason(name: str) -> None:
    text, key, reason = CASES[name]

    with pytest.raises(ConfigMigrateError) as refused:
        migrate(text)

    assert re.search(key, str(refused.value)), str(refused.value)
    assert re.search(reason, str(refused.value), re.IGNORECASE), str(refused.value)
