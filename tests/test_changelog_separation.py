"""Separating bullets that the union merge of a changelog ran together."""

from agent_build_kit.changelog_form import changelog_problems, separate_bullets
from tests.test_changelog import WELL_FORMED

JOINED = WELL_FORMED.replace(
    "\n- Another thing, with its reason.", "- Another thing, with its reason."
)


def test_bullets_run_together_get_their_blank_line_back() -> None:
    assert changelog_problems(JOINED) != []

    separated = separate_bullets(JOINED)

    assert changelog_problems(separated) == []
    assert separated == WELL_FORMED


def test_a_well_formed_changelog_comes_back_unchanged() -> None:
    assert separate_bullets(WELL_FORMED) == WELL_FORMED


def test_continuation_lines_and_a_bullet_under_a_heading_are_left_alone() -> None:
    text = "# Changelog\n\n## Unreleased\n- Directly under.\n  wrapped on.\n  and on.\n\n- Next.\n"

    assert separate_bullets(text) == text
