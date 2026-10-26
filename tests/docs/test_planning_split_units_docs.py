"""The reference and the move runbook say which units `abk planning split` moves."""

import re

from tests.doc_text import ROOT, entry, runbook_step, squashed


def test_the_reference_says_units_of_archive_entries_move():
    assert re.search(r"units? of (a moving repo's |the moving repo's )?archive entr", entry(), re.I)


def test_the_reference_gives_the_matching_and_the_two_refusals():
    text = entry()
    assert re.search(r"matched (to (their|its) change )?by name", text, re.I)
    assert "ambiguous" in text.lower()
    assert "spans" in text or "spanning" in text.lower()


def test_the_reference_says_a_unit_with_no_change_directory_moves_by_its_repo():
    assert re.search(r"no change directory[^.]*\bby (its|their) repo", entry(), re.I)


def test_the_reference_says_a_foreign_merged_dependency_is_dropped_with_a_note():
    text = entry()
    assert re.search(r"merged unit of another repo", text, re.I)
    assert re.search(r"dropped", text, re.I)
    assert re.search(r"note|printed line", text, re.I)


def test_the_reference_names_the_unit_counts_by_origin():
    text = entry().lower()
    for word in ("active", "archived", "no change directory", "left in the source"):
        assert word in text


def test_the_runbook_no_longer_says_archived_units_are_left_behind():
    text = runbook_step(2)
    assert "is archived or dropped, not copied" not in text
    assert "Archived changes that belong to other repos stay" in text
    assert re.search(r"archive entries move with their units", text, re.I)


def test_the_runbook_dry_run_compares_unit_counts_by_origin():
    text = runbook_step(4).lower()
    for word in ("active", "archived", "no change directory", "left in the source"):
        assert word in text
    assert "dropped" in text


def test_the_runbook_cutover_expects_the_dropped_edges():
    assert re.search(r"dropped (dependenc|edge)", runbook_step(5), re.I)


def test_the_changelog_has_one_unreleased_bullet_for_the_moved_units():
    unreleased = (
        (ROOT / "CHANGELOG.md").read_text().split("## Unreleased", 1)[1].split("\n## ", 1)[0]
    )
    bullets = [
        squashed(b)
        for b in re.split(r"\n\s*\n", unreleased)
        if "abk planning split" in b and "units of" in b
    ]
    assert len(bullets) == 1
    text = bullets[0]
    assert re.search(r"archive entr", text) and "units" in text
    assert "no directory" in text
    assert re.search(r"merged unit of another repo", text)
    assert "dropped" in text
