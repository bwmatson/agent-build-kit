"""The node-npm profile's red words: what its tests prompt says counts as red, built from the
profile's own red check sets (spec: tdd-loop)."""

from __future__ import annotations

import pytest

from agent_build_kit import profiles
from agent_build_kit.profiles.node_npm import BROKEN_TEST_ERRORS, RED_ERRORS


@pytest.mark.parametrize("stubbed", [True, False], ids=["stubbed", "unstubbed"])
def test_the_red_words_follow_the_profiles_sets(stubbed: bool) -> None:
    words = profiles.get("node-npm").prompt_words
    words = words.red_stubbed if stubbed else words.red
    not_red = " ".join(words.not_red)

    assert set(words.red_types) == set(RED_ERRORS)
    assert all(name in not_red for name in BROKEN_TEST_ERRORS)
