"""The authoring skill and the documents give the priority scale as 0 (emergency) to 5."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit import skills
from tests.prompt_text import flat

DOCS = Path(__file__).resolve().parents[2] / "docs"


def test_the_authoring_skill_says_when_to_use_zero_and_no_longer_that_it_bypasses_no_limit() -> (
    None
):
    text = flat(skills.source("abk-authoring")).lower()

    assert "scale is 0 to 5" in text
    assert "0 is for work that must go before all urgent work" in text
    assert "rare" in text
    assert "bypasses no limit" not in text


@pytest.mark.parametrize("name", ["architecture.md", "unit-graph.md"])
def test_the_documents_give_the_scale_as_zero_to_five(name: str) -> None:
    text = flat((DOCS / name).read_text(encoding="utf-8"))

    assert "0 (emergency) to 5" in text
