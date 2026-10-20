"""The runtimes document, AGENTS.md and the changelog say what the drift test checks."""

from __future__ import annotations

import re
from pathlib import Path

from tests.prompt_text import flat

ROOT = Path(__file__).resolve().parents[2]
RUNTIMES = flat((ROOT / "docs" / "agent-runtimes.md").read_text())
RUNTIMES_RAW = (ROOT / "docs" / "agent-runtimes.md").read_text()
AGENTS = flat((ROOT / "AGENTS.md").read_text())
CHANGELOG = (ROOT / "CHANGELOG.md").read_text()
UNRELEASED = CHANGELOG.split("## Unreleased", 1)[1].split("\n## ", 1)[0]
GAP_HEADING = "Claude scenarios without an ACP sibling"


def test_the_runtimes_document_no_longer_says_claude_scenarios_are_unchecked() -> None:
    assert "does not check that a `claude_code` scenario has an `acp` variant" not in RUNTIMES


def test_the_runtimes_document_names_the_table_of_signals() -> None:
    assert "`AGENT_SIGNALS`" in RUNTIMES


def test_the_runtimes_document_has_the_gap_list_section_with_the_current_list() -> None:
    section = re.search(
        rf"^#+ {GAP_HEADING}\n(.*?)(?=^#|\Z)", RUNTIMES_RAW, re.MULTILINE | re.DOTALL
    )

    assert section
    for name in ("test_build_unit.py", "test_graph_unit.py", "test_telemetry_stack.py"):
        assert name in section.group(1)


def test_the_runtimes_document_says_a_tag_is_compared_with_what_the_test_starts() -> None:
    assert re.search(r"tag[^.]*compared with[^.]*starts", RUNTIMES)


def test_the_runtimes_document_records_other_repos_get_no_such_test_yet() -> None:
    assert re.search(r"other code repos[^.]*no such drift test[^.]*;[^.]*follow-up", RUNTIMES)


def test_agents_md_says_how_a_new_live_test_is_tagged() -> None:
    assert re.search(r"one (runtime )?tag[^.]*start", AGENTS)
    assert "ACP_ONLY_REASONS" in AGENTS


def test_the_unreleased_section_of_the_changelog_mentions_the_change() -> None:
    assert re.search(r"drift test[^-]*(every|each) (live|e2e)", UNRELEASED, re.DOTALL)
    assert "ACP sibling" in UNRELEASED
