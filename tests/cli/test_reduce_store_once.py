"""The first round after the change reduces every stored unit's dependencies, once.

A store written before dependencies were reduced holds lists whose entries another entry
reaches. The round that starts a tick rewrites each through `set_dependencies` and logs what it
removed; a second round finds nothing to do, and no other part of any record changes.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import MERGED, RUNNING
from tests.tick_pass import isolate, stored, workspace

pytestmark = pytest.mark.usefixtures("scripted_engine")

ROOTS = ("x/1", "x/2", "x/3")
REDUCED = {"u/1": ("x/4",), "s/1": ("x/4",), "m/1": ("x/4",), "r/1": ("x/4",)}


@pytest.fixture(autouse=True)
def isolated(monkeypatch: pytest.MonkeyPatch) -> None:
    isolate(monkeypatch)


@pytest.fixture
def inst(tmp_path: Path) -> Installation:
    return workspace(tmp_path)


@pytest.fixture
def store(inst: Installation) -> UnitStore:
    """The units of a store from before reduction: `u/1` lists four dependencies, three of them
    reached by the fourth; `s/1` has started and lists one that `x/4` reaches; `m/1` merged
    listing the same; `r/1` is planned and waiting only on merged units; `n/1` lists nothing."""
    store = UnitStore(inst.state_dir / "units.json")
    store.import_units(
        [
            *(stored(uid) for uid in ROOTS),
            stored("x/4", depends_on=ROOTS),
            stored("u/1", depends_on=(*ROOTS, "x/4")),
            stored("s/1", depends_on=("x/1", "x/4")),
            stored("m/1", depends_on=("x/2", "x/4")),
            stored("r/1", depends_on=("x/3", "x/4")),
            stored("n/1"),
        ]
    )
    for uid in (*ROOTS, "x/4", "m/1"):
        store.set_state(uid, MERGED)
    store.set_state("s/1", RUNNING, branch="spec/s/1")
    return store


def round_of(inst: Installation, store: UnitStore):
    return cli.run_round(
        inst, store, building={"s/1"}, started=set(), only=frozenset(), submit=True
    )


def records(store: UnitStore) -> dict[str, dict]:
    return {unit.id: unit.model_dump() for unit in store.all()}


def without_dependencies(found: dict[str, dict]) -> dict[str, dict]:
    return {
        uid: {k: v for k, v in record.items() if k != "depends_on"} for uid, record in found.items()
    }


def recording_writes(store: UnitStore, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """The name of each store method that changed the file, in order."""
    writers: list[str] = []
    for name in dir(UnitStore):
        original = getattr(store, name)
        if name.startswith("_") or not callable(original):
            continue

        def watched(*args, _name=name, _original=original, **kwargs):
            before = store.path.read_bytes()
            result = _original(*args, **kwargs)
            if store.path.read_bytes() != before:
                writers.append(_name)
            return result

        monkeypatch.setattr(store, name, watched)
    return writers


def reduced_lines(out: str) -> dict[str, str]:
    """Each unit a `<unit>: dependencies reduced: <removed>` line names, with what it removed."""
    found = [re.search(r"(\S+): dependencies reduced: (.*)", line) for line in out.splitlines()]
    return {match.group(1): match.group(2) for match in found if match}


def test_each_redundant_list_is_stored_reduced_once_and_logged(
    inst: Installation,
    store: UnitStore,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    before = records(store)

    round_of(inst, store)

    after = records(store)
    assert {uid: unit["depends_on"] for uid, unit in after.items() if uid in REDUCED} == REDUCED
    assert after["n/1"]["depends_on"] == ()
    assert after["x/4"]["depends_on"] == ROOTS
    assert without_dependencies(after) == without_dependencies(before)
    removed = reduced_lines(capsys.readouterr().out)
    assert set(removed) == set(REDUCED)
    assert all(root in removed["u/1"] for root in ROOTS)
    assert "x/4" not in removed["u/1"]

    # A second round has nothing to reduce: no write, no line.
    writes = recording_writes(store, monkeypatch)
    round_of(inst, store)
    assert writes == []
    assert not reduced_lines(capsys.readouterr().out)
    assert records(store) == after


def test_the_file_is_written_only_by_set_dependencies_and_before_a_unit_is_judged_ready(
    inst: Installation, store: UnitStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    writes = recording_writes(store, monkeypatch)

    ready = round_of(inst, store)

    assert writes == ["set_dependencies"] * len(REDUCED)
    # The unit the round hands out for a build carries the list it was stored with by then.
    assert {unit.id: unit.depends_on for unit in ready}["r/1"] == ("x/4",)

    # A store that cannot be read stops the round, as it does without the step.
    store.path.write_text("{ not json")
    with pytest.raises(ValueError):
        round_of(inst, store)
