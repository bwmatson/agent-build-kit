"""`abk worker verify <change>`: a change's deploy-and-test verification as its own process (spec:
worker-kinds, resolution and verification run as workers).

The worker holds the e2e lock and the environment lock through the deploy and the tests and records
the result; the dispatcher archives the change on the next round and never waits for a
verification."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.cli.worker import cmd_worker_verify
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.archive import is_ready_to_archive
from agent_build_kit.pipeline.file_lock import LockTimeout, file_lock
from agent_build_kit.pipeline.snapshots import WAKE
from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.pipeline.units import MERGED
from agent_build_kit.pipeline.verify import Verification, VerifyRecord
from tests.dispatcher_support import (
    FakeSpawner,
    install_spawner,
    parse_worker_command,
    processes_workspace,
)
from tests.tick_pass import Builder, install_builder, isolate, stored, tick, warm_unit_graphs

pytestmark = pytest.mark.usefixtures("scripted_engine")

CHANGE = "done"


@pytest.fixture(autouse=True)
def warmed(tmp_path: Path) -> None:
    warm_unit_graphs(tmp_path)


@pytest.fixture(autouse=True)
def isolated(monkeypatch: pytest.MonkeyPatch) -> None:
    isolate(monkeypatch)


@pytest.fixture
def builder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Builder:
    return install_builder(tmp_path, monkeypatch)


@pytest.fixture
def spawner(monkeypatch: pytest.MonkeyPatch) -> FakeSpawner:
    return install_spawner(monkeypatch)


@pytest.fixture
def archived(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    done: list[str] = []

    def archive(units: list[StoredUnit], *, may_archive: object, **kwargs: object) -> list[str]:
        ready = [
            change
            for change in sorted({unit.change for unit in units})
            if is_ready_to_archive(change, units) and may_archive(change)  # type: ignore[operator]
        ]
        done.extend(ready)
        return ready

    monkeypatch.setattr(cli, "archive_ready_changes", archive)
    return done


def merged_change(builder: Builder) -> None:
    builder.store.upsert([stored(f"{CHANGE}/1", change=CHANGE)])
    builder.store.set_state(f"{CHANGE}/1", MERGED, pr=3, branch=f"spec/{CHANGE}/1")


def verify(inst: Installation, change: str = CHANGE) -> int:
    return cmd_worker_verify(argparse.Namespace(change=change), inst)


def held(path: Path) -> bool:
    try:
        with file_lock(path, 0):
            return False
    except LockTimeout:
        return True


def test_the_command_is_abk_worker_verify() -> None:
    args = parse_worker_command("verify", CHANGE)

    assert args.change == CHANGE
    assert args.func is cmd_worker_verify


def test_a_verify_worker_holds_both_locks_through_the_deploy_and_tests_and_records_the_result(
    tmp_path: Path, builder: Builder, monkeypatch: pytest.MonkeyPatch
) -> None:
    inst = processes_workspace(tmp_path)
    merged_change(builder)
    seen: list[tuple[bool, bool]] = []

    def deploy_and_test(change: str, units: list[StoredUnit], **kwargs: object) -> Verification:
        seen.append((held(inst.e2e_lock), held(inst.environment_lock)))
        return Verification(change=change, passed=True, units=[f"{CHANGE}/1"])

    monkeypatch.setattr(cli, "verify_change", deploy_and_test)

    code = verify(inst)

    assert code == 0
    assert seen == [(True, True)]
    assert not held(inst.e2e_lock)
    assert not held(inst.environment_lock)
    recorded = VerifyRecord(inst.state_dir / "verified.json").get(CHANGE)
    assert recorded is not None and recorded.passed
    assert (inst.state_dir / WAKE).exists()


def test_a_failed_verification_is_recorded_for_the_dispatcher(
    tmp_path: Path, builder: Builder, monkeypatch: pytest.MonkeyPatch
) -> None:
    inst = processes_workspace(tmp_path)
    merged_change(builder)
    monkeypatch.setattr(
        cli,
        "verify_change",
        lambda change, units, **kwargs: Verification(
            change=change, passed=False, detail="the live test failed", units=[f"{CHANGE}/1"]
        ),
    )

    verify(inst)

    recorded = VerifyRecord(inst.state_dir / "verified.json").get(CHANGE)
    assert recorded is not None
    assert not recorded.passed
    assert "the live test failed" in recorded.detail


def test_the_dispatcher_starts_a_verify_worker_without_deploying_or_waiting(
    tmp_path: Path,
    builder: Builder,
    spawner: FakeSpawner,
    archived: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inst = processes_workspace(tmp_path)
    merged_change(builder)

    def deploys(*args: object, **kwargs: object) -> Verification:
        raise AssertionError("the dispatcher ran the long part of a verification")

    monkeypatch.setattr(cli, "verify_change", deploys)

    assert tick(inst) == 0

    assert spawner.calls == [("verify", CHANGE)]
    assert archived == [], "nothing is archived until the verification is recorded"


def test_the_dispatcher_archives_a_verified_change_on_the_next_round(
    tmp_path: Path, builder: Builder, spawner: FakeSpawner, archived: list[str]
) -> None:
    inst = processes_workspace(tmp_path)
    merged_change(builder)
    VerifyRecord(inst.state_dir / "verified.json").put(
        Verification(change=CHANGE, passed=True, units=[f"{CHANGE}/1"])
    )

    assert tick(inst) == 0

    assert archived == [CHANGE]
    assert spawner.calls == [], "a recorded result is not verified again"


def test_a_verify_worker_killed_while_deploying_leaves_a_stale_lock_and_is_retried(
    tmp_path: Path, builder: Builder, spawner: FakeSpawner, archived: list[str]
) -> None:
    inst = processes_workspace(tmp_path)
    merged_change(builder)
    assert tick(inst) == 0
    # The worker was killed: its lock file stays behind and nothing holds the lock.
    inst.e2e_lock.parent.mkdir(parents=True, exist_ok=True)
    inst.e2e_lock.write_text("verify done\n")

    assert tick(inst) == 0

    assert spawner.calls == [("verify", CHANGE), ("verify", CHANGE)]
    assert archived == []


def test_a_verify_worker_finding_a_current_result_once_it_holds_the_locks_does_not_deploy_again(
    tmp_path: Path, builder: Builder, monkeypatch: pytest.MonkeyPatch
) -> None:
    inst = processes_workspace(tmp_path)
    merged_change(builder)
    record = VerifyRecord(inst.state_dir / "verified.json")
    earlier = Verification(change=CHANGE, passed=True, units=[f"{CHANGE}/1"], deployed=["svc-a"])
    record.put(earlier)

    def deploys(*args: object, **kwargs: object) -> Verification:
        raise AssertionError("a second worker deployed a change already verified")

    monkeypatch.setattr(cli, "verify_change", deploys)

    assert verify(inst) == 0

    assert record.get(CHANGE) == earlier
