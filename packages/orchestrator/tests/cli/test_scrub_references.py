"""Issue and pull-request references are scrubbed to `<ref>` (spec: stored-text-scrub)."""

from __future__ import annotations

from agent_build_kit.scrub_terms import scrub_references


def test_a_reference_after_a_redacted_owner_becomes_a_ref_token() -> None:
    assert scrub_references("<redacted>/app#15 failed") == "<redacted>/<ref> failed"


def test_text_without_a_reference_is_unchanged() -> None:
    text = "nothing to see, not even a hash: #15 or a#1\n"

    assert scrub_references(text) == text


def test_a_second_pass_changes_nothing() -> None:
    once = scrub_references("see <redacted>/app#15 and svc-a#7")

    assert scrub_references(once) == once
