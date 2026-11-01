"""The one reader of a document's `##` section, which the pull request's Why and the tracker's
change item share."""

from __future__ import annotations

import pytest

from agent_build_kit.pipeline.pr_body import section_text

DOCUMENT = "# Title\n\n## Why\n\nBecause.\n\nMore.\n\n## What Changes\n\n- One.\n"


@pytest.mark.parametrize(
    ("heading", "wanted"),
    [("Why", "Because.\n\nMore."), ("What Changes", "- One."), ("Impact", "")],
)
def test_a_section_is_the_text_under_its_heading(heading: str, wanted: str) -> None:
    assert section_text(DOCUMENT, heading) == wanted


def test_a_tab_after_the_hashes_still_opens_the_section() -> None:
    assert section_text("##\tWhy\nBecause.\n", "Why") == "Because."
