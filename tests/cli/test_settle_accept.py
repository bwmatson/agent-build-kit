"""`abk settle <unit> --accept` ends the wait of a unit whose check will never finish (spec:
merged-waits-for-ci): a settling unit becomes merged with a note, any other unit is refused."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.cli import main
from agent_build_kit.config import dump
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import IN_REVIEW, MERGED, SETTLING, UnitState
from tests.conftest import make_installation
from tests.factories import stored_unit


@pytest.fixture
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> UnitStore:
    inst = make_installation(tmp_path / "planning")
    (inst.root / "abk.yaml").write_text(dump(inst.config))
    monkeypatch.chdir(inst.root)
    store = UnitStore(inst.state_dir / "units.json")
    store.upsert([stored_unit("add-marker/1")])
    return store


def test_accept_makes_a_settling_unit_merged_with_the_persons_reason_in_its_note(
    store: UnitStore,
) -> None:
    store.set_state("add-marker/1", SETTLING, pr=4, branch="spec/add-marker/1")

    code = main(["settle", "add-marker/1", "--accept", "--reason", "the runner was retired"])

    assert code == 0
    unit = store.get("add-marker/1")
    assert unit.state == MERGED
    assert "the runner was retired" in unit.history[-1]["note"]


@pytest.mark.parametrize("state", [IN_REVIEW, MERGED])
def test_accept_refuses_a_unit_that_is_not_settling(
    store: UnitStore, capsys: pytest.CaptureFixture[str], state: UnitState
) -> None:
    store.set_state("add-marker/1", state, pr=4, branch="spec/add-marker/1")

    code = main(["settle", "add-marker/1", "--accept"])

    assert code != 0
    assert store.get("add-marker/1").state == state
    assert "not settling" in capsys.readouterr().err
