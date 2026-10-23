"""The toolchain profiles document describes the optional `sandbox_paths` member (spec:
sandbox-profile-paths)."""

from __future__ import annotations

from tests.doc_text import ROOT, squashed

DOC = (ROOT / "docs" / "toolchain-profiles.md").read_text(encoding="utf-8")


def test_the_protocol_table_has_a_sandbox_paths_row() -> None:
    rows = [line for line in DOC.splitlines() if line.startswith("| `sandbox_paths(")]

    [row] = rows
    text = squashed(row)
    assert "optional" in text
    assert "SandboxPaths" in text
    assert "hosts" in text


def test_adding_a_profile_says_what_the_member_is_for() -> None:
    section = DOC[DOC.index("## Adding a profile") :]

    assert "sandbox_paths" in squashed(section)
