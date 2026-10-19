"""The table of old and new spellings of the test kinds.

Spec: test-kind-names-are-accepted-both-ways.
"""

from __future__ import annotations

import pytest

from agent_build_kit.compat_names import (
    KIND_FORMS,
    Place,
    is_old_spelling,
    new_spelling,
    notice,
    old_spelling,
)
from agent_build_kit.model import TestTier

OLD_TO_NEW = [
    (Place.TAG, "tier1", "unit-test"),
    (Place.TAG, "tier2", "e2e-test"),
    (Place.SETTING, "tier1_command_seconds", "unit_test_command_seconds"),
    (Place.SETTING, "tier1_repeat_runs", "unit_test_repeat_runs"),
    (Place.SETTING, "tier2_lock_wait_seconds", "e2e_lock_wait_seconds"),
    (Place.SETTING, "tier2_schedule", "e2e_schedule"),
    (Place.SETTING, "tests.tier2_marker", "tests.e2e_marker"),
    (Place.SETTING, "tier2_runtimes", "e2e_runtimes"),
    (Place.SETTING, "tier2_splits", "e2e_splits"),
    (Place.VALUE, "tier1", "unit-test"),
    (Place.VALUE, "tier2", "e2e-test"),
    (Place.STATE_FILE, "tier2-held.json", "e2e-held.json"),
    (Place.STATE_FILE, "tier2.lock", "e2e.lock"),
    (Place.METRIC, "tier1_runs", "unit_test_runs"),
    (Place.METRIC, "tier2_runs", "e2e_runs"),
]


@pytest.mark.parametrize(("place", "old", "new"), OLD_TO_NEW)
def test_an_old_spelling_maps_to_its_new_one(place: Place, old: str, new: str) -> None:
    assert is_old_spelling(place, old)
    assert new_spelling(place, old) == new


@pytest.mark.parametrize(("place", "old", "new"), OLD_TO_NEW)
def test_a_new_spelling_is_returned_unchanged(place: Place, old: str, new: str) -> None:
    assert not is_old_spelling(place, new)
    assert new_spelling(place, new) == new


def test_a_name_the_table_does_not_hold_is_returned_unchanged() -> None:
    assert new_spelling(Place.SETTING, "max_unit_lines") == "max_unit_lines"
    assert new_spelling(Place.TAG, "integration") == "integration"


def test_each_kind_has_the_old_name_it_was_known_by() -> None:
    assert old_spelling(TestTier.UNIT_TEST) == "tier1"
    assert old_spelling(TestTier.E2E_TEST) == "tier2"


def test_the_notice_names_the_old_spelling_the_new_one_and_where_it_was_read() -> None:
    text = notice(Place.TAG, "tier2", "tasks.md line 7")

    assert "tier2" in text
    assert "e2e-test" in text
    assert "tasks.md line 7" in text


def test_integration_test_is_returned_unchanged_and_is_not_an_old_spelling() -> None:
    kind = TestTier.INTEGRATION_TEST.value
    for place in (Place.TAG, Place.VALUE):
        assert new_spelling(place, kind) == kind
        assert not is_old_spelling(place, kind)
    assert kind not in KIND_FORMS
    assert kind not in {old for _, old, _ in OLD_TO_NEW}
    assert kind not in {new for _, _, new in OLD_TO_NEW}
    assert all(forms.tag != kind for forms in KIND_FORMS.values())
    with pytest.raises(StopIteration):
        old_spelling(TestTier.INTEGRATION_TEST)
