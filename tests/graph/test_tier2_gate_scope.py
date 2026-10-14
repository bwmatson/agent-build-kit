"""Only a run that executes the whole marker is held by an open fix; the node learns which run
it is making from the scope function and reads no setting itself
(spec: tier2-waits-on-open-base-failure-fixes)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_build_kit.pipeline.stack_runner import RunStatus
from tests.tier2_gate_fakes import Planning


def test_an_own_scope_run_of_a_unit_with_a_test_of_its_own_is_not_held_and_reads_no_record(
    tmp_path: Path,
) -> None:
    planning = Planning(tmp_path, whole=False)
    planning.open_fix()

    outcome = planning.tick()

    assert len(planning.scope.asked) == 1, "the node asked the scope function"
    assert planning.gate.asked == [], "the record was not read"
    assert outcome.status != RunStatus.HELD and planning.ran_tier2, "it ran its own tests"
    assert planning.needs() == {}


def test_an_own_scope_unit_with_no_tier_2_test_is_not_held_and_takes_no_lock(
    tmp_path: Path,
) -> None:
    planning = Planning(tmp_path, whole=False)
    planning.open_fix()
    asked: list[str] = []

    def skipped(*, cwd: Path, base: str | None = None) -> tuple[bool, str]:
        asked.append("run")
        return True, "tier 2 skipped: no tier 2 test added or changed"

    outcome = planning.tick(run_tier2=skipped)

    assert len(planning.scope.asked) == 1
    assert planning.gate.asked == []
    assert outcome.status != RunStatus.HELD and asked == ["run"]
    assert planning.needs() == {}


def test_a_full_scope_run_is_held_however_the_scope_function_came_to_say_so(
    tmp_path: Path,
) -> None:
    # `full` by the repo's setting, by its dev stack script and by a profile that cannot
    # select tests all reach the node as the one answer of the scope function.
    planning = Planning(tmp_path, whole=True)
    fix = planning.open_fix()

    outcome = planning.tick()

    assert len(planning.scope.asked) == 1
    assert outcome.status == RunStatus.HELD
    assert planning.needs() == {1: [fix], 2: [fix]}
    assert not planning.ran_tier2


def test_the_scope_is_asked_for_the_tree_and_base_of_the_run_before_the_gate(
    tmp_path: Path,
) -> None:
    planning = Planning(tmp_path, whole=True)
    planning.open_fix()
    seen: list[int] = []

    def gate(unit: Any) -> list[str]:
        seen.append(len(planning.scope.asked))
        return planning.gate(unit)

    planning.tick(on_tier2_gate=gate, base="release")

    assert seen == [1], "the scope function was asked first, once"
    ((tree, base),) = planning.scope.asked
    assert tree == tmp_path / "tree"
    assert base == "release"
