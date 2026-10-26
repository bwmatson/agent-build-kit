## From `a-split-drops-merged-edges-into-a-kept-mixed-change/2`

- test_the_changelog_has_one_unreleased_bullet_for_the_moved_units in tests/docs/test_planning_split_units_docs.py still slices the Unreleased section by hand. It could use unreleased_bullets() from tests/doc_text.py instead. That code was already there before this branch; the rework only rewrapped it.
