"""A stored unit applies the newer-release and old-engine rules itself.

The rule lives on the class, so every reader of a stored unit gets the same
tolerance, not only the store, and the dict it is handed is left as it was.
"""

import copy

import pytest
from pydantic import ValidationError

from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.runtimes.base import ToolPolicy
from tests.factories import stored_unit
from tests.factories import unit as app_unit

UNIT_ID = "add-marker/1"


def _record(**extra) -> dict:
    return {**stored_unit(UNIT_ID).model_dump(mode="json"), **extra}


@pytest.mark.parametrize("empty", [None, "", [], {}, False])
def test_an_empty_unknown_key_is_dropped(empty) -> None:
    validated = StoredUnit.model_validate(_record(from_newer_release=empty))

    assert validated.id == UNIT_ID
    assert "from_newer_release" not in validated.model_dump()


@pytest.mark.parametrize(("field", "empty"), [("resume_from", ""), ("classic_run", {})])
def test_an_old_engine_field_written_empty_is_dropped(field, empty) -> None:
    validated = StoredUnit.model_validate(_record(**{field: empty}))

    assert validated.id == UNIT_ID
    assert field not in validated.model_dump()


@pytest.mark.parametrize("valued", ["abc", ["x"], {"k": 1}, True, 3, 0, 0.0])
def test_a_valued_unknown_key_is_refused_with_its_cause(valued) -> None:
    with pytest.raises(ValidationError) as refused:
        StoredUnit.model_validate(_record(from_newer_release=valued))

    message = str(refused.value)
    assert "newer release" in message
    assert UNIT_ID in message
    assert "from_newer_release" in message
    assert str(valued) in message


@pytest.mark.parametrize(
    "field", ["review_rounds", "deferred", "pending_replies", "person_comments"]
)
def test_a_valued_old_engine_field_is_refused_with_todays_wording(field) -> None:
    with pytest.raises(ValidationError) as refused:
        StoredUnit.model_validate(_record(**{field: ["work"]}))

    message = str(refused.value)
    assert f"{UNIT_ID}: the units store holds `{field}`, a field of the previous engine" in message
    assert "finish or requeue that unit's work with the release that wrote it" in message


def test_a_valued_written_empty_field_is_refused_as_old_work() -> None:
    with pytest.raises(ValidationError, match="a field of the previous engine"):
        StoredUnit.model_validate(_record(resume_from="abc123"))


def test_the_dict_it_is_handed_is_not_changed() -> None:
    record = _record(from_newer_release=None, resume_from="", classic_run={})
    before = copy.deepcopy(record)

    StoredUnit.model_validate(record)

    assert record == before


def test_the_dict_is_not_changed_when_the_record_is_refused() -> None:
    record = _record(from_newer_release=None, other="value")
    before = copy.deepcopy(record)

    with pytest.raises(ValidationError):
        StoredUnit.model_validate(record)

    assert record == before


def test_a_wrong_type_on_a_known_field_still_fails() -> None:
    with pytest.raises(ValidationError) as refused:
        StoredUnit.model_validate(_record(from_newer_release=None, check_reruns="many"))

    assert "check_reruns" in str(refused.value)
    assert "newer release" not in str(refused.value)


def test_a_misspelled_known_field_is_refused() -> None:
    with pytest.raises(ValidationError, match="chek_reruns"):
        StoredUnit.model_validate(_record(chek_reruns=2))


def test_unit_still_forbids_an_unknown_key() -> None:
    unit = app_unit(UNIT_ID)

    with pytest.raises(ValidationError, match="extra_forbidden"):
        type(unit).model_validate({**unit.model_dump(), "from_newer_release": None})


def test_every_other_frozen_model_forbids_an_unknown_key() -> None:
    class Plain(Frozen):
        name: str

    with pytest.raises(ValidationError, match="extra_forbidden"):
        Plain.model_validate({"name": "x", "from_newer_release": None})
    with pytest.raises(ValidationError, match="extra_forbidden"):
        ToolPolicy.model_validate({"from_newer_release": None})
