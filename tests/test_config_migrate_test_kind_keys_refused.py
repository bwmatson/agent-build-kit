"""The test-kind rename refuses, naming the key, what it cannot edit safely."""

from __future__ import annotations

import re

import pytest

from agent_build_kit.config_migrate import ConfigMigrateError, migrate

# name -> (text, a pattern for the key the message names, a pattern for the reason it gives)
CASES = {
    "old and new spelling of one setting": (
        "global_limits:\n  tier2_lock_wait_seconds: 600\n  e2e_lock_wait_seconds: 300\n",
        r"tier2_lock_wait_seconds|e2e_lock_wait_seconds",
        r"both|together",
    ),
    "anchor on an old key": (
        "global_limits:\n  tier2_lock_wait_seconds: &w 600\n",
        r"tier2_lock_wait_seconds|global_limits",
        r"anchor|alias",
    ),
    "merge key in the block": (
        "base: &base\n  e2e_marker: slow\nrepos:\n  app:\n    tests:\n      <<: *base\n"
        "      tier2_schedule: weekly\n",
        r"tests|<<|tier2_schedule",
        r"merge|anchor|alias",
    ),
    "flow-style block": (
        "repos:\n  app:\n    path: app\n    tests: {tier2_schedule: weekly}\n",
        r"tests|tier2_schedule",
        r"flow",
    ),
    "block brought in by a merge key above it": (
        "repos:\n  app: &app\n    path: app\n    tests:\n      tier2_schedule: weekly\n"
        "  platform:\n    <<: *app\n    path: platform\n",
        r"repos\.platform\.tests",
        r"merge|alias",
    ),
    "block of a repo that is an alias of another": (
        "repos:\n  app: &app\n    path: app\n    tests:\n      tier2_schedule: weekly\n"
        "  platform: *app\n",
        r"repos\.(app|platform)\.tests",
        r"merge|alias",
    ),
    "quoted old key": (
        'global_limits:\n  "tier2_lock_wait_seconds": 600\n',
        r"tier2_lock_wait_seconds",
        r"quoted",
    ),
    "several documents with an old key": (
        "global_limits:\n  tier2_lock_wait_seconds: 600\n---\nversion: 1\n",
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
