"""`on_flake` with `wait` false records a flake and ensures its one fix change, and leaves the
unit without a `Needs:` line; with `wait` true it behaves as it always has (spec:
a-moved-base-is-checked-by-what-it-can-affect).
"""

from __future__ import annotations

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.flakes import flake_change_name, flake_record
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.wiring import build_on_flake
from tests.pipeline.test_flake_fix_change import (
    TEST,
    change_with_unit,
    changes,
    code_repo,
    flaked,
    waits_on,
)


def on_flake_of(installation: Installation, *names: str, logged: list[str] | None = None):
    """The recorder over one unit per name, each of a change of its own, logging to `logged`;
    returns it and the units."""
    units = [change_with_unit(installation, name, f"{name}/1") for name in names]
    store = UnitStore(installation.root / "units.json")
    store.upsert(units)
    sink = logged.append if logged is not None else (lambda message: None)
    return build_on_flake(store, installation, log=sink), units


def test_the_log_says_a_unit_that_does_not_wait_did_not_and_one_that_waits_did(
    installation: Installation,
) -> None:
    code_repo(installation)
    logged: list[str] = []
    on_flake, (going, waiting) = on_flake_of(installation, "feature", "other", logged=logged)

    fix = on_flake(going, flaked(unit=going.id), wait=False)
    on_flake(waiting, flaked(unit=waiting.id), wait=True)

    # The fixture's checkout is no git repository, so the agent step says it has no worktree.
    waits = [line for line in logged if not line.startswith("no worktree")]
    assert waits == [
        f"feature/1: flaky test {TEST} — recorded as {fix}, no wait",
        f"other/1: flaky test {TEST} — waits for {fix}",
    ]


def test_a_flake_that_does_not_wait_is_recorded_with_its_fix_change_and_no_needs_line(
    installation: Installation,
) -> None:
    code_repo(installation)
    on_flake, (unit,) = on_flake_of(installation, "feature")

    fix = on_flake(unit, flaked(), wait=False)

    assert fix == flake_change_name(TEST)
    assert fix in changes(installation), "the one fix change is written"
    assert waits_on(installation, "feature") == []
    (recorded,) = flake_record(installation).entries()
    assert (recorded.test, recorded.unit, recorded.change) == (TEST, "feature/1", fix)


def test_two_units_meeting_the_flake_without_waiting_make_one_change(
    installation: Installation,
) -> None:
    code_repo(installation)
    on_flake, (first, second) = on_flake_of(installation, "feature", "other")

    named = [
        on_flake(first, flaked(unit=first.id), wait=False),
        on_flake(second, flaked(unit=second.id), wait=False),
    ]

    fix = flake_change_name(TEST)
    assert named == [fix, fix]
    assert changes(installation) == {"feature", "other", fix}
    assert waits_on(installation, "feature") == [] and waits_on(installation, "other") == []
    assert len(flake_record(installation).entries()) == 2


def test_a_unit_that_waits_beside_one_that_does_not_is_the_only_one_with_a_needs_line(
    installation: Installation,
) -> None:
    code_repo(installation)
    on_flake, (waiting, going) = on_flake_of(installation, "feature", "other")

    fix = on_flake(waiting, flaked(unit=waiting.id), wait=True)
    on_flake(going, flaked(unit=going.id), wait=False)

    assert waits_on(installation, "feature") == [fix]
    assert waits_on(installation, "other") == []
