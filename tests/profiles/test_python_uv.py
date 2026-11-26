"""The python-uv profile's red words: what its tests prompt says counts as red, built from the
red check's own sets (spec: tdd-loop)."""

from __future__ import annotations

import pytest

from agent_build_kit import profiles
from agent_build_kit.pipeline.red_check import ACCEPTED_TYPES, MISSING_NAMES


@pytest.mark.parametrize("stubbed", [True, False], ids=["stubbed", "unstubbed"])
def test_the_red_words_follow_the_red_checks_sets(stubbed: bool) -> None:
    words = profiles.get("python-uv").prompt_words
    words = words.red_stubbed if stubbed else words.red
    expected = set(ACCEPTED_TYPES) - (set(MISSING_NAMES) if stubbed else set())
    not_red = " ".join(words.not_red)

    assert set(words.red_types) == expected
    if stubbed:
        assert all(name in not_red for name in MISSING_NAMES)
    for word in ("conftest", "collected", "pytest.raises"):
        assert word in not_red
    assert "stub" in words.advice
