"""A failure that is on the base too belongs to an e2e-test split, and the open-fix gate holds
only a run that would execute that split (spec: e2e-failures)."""

from __future__ import annotations

import json
from pathlib import Path

from agent_build_kit.pipeline.untouched_failures import preexisting_record
from agent_build_kit.pipeline.wiring import build_on_e2e_gate, build_on_preexisting
from tests.e2e_gate_fakes import Planning
from tests.e2e_wait_fakes import OLD, verdict_of
from tests.factories import stored_unit
from tests.untouched_failure_fakes import failing

ACP = "acp"
REST_RUN = ("rest",)
CLAUDE_ONLY = ("claude_code",)
ACP_ONLY = (ACP,)
FULL_RUN = ("rest", "claude_code", "acp")
WITHOUT_ACP = ("rest", "claude_code")


def gate_for(planning: Planning, splits: tuple[str, ...], unit: str = "add-marker/1") -> list[str]:
    """What the gate answers for `unit` about to run the splits `splits`."""
    gate = build_on_e2e_gate(planning.store, planning.installation, log=lambda m: None)
    return gate(planning.store.get(unit), splits=splits)


# --- the entry carries the split -------------------------------------------------------


def test_an_entry_recorded_for_a_failure_of_acp_carries_acp(tmp_path: Path) -> None:
    planning = Planning(tmp_path)
    planning.open_fix(OLD, split=ACP)

    (entry,) = preexisting_record(planning.installation).entries()

    assert entry.split == ACP


def written_as(planning: Planning, **keys: str) -> list[str]:
    """The record holds one entry as an older version wrote it: `keys` replace the split."""
    record = preexisting_record(planning.installation)
    written = json.loads(failing().model_dump_json())
    for key in ("split", "runtime"):
        written.pop(key, None)
    record.path.parent.mkdir(parents=True, exist_ok=True)
    record.path.write_text(json.dumps({**written, **keys}) + "\n", encoding="utf-8")
    return [entry.split for entry in record.entries()]


def test_an_entry_written_with_the_older_runtime_key_reads_as_split(tmp_path: Path) -> None:
    assert written_as(Planning(tmp_path), runtime=ACP) == [ACP]


def test_the_older_value_base_reads_as_rest(tmp_path: Path) -> None:
    assert written_as(Planning(tmp_path), runtime="base") == ["rest"]


def test_an_entry_recorded_before_the_runtime_existed_reads_as_rest(tmp_path: Path) -> None:
    assert written_as(Planning(tmp_path)) == ["rest"]


def test_the_fix_change_names_the_split_in_its_proposal(tmp_path: Path) -> None:
    planning = Planning(tmp_path)
    fix = planning.open_fix(OLD, split=ACP)

    proposal = (planning.installation.changes_dir / fix / "proposal.md").read_text()

    assert "`acp` split" in proposal


def test_two_failures_of_one_test_in_two_splits_are_two_entries(tmp_path: Path) -> None:
    planning = Planning(tmp_path)
    planning.open_fix(OLD, split=ACP)
    unit = planning.store.get("feature/1")
    verdict = verdict_of(old=(OLD,), group="claude_code")

    build_on_preexisting(planning.store, planning.installation, log=lambda m: None)(
        unit, verdict, verdict.pre_existing[0], wait=False
    )

    entries = preexisting_record(planning.installation).entries()
    assert [(e.test, e.split) for e in entries] == [(OLD, ACP), (OLD, "claude_code")]


# --- the gate holds only runs that execute the entry's split ---------------------------


def test_a_rest_entry_holds_a_full_run(tmp_path: Path) -> None:
    planning = Planning(tmp_path)
    fix = planning.open_fix(OLD, split="rest")

    assert gate_for(planning, FULL_RUN) == [fix]


def test_an_acp_entry_holds_a_run_that_executes_acp(tmp_path: Path) -> None:
    planning = Planning(tmp_path)
    fix = planning.open_fix(OLD, split=ACP)

    assert gate_for(planning, FULL_RUN) == [fix]


def test_an_acp_entry_does_not_hold_a_run_of_claude_code_alone(tmp_path: Path) -> None:
    planning = Planning(tmp_path)
    planning.open_fix(OLD, split=ACP)

    assert gate_for(planning, CLAUDE_ONLY) == []
    assert planning.needs() == {}, "no Needs line either"


def test_an_acp_entry_does_not_hold_a_run_that_left_acp_out(tmp_path: Path) -> None:
    planning = Planning(tmp_path)
    planning.open_fix(OLD, split=ACP)

    assert gate_for(planning, WITHOUT_ACP) == []


def test_a_rest_entry_holds_a_run_of_rest_alone(tmp_path: Path) -> None:
    planning = Planning(tmp_path)
    fix = planning.open_fix(OLD, split="rest")

    assert gate_for(planning, REST_RUN) == [fix]


def test_a_rest_entry_does_not_hold_a_run_of_another_split_alone(tmp_path: Path) -> None:
    planning = Planning(tmp_path)
    planning.open_fix(OLD, split="rest")

    assert gate_for(planning, ACP_ONLY) == []


def test_an_entry_of_another_repo_holds_nothing(tmp_path: Path) -> None:
    planning = Planning(tmp_path)
    planning.open_fix(OLD, repo="platform", split=ACP)

    assert gate_for(planning, FULL_RUN) == []


def test_the_fix_changes_own_unit_is_not_held(tmp_path: Path) -> None:
    planning = Planning(tmp_path)
    fix = planning.open_fix(OLD, split=ACP)

    assert gate_for(planning, FULL_RUN, unit=f"{fix}/1") == []


def test_a_unit_already_waiting_on_the_fix_is_not_held_again(tmp_path: Path) -> None:
    planning = Planning(tmp_path)
    fix = planning.open_fix(OLD, split=ACP)
    assert gate_for(planning, FULL_RUN) == [fix]

    assert gate_for(planning, FULL_RUN) == []


def test_another_unit_of_the_repo_is_held_by_the_fix(tmp_path: Path) -> None:
    planning = Planning(tmp_path)
    fix = planning.open_fix(OLD, split=ACP)
    planning.store.upsert([stored_unit("other/1", change="add-marker", repo="app", groups=(1,))])

    assert gate_for(planning, FULL_RUN, unit="other/1") == [fix]
