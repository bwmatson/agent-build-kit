"""The tick's lock probe of a state directory on a share (spec: state-locking-on-a-share)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline import lock_probe, mounts
from agent_build_kit.pipeline.lock_probe import CACHE_NAME, ProbeResult
from agent_build_kit.pipeline.mounts import Mount
from tests.conftest import make_installation
from tests.tick_pass import isolate, tick

DAY = 24 * 3600.0
FAR_FUTURE = 10.0**12


class Probes:
    """Counts the probes a tick starts, and answers as a test chooses."""

    def __init__(self) -> None:
        self.count = 0
        self.result = ProbeResult(passed=True, detail="ok")

    def __call__(self, directory: Path, *args, **kwargs) -> ProbeResult:
        self.count += 1
        return self.result


class Syncs:
    """Stands in for the planning sync and counts it."""

    def __init__(self) -> None:
        self.count = 0

    def __call__(self, *args, **kwargs) -> bool:
        self.count += 1
        return True


@pytest.fixture
def probes(monkeypatch: pytest.MonkeyPatch) -> Probes:
    found = Probes()
    monkeypatch.setattr(lock_probe, "probe_locking", found)
    return found


@pytest.fixture
def syncs(monkeypatch: pytest.MonkeyPatch) -> Syncs:
    found = Syncs()
    isolate(monkeypatch)
    monkeypatch.setattr(cli, "sync_or_stop", found)
    return found


@pytest.fixture
def inst(tmp_path: Path) -> Installation:
    return make_installation(
        tmp_path,
        planning={"state_dir": ".", "worktree_root": str(tmp_path.parent / "trees")},
    )


def on(monkeypatch: pytest.MonkeyPatch, fstype: str, *, options: str = "rw") -> None:
    """Every path on a filesystem of this type."""
    mount = Mount(fstype=fstype, source="files:/export", options=options, local=fstype == "ext4")
    monkeypatch.setattr(mounts, "mount_of", lambda path, table=None: mount)


def cache(inst: Installation) -> Path:
    return inst.local_dir / CACHE_NAME


def listing(root: Path) -> list[str]:
    return sorted(str(p.relative_to(root)) for p in root.rglob("*"))


def test_a_tick_on_a_local_state_runs_no_probe_and_writes_no_cache(
    inst: Installation, probes: Probes, syncs: Syncs, monkeypatch: pytest.MonkeyPatch
) -> None:
    on(monkeypatch, "ext4")

    assert tick(inst) == 0

    assert probes.count == 0
    assert not cache(inst).exists()


def test_a_tick_on_a_share_probes_once_and_caches_the_pass_for_a_day(
    inst: Installation, probes: Probes, syncs: Syncs, monkeypatch: pytest.MonkeyPatch
) -> None:
    on(monkeypatch, "nfs4")

    assert tick(inst) == 0
    assert tick(inst) == 0

    assert probes.count == 1
    assert cache(inst).is_file()


def test_a_cache_older_than_a_day_probes_again(
    inst: Installation, probes: Probes, syncs: Syncs, monkeypatch: pytest.MonkeyPatch
) -> None:
    on(monkeypatch, "nfs4")
    tick(inst)
    monkeypatch.setattr(lock_probe, "time", SimpleNamespace(time=lambda: FAR_FUTURE))

    tick(inst)

    assert probes.count == 2


def test_a_changed_mount_option_probes_again(
    inst: Installation, probes: Probes, syncs: Syncs, monkeypatch: pytest.MonkeyPatch
) -> None:
    on(monkeypatch, "nfs4", options="rw,nolock")
    tick(inst)
    on(monkeypatch, "nfs4", options="rw")

    tick(inst)

    assert probes.count == 2


def test_a_failed_probe_prints_the_detail_exits_1_and_touches_nothing(
    inst: Installation,
    probes: Probes,
    syncs: Syncs,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    on(monkeypatch, "nfs4")
    probes.result = ProbeResult(
        passed=False, detail="two processes both held the lock on nfs4", fix="mount lockd"
    )
    before = listing(inst.state_dir)

    code = tick(inst)

    assert code == 1
    assert "two processes both held the lock on nfs4" in capsys.readouterr().out
    assert listing(inst.state_dir) == before
    assert syncs.count == 0
    assert not cache(inst).exists()
