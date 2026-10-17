"""The docs describe the node profile as implemented (spec: node-npm-workspaces)."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = [
    ROOT / "README.md",
    ROOT / "docs" / "toolchain-profiles.md",
    ROOT / "docs" / "configuration.md",
    ROOT / "src" / "agent_build_kit" / "skills" / "abk-config" / "SKILL.md",
]
UNIMPLEMENTED = re.compile(
    r"declared(?:,|\s+but|\s+and)?\s+(?:and\s+)?not\s+(?:yet\s+)?implemented"
)


def node_section() -> str:
    text = (ROOT / "docs" / "toolchain-profiles.md").read_text(encoding="utf-8")
    found = re.search(r"^## `node-npm`\n(.*?)(?=^## )", text, re.DOTALL | re.MULTILINE)
    assert found, "docs/toolchain-profiles.md has no `node-npm` section"
    return found.group(1)


def test_no_document_calls_the_node_profile_declared_and_not_implemented() -> None:
    saying_so = [
        path.name for path in DOCS if UNIMPLEMENTED.search(path.read_text(encoding="utf-8"))
    ]

    assert saying_so == []


def test_the_node_section_says_nothing_still_raises() -> None:
    assert "still raises" not in node_section()


def test_the_node_section_has_a_command_table_like_the_python_one() -> None:
    section = node_section()

    assert "| Method | Command |" in section
    for method in ("lint_command", "test_commands", "e2e_commands", "acceptance_commands"):
        assert re.search(rf"^\| `{method}", section, re.MULTILINE), f"no table row for {method}"


def test_the_node_section_documents_the_file_name_marker() -> None:
    assert ".<marker>.test." in node_section()


def test_the_config_skill_explains_the_node_marker_as_a_file_name() -> None:
    skill = DOCS[-1].read_text(encoding="utf-8")

    assert ".<marker>.test." in skill
