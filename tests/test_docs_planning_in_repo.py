"""The documents describe a planning repo that is also a code repo (spec: planning-worktree,
planning-publish, planning-in-repo-init)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.prompt_text import flat

ROOT = Path(__file__).resolve().parents[1]
CONFIGURATION = ROOT / "docs" / "configuration.md"
DOCUMENTS = [
    ROOT / "docs" / "architecture.md",
    CONFIGURATION,
    ROOT / "docs" / "init.md",
    ROOT / "docs" / "tracks.md",
    ROOT / "README.md",
]
MARKER = "abk-pipeline-worktree"


@pytest.mark.parametrize("path", DOCUMENTS, ids=lambda p: p.name)
def test_the_document_names_the_publish_setting_the_pipeline_worktree_and_the_marker(
    path: Path,
) -> None:
    text = flat(path.read_text())
    missing = [
        term for term in ("planning.publish", "pipeline worktree", MARKER) if term not in text
    ]
    assert not missing, f"{path.name} does not name {missing}"


def test_configuration_lists_publish_beside_self_pull_with_its_values_and_default() -> None:
    text = CONFIGURATION.read_text()
    publish = re.search(r"^\s*publish:\s*(\S+)(.*(?:\n\s{20,}#.*)*)", text, re.M)
    assert publish, "docs/configuration.md has no publish key"
    assert publish[1] == "direct"
    assert "direct | branch" in publish[0]
    self_pull = re.search(r"^\s*self_pull:", text, re.M)
    assert self_pull
    assert abs(text[: publish.start()].count("\n") - text[: self_pull.start()].count("\n")) <= 4
    prose = flat(CONFIGURATION.read_text())
    assert "`planning.publish`" in prose
    assert "default" in prose.split("`planning.publish`", 1)[1][:600].lower()
