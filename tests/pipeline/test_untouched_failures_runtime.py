"""A failure that is on the base too belongs to a runtime group, and the open-fix gate holds
only a run that would execute that group (spec: tier2-failures)."""

from __future__ import annotations

import json
from pathlib import Path

from agent_build_kit.pipeline.untouched_failures import preexisting_record
from agent_build_kit.pipeline.wiring import build_on_preexisting, build_on_tier2_gate
from tests.factories import stored_unit
from tests.tier2_gate_fakes import Planning
from tests.tier2_wait_fakes import OLD, verdict_of
from tests.untouched_failure_fakes import failing

ACP = "acp"
BASE_RUN = ("base",)
CLAUDE_ONLY = ("claude_code",)
FULL_RUN = ("base", "claude_code", "acp")
WITHOUT_ACP = ("base", "claude_code")


def gate_for(
    planning: Planning, runtimes: tuple[str, ...], unit: str = "add-marker/1"
) -> list[str]:
    """What the gate answers for `unit` about to run the groups `runtimes`."""
    gate = build_on_tier2_gate(planning.store, planning.installation, log=lambda m: None)
    return gate(planning.store.get(unit), runtimes=runtimes)


# --- the entry carries the runtime -------------------------------------------------------


def test_an_entry_recorded_for_a_failure_of_acp_carries_acp(tmp_path: Path) -> None:
    planning = Planning(tmp_path)
    planning.open_fix(OLD, group=ACP)

    (entry,) = preexisting_record(planning.installation).entries()

    assert entry.runtime == ACP


def test_an_entry_recorded_before_the_runtime_existed_reads_as_base(tmp_path: Path) -> None:
    planning = Planning(tmp_path)
    record = preexisting_record(planning.installation)
    written = json.loads(failing().model_dump_json())
    written.pop("runtime", None)
    record.path.parent.mkdir(parents=True, exist_ok=True)
    record.path.write_text(json.dumps(written) + "\n", encoding="utf-8")

    (entry,) = record.entries()

    assert entry.runtime == "base"


def test_the_fix_change_names_the_runtime_in_its_proposal(tmp_path: Path) -> None:
    planning = Planning(tmp_path)
    fix = planning.open_fix(OLD, group=ACP)

    proposal = (planning.installation.changes_dir / fix / "proposal.md").read_text()

    assert "acp" in proposal.lower()


def test_two_failures_of_one_test_in_two_runtimes_are_two_entries(tmp_path: Path) -> None:
    planning = Planning(tmp_path)
    planning.open_fix(OLD, group=ACP)
    unit = planning.store.get("feature/1")
    verdict = verdict_of(old=(OLD,), group="claude_code")

    build_on_preexisting(planning.store, planning.installation, log=lambda m: None)(
        unit, verdict, verdict.pre_existing[0], wait=False
    )

    entries = preexisting_record(planning.installation).entries()
    assert [(e.test, e.runtime) for e in entries] == [(OLD, ACP), (OLD, "claude_code")]


# --- the gate holds only runs that execute the entry's runtime ---------------------------


def test_a_base_entry_holds_a_full_run(tmp_path: Path) -> None:
    planning = Planning(tmp_path)
    fix = planning.open_fix(OLD, group="base")

    assert gate_for(planning, FULL_RUN) == [fix]


def test_an_acp_entry_holds_a_run_that_executes_acp(tmp_path: Path) -> None:
    planning = Planning(tmp_path)
    fix = planning.open_fix(OLD, group=ACP)

    assert gate_for(planning, FULL_RUN) == [fix]


def test_an_acp_entry_does_not_hold_a_run_of_claude_code_alone(tmp_path: Path) -> None:
    planning = Planning(tmp_path)
    planning.open_fix(OLD, group=ACP)

    assert gate_for(planning, CLAUDE_ONLY) == []
    assert planning.needs() == {}, "no Needs line either"


def test_an_acp_entry_does_not_hold_a_run_that_left_acp_out(tmp_path: Path) -> None:
    planning = Planning(tmp_path)
    planning.open_fix(OLD, group=ACP)

    assert gate_for(planning, WITHOUT_ACP) == []


def test_a_base_entry_holds_a_run_of_the_base_group_alone(tmp_path: Path) -> None:
    planning = Planning(tmp_path)
    fix = planning.open_fix(OLD, group="base")

    assert gate_for(planning, BASE_RUN) == [fix]


def test_an_entry_of_another_repo_holds_nothing(tmp_path: Path) -> None:
    planning = Planning(tmp_path)
    planning.open_fix(OLD, repo="platform", group=ACP)

    assert gate_for(planning, FULL_RUN) == []


def test_the_fix_changes_own_unit_is_not_held(tmp_path: Path) -> None:
    planning = Planning(tmp_path)
    fix = planning.open_fix(OLD, group=ACP)

    assert gate_for(planning, FULL_RUN, unit=f"{fix}/1") == []


def test_a_unit_already_waiting_on_the_fix_is_not_held_again(tmp_path: Path) -> None:
    planning = Planning(tmp_path)
    fix = planning.open_fix(OLD, group=ACP)
    assert gate_for(planning, FULL_RUN) == [fix]

    assert gate_for(planning, FULL_RUN) == []


def test_another_unit_of_the_repo_is_held_by_the_fix(tmp_path: Path) -> None:
    planning = Planning(tmp_path)
    fix = planning.open_fix(OLD, group=ACP)
    planning.store.upsert([stored_unit("other/1", change="add-marker", repo="app", groups=(1,))])

    assert gate_for(planning, FULL_RUN, unit="other/1") == [fix]
