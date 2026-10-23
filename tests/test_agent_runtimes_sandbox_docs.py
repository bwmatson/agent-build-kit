"""`docs/agent-runtimes.md` says what ACP at the `process` coverage means and what is unproven
(spec: sandbox-acp, group 2)."""

from __future__ import annotations

import re

from tests.doc_text import ROOT, squashed


def acp_sandbox_section() -> str:
    """The section whose heading names ACP and the sandbox, squashed."""
    text = (ROOT / "docs" / "agent-runtimes.md").read_text(encoding="utf-8")
    sections = re.split(r"\n(?=#{2,4} )", text)
    found = [
        s for s in sections if re.match(r"#{2,4} .*(ACP|acp).*sandbox|#{2,4} .*sandbox.*ACP", s)
    ]
    assert found, "agent-runtimes.md has no section on ACP and the sandbox"
    return squashed(found[0])


def test_the_section_says_what_process_coverage_confines() -> None:
    text = acp_sandbox_section()

    assert "process" in text
    assert "terminal" in text
    assert "read_text_file" in text
    assert "state folders" in text


def test_the_section_says_what_is_unproven_and_how_a_person_proves_it() -> None:
    text = acp_sandbox_section()

    assert "unverified against a real agent" in text
    assert "abk policy check" in text
    assert "probe" in text
    for denial in ("write", "read", "host"):
        assert denial in text


def test_the_section_says_the_clients_own_file_writes_are_not_the_sandbox() -> None:
    text = acp_sandbox_section()

    assert "write_text_file" in text
    assert "worktree" in text
