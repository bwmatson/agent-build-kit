"""The documents and the `abk-config` skill show `runtimes.<name>.models` and call the flat
`models:` block deprecated (spec: runtime-models)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOCUMENTS = (
    ROOT / "docs" / "configuration.md",
    ROOT / "docs" / "agent-runtimes.md",
    ROOT / "src" / "agent_build_kit" / "skills" / "abk-config" / "SKILL.md",
)
IDS = ["configuration.md", "agent-runtimes.md", "abk-config-skill"]


def squashed(path: Path) -> str:
    """The file's text on one line with the code ticks dropped, so a wrapped sentence matches."""
    return " ".join(path.read_text(encoding="utf-8").replace("`", "").split())


@pytest.mark.parametrize("path", DOCUMENTS, ids=IDS)
def test_the_runtime_form_is_shown(path: Path) -> None:
    text = squashed(path)

    assert "runtimes.<name>.models" in text
    assert "runtimes.claude_code.models" in text or re.search(
        r"claude_code:.{0,1500}\smodels:", text
    )


@pytest.mark.parametrize("path", DOCUMENTS, ids=IDS)
def test_the_flat_block_is_described_as_deprecated(path: Path) -> None:
    text = squashed(path)

    assert re.search(r"(flat|top-level) models.{0,300}deprecated", text, re.I) or re.search(
        r"deprecated.{0,300}(flat|top-level) models", text, re.I
    )


@pytest.mark.parametrize("path", DOCUMENTS, ids=IDS)
def test_no_example_puts_the_roles_in_a_top_level_block(path: Path) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()

    assert [line for line in lines if line.startswith("models:")] == []
