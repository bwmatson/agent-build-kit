"""A unit's saved feedback source in the store: the old values are read as the kind they meant
and only the new values are written."""

import json

import pytest

from agent_build_kit.pipeline.unit_store import FeedbackSource, UnitStore
from tests.factories import unit

UNIT_ID = "add-marker/1"
OLD_TO_NEW = {"tier" + "1": FeedbackSource.UNIT_TEST, "tier" + "2": FeedbackSource.E2E}


def stored_with(tmp_path, source: str) -> UnitStore:
    """A store whose one unit was written with `source` as its recorded `feedback_source`."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit(UNIT_ID)])
    raw = json.loads(store.path.read_text())
    raw["units"][0]["feedback_source"] = source
    store.path.write_text(json.dumps(raw))
    return store


@pytest.mark.parametrize("old", sorted(OLD_TO_NEW))
def test_a_store_written_before_the_rename_reads_the_source_as_the_kind_it_meant(
    tmp_path, old
) -> None:
    store = stored_with(tmp_path, old)

    assert store.get(UNIT_ID).feedback_source is OLD_TO_NEW[old]


@pytest.mark.parametrize("old", sorted(OLD_TO_NEW))
def test_the_next_write_holds_only_the_new_value(tmp_path, old) -> None:
    store = stored_with(tmp_path, old)

    store.set_run_log(UNIT_ID, "run.log")

    written = json.loads(store.path.read_text())["units"][0]["feedback_source"]
    assert written == OLD_TO_NEW[old].value
    assert old not in store.path.read_text()


def test_a_value_that_is_no_source_is_still_refused(tmp_path) -> None:
    with pytest.raises(ValueError):
        FeedbackSource("tier3")
