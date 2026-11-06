"""The documents and the two skills name the resolution lane, its cap `max_concurrent_resolutions`,
the comment runs it holds and the old key `max_concurrent_restacks`, and no longer call the lane the
restack lane."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit import skills
from tests.prompt_text import flat

ROOT = Path(__file__).resolve().parents[2]


def doc(*parts: str) -> str:
    return ROOT.joinpath(*parts).read_text(encoding="utf-8")


DOCUMENTS = {
    "docs/architecture.md": doc("docs", "architecture.md"),
    "docs/configuration.md": doc("docs", "configuration.md"),
    "docs/cli.md": doc("docs", "cli.md"),
    "docs/designs/unit-graph.md": doc("docs", "designs", "unit-graph.md"),
    "docs/designs/worker-design.md": doc("docs", "designs", "worker-design.md"),
    "skill abk-config": skills.source("abk-config"),
    "skill abk-pipeline": skills.source("abk-pipeline"),
}
# The documents that spell out the settings, where the old key is told to a reader.
SETTINGS_DOCUMENTS = ["docs/configuration.md", "skill abk-config"]


def read(name: str) -> str:
    return flat(DOCUMENTS[name]).lower()


@pytest.mark.parametrize("name", DOCUMENTS)
def test_each_document_names_the_lane_its_cap_and_the_comment_runs(name: str) -> None:
    text = read(name)
    assert "resolution lane" in text
    assert "max_concurrent_resolutions" in text
    assert "comment run" in text
    assert "restack lane" not in text


@pytest.mark.parametrize("name", SETTINGS_DOCUMENTS)
def test_the_settings_documents_name_the_old_key_as_deprecated(name: str) -> None:
    text = read(name)
    assert "`max_concurrent_restacks`" in text
    assert "deprecat" in text
    assert "abk config --migrate" in text
    assert "comment run" in text


def test_the_worker_design_names_the_resolve_worker() -> None:
    text = read("docs/designs/worker-design.md")
    assert "`resolve`" in text
    assert "`restack` (" not in text
    assert "comment run" in text
