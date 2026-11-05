"""A unit-test takes a slot before its clock starts and records the wait (spec:
unit-test-concurrency): with a limit set and every slot taken the run does not start its command,
says it waits and names a holder, starts when a slot is free, reports the wait in its ledger row
apart from its own time, shares one permit with the reruns inside it, and gives the permit back
however it ends."""

from __future__ import annotations

import contextvars
import json
import subprocess
import threading
from collections.abc import Collection, Iterator
from contextlib import ExitStack, contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest

from agent_build_kit import config as config_module
from agent_build_kit import profiles
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline import events, spans
from agent_build_kit.pipeline.flakes import FlakeFound
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.unit_test_slots import LATE_CHECK_NODE, unit_test_slot
from agent_build_kit.pipeline.units import IN_REVIEW, SETTLING
from agent_build_kit.pipeline.wiring import build_reproduce, build_unit_test
from agent_build_kit.profiles.base import ToolchainProfile
from tests.conftest import make_installation
from tests.factories import commit, init_repo, new_unit, stored_unit
from tests.failure_bundle_fakes import START, BundleMachine, BundleProfile
from tests.unit_test_slot_fakes import waiting_units
from tests.waiting import wait_for


def limited(limit: int | None) -> None:
    current = config_module.active()
    config_module.activate(
        current.model_copy(
            update={
                "global_limits": current.global_limits.model_copy(
                    update={"max_concurrent_unit_tests": limit}
                )
            }
        ),
        config_module.active_root(),
    )


@pytest.fixture
def installation(tmp_path: Path) -> Installation:
    return make_installation(tmp_path / "planning")


@contextmanager
def running(target) -> Iterator[threading.Thread]:
    """`target` running in a thread, in a copy of this test's context (where the unit the
    pipeline's step runs for is set), joined when the block ends."""
    thread = threading.Thread(target=contextvars.copy_context().run, args=(target,), daemon=True)
    thread.start()
    try:
        yield thread
    finally:
        thread.join(timeout=30)


def rows(ledger: Path) -> list[dict]:
    return [json.loads(line) for line in ledger.read_text().splitlines() if line.strip()]


def unit_test_of(
    scratch: Path,
    machine: BundleMachine,
    ledger: Path,
    installation: Installation,
    log: list[str],
    *,
    real_clock: bool = False,
):
    ticks = iter(START + timedelta(seconds=10 * n) for n in range(100))
    return build_unit_test(
        profile=cast(ToolchainProfile, BundleProfile()),
        run=machine,
        changed=lambda *a: ["tests/test_one.py"],
        failures_dir=ledger.parent / "bundles",
        test_runs=ledger,
        installation=installation,
        log=log.append,
        now=(lambda: datetime.now(UTC)) if real_clock else (lambda: next(ticks)),
        machine=lambda: {"load": [1.0, 1.0, 1.0]},
    )


def test_a_run_waits_for_a_slot_and_starts_its_command_only_when_one_is_free(
    scratch: Path, tmp_path: Path, installation: Installation
) -> None:
    limited(1)
    ledger, log = tmp_path / "test-runs.jsonl", []
    machine = BundleMachine(scratch, reruns=[], passing=True)
    outcome: list[tuple[bool, str]] = []
    holder = ExitStack()
    holder.enter_context(unit_test_slot(installation.locks_dir, 1, holder="other/1"))

    def run() -> None:
        outcome.append(
            unit_test_of(scratch, machine, ledger, installation, log)(cwd=scratch, base="main")
        )

    with running(run):
        wait_for(
            lambda: any("waiting for a unit-test slot" in line for line in log), what="the wait"
        )
        assert machine.commands == [], "no command starts while every slot is taken"
        assert any("other/1" in line for line in log), "the log names a holder"
        holder.close()

    assert outcome == [(True, outcome[0][1])]
    assert machine.commands, "the command ran once a slot was free"


def test_the_ledger_row_has_the_wait_apart_from_the_run_and_the_run_starts_after_the_wait(
    scratch: Path, tmp_path: Path, installation: Installation
) -> None:
    limited(1)
    ledger, log = tmp_path / "test-runs.jsonl", []
    holder = ExitStack()
    holder.enter_context(unit_test_slot(installation.locks_dir, 1, holder="other/1"))
    with running(
        lambda: unit_test_of(
            scratch,
            BundleMachine(scratch, reruns=[], passing=True),
            ledger,
            installation,
            log,
            real_clock=True,
        )(cwd=scratch, base="main")
    ):
        wait_for(lambda: any("waiting" in line for line in log), what="the wait")
        released = datetime.now(UTC)
        holder.close()

    (row,) = rows(ledger)
    assert row["wait_seconds"] > 0
    assert datetime.fromisoformat(row["started"]) >= released, "the clock starts after the permit"


def test_a_run_that_waited_for_nothing_has_zero_wait_in_its_row(
    scratch: Path, tmp_path: Path, installation: Installation
) -> None:
    limited(2)
    ledger = tmp_path / "test-runs.jsonl"

    unit_test_of(
        scratch, BundleMachine(scratch, reruns=[], passing=True), ledger, installation, []
    )(cwd=scratch, base="main")

    assert rows(ledger)[0]["wait_seconds"] == 0.0


def test_with_no_limit_nothing_waits_and_no_slot_file_is_made(
    scratch: Path, tmp_path: Path, installation: Installation
) -> None:
    limited(None)
    ledger = tmp_path / "test-runs.jsonl"

    unit_test_of(
        scratch, BundleMachine(scratch, reruns=[], passing=True), ledger, installation, []
    )(cwd=scratch, base="main")

    assert not installation.locks_dir.exists() or not list(
        installation.locks_dir.glob("unit-test-slot-*")
    )


def test_the_reruns_inside_one_unit_test_share_its_permit_and_the_slot_is_free_afterwards(
    scratch: Path, tmp_path: Path, installation: Installation
) -> None:
    limited(1)
    ledger = tmp_path / "test-runs.jsonl"
    machine = BundleMachine(scratch, reruns=[0, 0])  # the failed tests pass both serial reruns

    result: list[object] = []

    def run() -> None:
        try:
            unit_test_of(scratch, machine, ledger, installation, [])(cwd=scratch, base="main")
        except FlakeFound as found:
            result.append(found)

    with running(run) as thread:
        thread.join(timeout=30)
        assert not thread.is_alive(), "the reruns did not wait on their own run's slot"

    assert result, "the run found the flake"
    with unit_test_slot(installation.locks_dir, 1, holder="next/1") as waited:
        assert waited == 0.0, "the permit was given back when the run raised"


def test_the_permit_is_given_back_when_the_command_raises(
    scratch: Path, tmp_path: Path, installation: Installation
) -> None:
    limited(1)

    def broken(command, **kwargs):
        raise RuntimeError("the runner died")

    unit_test = build_unit_test(
        profile=cast(ToolchainProfile, BundleProfile()),
        run=broken,
        changed=lambda *a: ["tests/test_one.py"],
        test_runs=tmp_path / "test-runs.jsonl",
        installation=installation,
    )

    with pytest.raises(RuntimeError, match="runner died"):
        unit_test(cwd=scratch, base="main")

    with unit_test_slot(installation.locks_dir, 1, holder="next/1") as waited:
        assert waited == 0.0


TEST = "tests/test_widget.py::test_renders_the_label"


def test_the_reproduce_run_takes_a_slot_too(tmp_path: Path, installation: Installation) -> None:
    limited(1)
    tree = tmp_path / "tree"
    (tree / "tests").mkdir(parents=True)
    (tree / "tests" / "test_widget.py").write_text("def test_renders_the_label():\n    pass\n")
    (tree / "pyproject.toml").write_text(
        '[project]\nname = "app"\nversion = "0"\ndependencies = ["pytest-xdist"]\n'
    )
    commands: list[list[str]] = []
    log: list[str] = []

    def run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        commands.append(args)
        return subprocess.CompletedProcess(args, 0, "", "")

    reproduce = build_reproduce(
        profile=profiles.get("python-uv"), run=run, installation=installation, log=log.append
    )
    holder = ExitStack()
    holder.enter_context(unit_test_slot(installation.locks_dir, 1, holder="other/1"))
    found: list[object] = []
    with running(lambda: found.append(reproduce(cwd=tree, test=TEST, runs=1))):
        wait_for(
            lambda: any("waiting for a unit-test slot" in line for line in log), what="the wait"
        )
        assert commands == [], "no command starts while every slot is taken"
        holder.close()

    assert commands and found


def stored(installation: Installation, *units) -> None:
    UnitStore(installation.state_dir / "units.json").upsert(list(units))


def served_in_order(
    scratch: Path,
    tmp_path: Path,
    installation: Installation,
    waiters: list[str],
    late: Collection[str] = (),
) -> list[str]:
    """The ids of `waiters`' runs in the order they got the one slot, each run starting to wait
    only after the one before it is waiting, while another run holds the slot. The runs of the
    units in `late` are their late checks."""
    limited(1)
    ledger, served = tmp_path / "test-runs.jsonl", []
    holder = ExitStack()
    holder.enter_context(unit_test_slot(installation.locks_dir, 1, holder="other/1"))
    logs: dict[str, list[str]] = {uid: [] for uid in waiters}

    def run_of(uid: str):
        def run() -> None:
            node = LATE_CHECK_NODE if uid in late else "n1"
            spans.current_unit.set((uid, uid.split("/")[0], node, 1))
            unit_test_of(
                scratch,
                BundleMachine(scratch, reruns=[], passing=True),
                ledger,
                installation,
                logs[uid],
            )(cwd=scratch, base="main")
            served.append(uid)

        return run

    with ExitStack() as threads:
        for uid in waiters:
            threads.enter_context(running(run_of(uid)))
            wait_for(
                lambda uid=uid: any("waiting for a unit-test slot" in line for line in logs[uid]),
                what=f"{uid} waiting",
            )
        holder.close()
    return served


def test_a_more_urgent_unit_is_served_before_a_less_urgent_one_that_began_waiting_first(
    scratch: Path, tmp_path: Path, installation: Installation
) -> None:
    stored(installation, new_unit("slow/1", priority=4), new_unit("fast/1", priority=2))

    served = served_in_order(scratch, tmp_path, installation, ["slow/1", "fast/1"])

    assert served == ["fast/1", "slow/1"]


def test_a_unit_with_an_open_pull_request_is_served_before_a_new_unit_of_equal_priority(
    scratch: Path, tmp_path: Path, installation: Installation
) -> None:
    stored(installation, new_unit("fresh/1", priority=2), new_unit("review/1", priority=2))
    UnitStore(installation.state_dir / "units.json").set_state(
        "review/1", IN_REVIEW, pr=7, branch="spec/review/1"
    )

    served = served_in_order(scratch, tmp_path, installation, ["fresh/1", "review/1"])

    assert served == ["review/1", "fresh/1"]


def test_a_run_whose_unit_is_not_in_the_store_waits_as_least_urgent(
    scratch: Path, tmp_path: Path, installation: Installation
) -> None:
    stored(installation, new_unit("known/1", priority=4))

    served = served_in_order(scratch, tmp_path, installation, ["ghost/1", "known/1"])

    assert served == ["known/1", "ghost/1"]


def test_with_no_limit_a_run_makes_no_slot_and_no_marker_even_for_a_stored_unit(
    scratch: Path, tmp_path: Path, installation: Installation
) -> None:
    limited(None)
    stored(installation, new_unit("fast/1", priority=2))
    spans.current_unit.set(("fast/1", "fast", "n1", 1))

    unit_test_of(
        scratch,
        BundleMachine(scratch, reruns=[], passing=True),
        tmp_path / "t.jsonl",
        installation,
        [],
    )(cwd=scratch, base="main")

    assert not installation.locks_dir.exists() or not list(installation.locks_dir.iterdir())


# --- a settling unit's late check -------------------------------------------------------


def settling(installation: Installation, *uids: str) -> None:
    store = UnitStore(installation.state_dir / "units.json")
    for uid in uids:
        store.set_state(uid, SETTLING, pr=4, branch=f"spec/{uid}")


def test_a_late_check_s_run_is_served_before_a_priority_0_unit_s_run_that_began_waiting_first(
    scratch: Path, tmp_path: Path, installation: Installation
) -> None:
    stored(installation, new_unit("urgent/1", priority=0), new_unit("late/1", priority=4))
    UnitStore(installation.state_dir / "units.json").set_state(
        "urgent/1", IN_REVIEW, pr=7, branch="spec/urgent/1"
    )
    settling(installation, "late/1")

    served = served_in_order(
        scratch, tmp_path, installation, ["urgent/1", "late/1"], late=["late/1"]
    )

    assert served == ["late/1", "urgent/1"]
    assert "late/1" in [row.get("unit") for row in rows(tmp_path / "test-runs.jsonl")]


def test_two_late_checks_are_served_in_the_order_they_began_waiting(
    scratch: Path, tmp_path: Path, installation: Installation
) -> None:
    stored(installation, new_unit("late/2", priority=0), new_unit("late/1", priority=4))
    settling(installation, "late/1", "late/2")

    served = served_in_order(
        scratch, tmp_path, installation, ["late/1", "late/2"], late=["late/1", "late/2"]
    )

    assert served == ["late/1", "late/2"]


def test_a_run_that_names_no_unit_still_waits_behind_a_late_check_as_least_urgent(
    scratch: Path, tmp_path: Path, installation: Installation
) -> None:
    stored(installation, new_unit("late/1", priority=4))
    settling(installation, "late/1")

    served = served_in_order(
        scratch, tmp_path, installation, ["ghost/1", "late/1"], late=["late/1"]
    )

    assert served == ["late/1", "ghost/1"]


def test_the_late_check_s_run_names_its_unit_in_the_waiting_marker_and_the_ledger_row(
    scratch: Path, tmp_path: Path
) -> None:
    repo = init_repo(tmp_path / "checkouts" / "app")
    commit(repo, "pyproject.toml", '[project]\nname = "app"\nversion = "0"\n')
    installation = make_installation(
        tmp_path / "planning", repos={"app": {"path": str(repo), "slug": "example/app"}}
    )
    limited(1)
    ledger, log = tmp_path / "test-runs.jsonl", []
    unit = stored_unit("late/1", change="late")
    UnitStore(installation.state_dir / "units.json").upsert([unit])
    settling(installation, "late/1")
    passes = events.build_base_passes(
        {"app": repo},
        unit_test_of=lambda name: unit_test_of(
            scratch, BundleMachine(scratch, reruns=[], passing=True), ledger, installation, log
        ),
    )
    holder = ExitStack()
    holder.enter_context(unit_test_slot(installation.locks_dir, 1, holder="other/1"))
    outcome: list[bool | None] = []

    with running(lambda: outcome.append(passes(unit, "FAILED tests/test_one.py"))):
        wait_for(lambda: "late/1" in waiting_units(installation.locks_dir), what="the marker")
        holder.close()

    assert outcome == [True]
    assert [row["unit"] for row in rows(ledger) if "unit" in row] == ["late/1"]


def test_another_run_of_a_settling_unit_is_not_ranked_as_its_late_check(
    scratch: Path, tmp_path: Path, installation: Installation
) -> None:
    stored(installation, new_unit("urgent/1", priority=0), new_unit("late/1", priority=4))
    UnitStore(installation.state_dir / "units.json").set_state(
        "urgent/1", IN_REVIEW, pr=7, branch="spec/urgent/1"
    )
    settling(installation, "late/1")

    served = served_in_order(scratch, tmp_path, installation, ["urgent/1", "late/1"])

    assert served == ["urgent/1", "late/1"], "only the late check's own run goes first"
