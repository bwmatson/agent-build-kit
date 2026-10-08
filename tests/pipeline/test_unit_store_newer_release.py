"""A store written by a newer release.

Every process of an installation reads the same file, and a release can add a
field to a stored unit while an older process is still running. An empty field
carries nothing, so the older reader ignores it; one holding a value is
information it cannot keep, so it is refused with its cause.
"""

import json

import pytest

from agent_build_kit.pipeline.unit_store import UnitStore, corrupt_store_message
from tests.factories import unit as app_unit

UNIT_ID = "add-marker/1"


def _store_with(tmp_path, **extra) -> UnitStore:
    """A store file whose one unit carries keys this release has no field for."""
    path = tmp_path / "units.json"
    UnitStore(path).upsert([app_unit(UNIT_ID)])
    raw = json.loads(path.read_text())
    raw["units"][0].update(extra)
    path.write_text(json.dumps(raw))
    return UnitStore(path)


@pytest.mark.parametrize("empty", [None, "", [], {}, False])
def test_an_unknown_key_with_an_empty_value_is_read(tmp_path, empty) -> None:
    store = _store_with(tmp_path, from_newer_release=empty)

    assert [u.id for u in store.all()] == [UNIT_ID]
    assert store.get(UNIT_ID).id == UNIT_ID


@pytest.mark.parametrize("empty", [None, "", [], {}, False])
def test_the_next_write_omits_an_empty_unknown_key(tmp_path, empty) -> None:
    store = _store_with(tmp_path, from_newer_release=empty)

    store.set_run_log(UNIT_ID, "run.log")

    written = json.loads(store.path.read_text())["units"][0]
    assert "from_newer_release" not in written
    assert written["run_log"] == "run.log"


@pytest.mark.parametrize("valued", ["abc", ["x"], {"k": 1}, True, 3])
def test_an_unknown_key_with_a_value_is_refused_with_its_cause(tmp_path, valued) -> None:
    store = _store_with(tmp_path, from_newer_release=valued)

    with pytest.raises(ValueError) as refused:
        store.all()

    message = str(refused.value)
    assert "newer release" in message
    assert UNIT_ID in message
    assert "from_newer_release" in message
    assert str(valued) in message


def test_a_wrong_type_on_a_known_field_keeps_todays_message(tmp_path) -> None:
    store = _store_with(tmp_path, from_newer_release=None, check_reruns="many")

    with pytest.raises(ValueError, match=corrupt_store_message(store.path)) as refused:
        store.all()

    assert "newer release" not in str(refused.value)
