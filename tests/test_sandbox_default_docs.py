"""The documents say the sandbox is on by default and the config guard only warns, and stop
asking people to stop the timer (spec: sandbox-default)."""

from __future__ import annotations

import pytest

from tests.doc_text import ROOT, squashed, unreleased_bullets

SANDBOX_ONLY = ["README.md"]
GUARD_DOCUMENTS = [
    "docs/configuration.md",
    "docs/architecture.md",
    "docs/designs/sandbox-design.md",
    "docs/runbooks/landing-changes.md",
    "src/agent_build_kit/skills/abk-config/SKILL.md",
    "src/agent_build_kit/skills/abk-pipeline/SKILL.md",
]

SANDBOX_PHRASES = [
    "sandbox is on by default",
    "sandbox.enabled: false",
    "no backend",
]
GUARD_PHRASES = [
    "at any time",
    "warning",
    "diff",
]
STALE_PHRASES = [
    "configchanged",
    "stop the timer",
    "stop the tick timer",
    "systemctl --user stop",
]


def text_of(path: str) -> str:
    return squashed((ROOT / path).read_text(encoding="utf-8")).lower()


def assert_says(path: str, phrases: list[str]) -> None:
    text = text_of(path)
    missing = [p for p in phrases if p not in text]
    stale = [p for p in STALE_PHRASES if p in text]

    assert not missing, f"{path} does not say: {missing}"
    assert not stale, f"{path} still says: {stale}"


@pytest.mark.parametrize("path", SANDBOX_ONLY)
def test_the_document_says_the_sandbox_is_on_by_default(path: str) -> None:
    assert_says(path, SANDBOX_PHRASES)


@pytest.mark.parametrize("path", GUARD_DOCUMENTS)
def test_the_document_says_the_sandbox_is_on_and_a_config_change_only_warns(path: str) -> None:
    assert_says(path, SANDBOX_PHRASES + GUARD_PHRASES)


def test_the_changelog_has_a_bullet_for_the_default() -> None:
    bullets = [b.lower() for b in unreleased_bullets()]

    assert any("sandbox" in b and "on by default" in b for b in bullets)
