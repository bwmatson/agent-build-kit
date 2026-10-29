"""The hook policy asks the shared function for a checkout; it keeps no wrapper of its own."""

from __future__ import annotations

from agent_build_kit.hooks import policy


def test_the_policy_has_no_checkout_wrapper_of_its_own() -> None:
    assert not hasattr(policy, "_checkout_of")
