"""The reference, the move runbook and the changelog describe the dropped edges of a kept mixed
change and the `Needs:` note."""

import re

from tests.doc_text import entry, runbook_step, unreleased_bullets


def test_the_reference_names_the_three_reasons_for_a_dropped_edge():
    text = entry()
    assert re.search(r"merged unit of another repo", text, re.I)
    assert re.search(r"another project", text, re.I)
    assert re.search(r"mixed change kept in the source", text, re.I)
    assert re.search(r"dropped", text, re.I)
    assert re.search(r"note|printed line", text, re.I)


def test_the_reference_says_a_needs_line_on_a_merged_group_is_a_note_copied_unchanged():
    text = entry()
    assert re.search(r"Needs: ?[^.]*merged group[^.]*note", text, re.I)
    assert re.search(r"copied unchanged", text, re.I)


def test_the_runbook_step_two_says_a_kept_mixed_change_keeps_its_moving_repo_units():
    text = runbook_step(2)
    assert re.search(r"mixed change kept in the source[^.]*units", text, re.I)
    assert re.search(r"dropped", text, re.I)
    assert re.search(r"entry stays", text, re.I)


def test_the_runbook_step_four_says_the_notes_name_the_reason_and_the_needs_group():
    text = runbook_step(4)
    assert re.search(r"dropped[- ]edge notes? name", text, re.I)
    assert "Needs:" in text
    assert re.search(r"merged history", text, re.I)


def test_the_changelog_has_one_unreleased_bullet_for_the_kept_mixed_change():
    bullets = [
        b for b in unreleased_bullets() if "abk planning split" in b and "kept in the source" in b
    ]
    assert len(bullets) == 1
    text = bullets[0]
    assert re.search(r"mixed change", text)
    assert re.search(r"Needs: ", text)
    assert re.search(r"\bnote\b", text)
    assert re.search(r"another repo", text)
