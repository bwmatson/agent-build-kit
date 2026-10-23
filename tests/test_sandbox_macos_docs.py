"""The README, the design document and the changelog say what the macOS backend needs and
where it falls short."""

from __future__ import annotations

import re

from tests.doc_text import ROOT, squashed, unreleased_bullets


def requirements() -> str:
    text = squashed((ROOT / "README.md").read_text(encoding="utf-8"))
    return text[text.index("Requirements:") :].split(" ## ")[0]


def limits() -> str:
    """The design document's section on what the sandbox does not cover."""
    text = (ROOT / "docs" / "sandbox-design.md").read_text(encoding="utf-8")
    start = text.index("## What it covers, and what it does not")
    return text[start:].split("\n## ")[0]


def seatbelt_limits() -> str:
    """The bullets of that section that are about Seatbelt, squashed."""
    bullets = re.split(r"\n(?=- )", limits())
    return " ".join(squashed(bullet) for bullet in bullets if "Seatbelt" in bullet)


def test_the_readme_requirements_say_macos_needs_nothing_installed() -> None:
    line = requirements()

    assert "macOS" in line
    assert "sandbox-exec" in line


def test_the_design_records_that_apple_marks_sandbox_exec_deprecated() -> None:
    assert "sandbox-exec" in seatbelt_limits()
    assert "deprecated" in seatbelt_limits()


def test_the_design_records_that_dns_and_unix_sockets_stay_reachable_on_macos() -> None:
    text = seatbelt_limits()

    assert "DNS" in text
    assert "Unix socket" in text


def test_the_design_records_that_a_network_rule_can_be_silently_ineffective() -> None:
    text = seatbelt_limits()

    assert "silently" in text
    assert "direct connection" in text


def test_the_design_no_longer_says_the_macos_backend_is_not_built() -> None:
    text = squashed((ROOT / "docs" / "sandbox-design.md").read_text(encoding="utf-8"))

    assert "before it is built" not in text


def test_the_changelog_has_one_bullet_for_the_macos_backend() -> None:
    found = [b for b in unreleased_bullets() if "Seatbelt" in b]

    assert len(found) == 1
    assert "macOS" in found[0]
    assert "sandbox-exec" in found[0]
