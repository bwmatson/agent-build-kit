"""The README, the configuration reference and the design document say what the sandbox
needs and where its keys live."""

from __future__ import annotations

import re

from tests.doc_text import ROOT, squashed


def requirements() -> str:
    text = squashed((ROOT / "README.md").read_text(encoding="utf-8"))
    return text[text.index("Requirements:") :].split(" ## ")[0]


def test_the_readme_requirements_name_the_platforms_the_sandbox_runs_on() -> None:
    line = requirements()

    assert "Linux" in line
    assert "WSL2" in line
    assert "macOS" in line


def test_configuration_lists_the_sandbox_keys() -> None:
    text = (ROOT / "docs" / "configuration.md").read_text(encoding="utf-8")

    for key in ("sandbox.enabled", "sandbox.backend", "sandbox.required"):
        assert key in text.replace("`", ""), key
    assert re.search(r"sandbox\.(write|read|hosts)", text)


def test_configuration_says_which_file_holds_the_sandbox_lists() -> None:
    text = (ROOT / "docs" / "configuration.md").read_text(encoding="utf-8")
    table = text[text.index("#### Which file holds a setting") :]
    rows = [line for line in table.splitlines() if line.startswith("|") and "sandbox" in line]

    assert rows
    assert any("abk.local.yaml" in row for row in rows)


def test_the_design_document_points_at_the_specs() -> None:
    text = (ROOT / "docs" / "sandbox-design.md").read_text(encoding="utf-8")

    assert "specs/sandbox-backends" in text
