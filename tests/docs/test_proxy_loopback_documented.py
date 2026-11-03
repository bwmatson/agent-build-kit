"""The sandbox design and the changelog say that the proxy explains a refused loopback host (spec:
agent-test-commands)."""

from __future__ import annotations

from tests.doc_text import ROOT, unreleased_bullets
from tests.prompt_text import flat

DESIGN = flat((ROOT / "docs" / "designs" / "sandbox-design.md").read_text())


def test_the_design_says_what_a_refused_loopback_host_is_told() -> None:
    assert "not reachable from the sandbox" in DESIGN
    assert "outside the sandbox" in DESIGN


def test_the_changelog_has_a_bullet_for_it() -> None:
    assert any("loopback" in bullet and "403" in bullet for bullet in unreleased_bullets())
