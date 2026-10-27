"""`abk external hand-off`, `list`, `done` and `release` (spec: external-work).

The commands run through the real command line over a fixture change and a store of units.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_build_kit.cli import main
from agent_build_kit.config import dump
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.external_file import DONE, HELD, RELEASED, read_holds, record_done
from agent_build_kit.pipeline.unit_store import StoredUnit, UnitStore
from agent_build_kit.pipeline.units import MERGED, PLANNED
from tests.conftest import make_installation, run_status
from tests.external_support import SINCE, change_in
from tests.factories import stored_unit
from tests.forges.stand_in import StandInForge

COMMIT = "c" * 40
MERGED_PR = 5
LINK = "https://boards.example/items/42"


class World:
    """An installation on disk with the change `feature` (three groups) and a unit store."""

    def __init__(self, tmp_path: Path) -> None:
        self.inst = make_installation(tmp_path / "planning", planning=dict(state_dir="."))
        self.config = self.inst.root / "abk.yaml"
        self.config.write_text(dump(self.inst.config))
        self.folder = change_in(self.inst.changes_dir)
        self.store = self.inst.state_dir / "units.json"

    def units(self, *units: StoredUnit) -> UnitStore:
        store = UnitStore(self.store)
        store.upsert(list(units))
        return store

    def run(self, capsys: pytest.CaptureFixture[str], *argv: str, code: int = 0) -> tuple[str, str]:
        capsys.readouterr()
        assert main(["--config", str(self.config), "external", *argv]) == code
        out = capsys.readouterr()
        return out.out, out.err

    def hand_off(self, capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[str, str]:
        return self.run(
            capsys, "hand-off", "feature", "--holder", "Sam Example", "--link", LINK, *argv
        )


@pytest.fixture
def world(tmp_path: Path) -> World:
    return World(tmp_path)


def test_hand_off_records_a_hold_on_named_groups(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    world.hand_off(
        capsys, "--groups", "2", "3", "--item", "story=88", "--note", "Sam takes the API half"
    )

    [recorded] = read_holds(world.folder)
    assert recorded.scope == (2, 3)
    assert (recorded.holder, recorded.link, recorded.status) == ("Sam Example", LINK, HELD)
    assert recorded.items == {"story": "88"}
    assert recorded.note == "Sam takes the API half"


def test_hand_off_all_works_before_the_change_has_a_spec(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    (world.folder / "tasks.md").unlink()

    world.hand_off(capsys, "--all")

    assert [h.scope for h in read_holds(world.folder)] == ["all"]


def test_repeating_a_hand_off_by_the_same_holder_changes_nothing_and_says_so(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    world.hand_off(capsys, "--groups", "2")
    before = (world.folder / "external.yaml").read_text()

    out, _err = world.hand_off(capsys, "--groups", "2")

    assert "already held" in out
    assert (world.folder / "external.yaml").read_text() == before


@pytest.mark.parametrize("repeat", [("3", "2"), ("2",), ("2", "2", "3")])
def test_a_repeat_in_another_order_or_of_part_of_what_is_held_changes_nothing(
    world: World, capsys: pytest.CaptureFixture[str], repeat: tuple[str, ...]
) -> None:
    world.hand_off(capsys, "--groups", "2", "3")
    before = (world.folder / "external.yaml").read_text()

    out, _err = world.hand_off(capsys, "--groups", *repeat, "--json")

    assert json.loads(out)["already_held"] is True
    assert (world.folder / "external.yaml").read_text() == before


def test_a_hand_off_of_part_of_an_all_hold_by_the_same_holder_changes_nothing(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    world.hand_off(capsys, "--all")

    out, _err = world.hand_off(capsys, "--groups", "2", "--json")

    assert json.loads(out)["already_held"] is True
    assert len(read_holds(world.folder)) == 1


def test_a_hand_off_to_a_change_that_does_not_exist_is_refused_and_creates_nothing(
    world: World, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    _out, err = world.run(
        capsys,
        "hand-off",
        "featur",
        "--all",
        "--holder",
        "Sam Example",
        "--link",
        LINK,
        code=1,
    )

    assert "featur" in err
    assert not (world.inst.changes_dir / "featur").exists()


def test_a_refusal_under_json_prints_the_reason_on_stdout(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    out, _err = world.run(capsys, "release", "feature", "--groups", "1", "--json", code=1)

    assert "not held" in json.loads(out)["refused"]


def test_a_hand_off_another_holder_already_has_is_refused(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    world.hand_off(capsys, "--groups", "2")

    _out, err = world.run(
        capsys,
        "hand-off",
        "feature",
        "--groups",
        "2",
        "--holder",
        "Alex Example",
        "--link",
        LINK,
        code=1,
    )

    assert "group 2" in err and "Sam Example" in err
    assert len(read_holds(world.folder)) == 1


def test_hand_off_of_started_work_is_refused_with_guidance(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    store = world.units(stored_unit("feature/1", change="feature", groups=(1,)))
    store.set_state("feature/1", PLANNED, branch="spec/feature/1")

    _out, err = world.run(
        capsys,
        "hand-off",
        "feature",
        "--groups",
        "1",
        "--holder",
        "Sam Example",
        "--link",
        LINK,
        code=1,
    )

    assert "feature/1" in err and "retire" in err
    assert read_holds(world.folder) == ()


def test_list_shows_each_hold_with_its_facts_and_the_units_waiting_on_it(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    world.units(
        stored_unit("feature/1", change="feature", groups=(1,)),
        stored_unit("feature/2", change="feature", groups=(2,), depends_on=("feature/1",)),
    )
    world.hand_off(capsys, "--groups", "1")

    out, _err = world.run(capsys, "list")

    for expected in ("feature groups 1:", "Sam Example", LINK, HELD, "feature/2"):
        assert expected in out, out
    assert "feature/1" in out


def test_list_with_no_holds_says_so(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    out, _err = world.run(capsys, "list")

    assert "no holds" in out.lower()


def test_list_json_carries_the_same_facts(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    world.units(
        stored_unit("feature/1", change="feature", groups=(1,)),
        stored_unit("feature/2", change="feature", groups=(2,), depends_on=("feature/1",)),
    )
    world.hand_off(capsys, "--groups", "1", "--item", "story=88")

    out, _err = world.run(capsys, "list", "--json")

    [row] = json.loads(out)["holds"]
    assert row["change"] == "feature"
    assert row["groups"] == [1]
    assert (row["holder"], row["link"], row["status"]) == ("Sam Example", LINK, HELD)
    assert row["items"] == {"story": "88"}
    assert row["age"]
    assert row["waiting"] == ["feature/2"]


def test_every_command_has_a_json_form(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    store = world.units(stored_unit("feature/1", change="feature", groups=(1,)))

    out, _err = world.hand_off(capsys, "--groups", "1", "--json")
    handed = json.loads(out)
    again, _err = world.hand_off(capsys, "--groups", "1", "--json")
    repeated = json.loads(again)
    released, _err = world.run(capsys, "release", "feature", "--groups", "1", "--json")

    assert handed["change"] == "feature" and handed["groups"] == [1]
    assert repeated["already_held"] is True
    assert json.loads(released)["groups"] == [1]
    assert store.get("feature/1").state == PLANNED


def test_releasing_every_group_of_one_hold_succeeds_in_one_step(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    world.hand_off(capsys, "--groups", "2", "3")

    world.run(capsys, "release", "feature", "--groups", "2", "3")

    assert [h.status for h in read_holds(world.folder)] == [RELEASED]


def test_releasing_one_group_names_every_group_its_hold_covered(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    world.hand_off(capsys, "--groups", "2", "3")

    out, _err = world.run(capsys, "release", "feature", "--groups", "2", "--json")

    assert json.loads(out)["groups"] == [2, 3]


def test_a_release_naming_a_group_nobody_held_is_refused_and_writes_nothing(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    world.hand_off(capsys, "--groups", "2")

    _out, err = world.run(capsys, "release", "feature", "--groups", "2", "1", code=1)

    assert "group 1" in err
    assert [h.status for h in read_holds(world.folder)] == [HELD]


def test_release_gives_the_work_back_and_a_done_hold_cannot_be_released(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    world.hand_off(capsys, "--groups", "1")

    world.run(capsys, "release", "feature", "--groups", "1")
    assert [h.status for h in read_holds(world.folder)] == [RELEASED]

    world.hand_off(capsys, "--groups", "2")
    record_done(world.folder, (2,), merged_by="5", at=SINCE)

    _out, err = world.run(capsys, "release", "feature", "--groups", "2", code=1)

    assert "done" in err


def forge_with_merged_pr(monkeypatch: pytest.MonkeyPatch) -> StandInForge:
    forge = StandInForge()
    forge.merged[MERGED_PR] = COMMIT
    monkeypatch.setattr(
        Installation, "forge_of", lambda self, repo: (forge, forge.repo_id()), raising=True
    )
    return forge


def test_done_records_a_verified_hand_merge(
    world: World, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    store = world.units(stored_unit("feature/1", change="feature", groups=(1,)))
    world.hand_off(capsys, "--groups", "1")
    forge_with_merged_pr(monkeypatch)

    world.run(capsys, "done", "feature", "--groups", "1", "--pr", str(MERGED_PR))

    assert store.get("feature/1").state == MERGED
    assert store.get("feature/1").merge_sha == COMMIT
    assert [h.status for h in read_holds(world.folder)] == [DONE]


def test_done_refuses_a_pull_request_that_is_not_merged(
    world: World, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    store = world.units(stored_unit("feature/1", change="feature", groups=(1,)))
    world.hand_off(capsys, "--groups", "1")
    forge_with_merged_pr(monkeypatch)

    _out, err = world.run(capsys, "done", "feature", "--groups", "1", "--pr", "6", code=1)

    assert "not merged" in err
    assert store.get("feature/1").state == PLANNED


def test_done_json_names_the_commit(
    world: World, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    world.units(stored_unit("feature/1", change="feature", groups=(1,)))
    world.hand_off(capsys, "--groups", "1")
    forge_with_merged_pr(monkeypatch)

    out, _err = world.run(
        capsys, "done", "feature", "--groups", "1", "--pr", str(MERGED_PR), "--json"
    )

    result = json.loads(out)
    assert result["change"] == "feature" and result["groups"] == [1]
    assert result["merged_by"] == str(MERGED_PR)


def test_status_has_a_section_for_holds(
    world: World, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    world.units(stored_unit("feature/1", change="feature", groups=(1,)))
    world.hand_off(capsys, "--groups", "1")
    lines = run_status(world.inst, monkeypatch, capsys)

    heading = next(i for i, line in enumerate(lines) if "external holds" in line.lower())
    section = "\n".join(lines[heading : heading + 4])
    assert "feature" in section and "Sam Example" in section and LINK in section


def test_status_has_no_holds_section_when_nothing_is_held(
    world: World, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    world.units(stored_unit("feature/1", change="feature", groups=(1,)))
    lines = run_status(world.inst, monkeypatch, capsys)

    assert not any("external holds" in line.lower() for line in lines)
