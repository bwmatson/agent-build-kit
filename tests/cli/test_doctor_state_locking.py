"""`abk doctor` over the state directory's mount and lock probe (spec: state-locking-on-a-share)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.pipeline import lock_probe
from agent_build_kit.pipeline.lock_probe import ProbeResult
from agent_build_kit.pipeline.mounts import Mount
from tests.cli.in_repo_doctor import checks_of, in_repo, named
from tests.cli.public_content_repo import said

MOUNT = "state mount"
LOCKING = "state locking"


class Probes:
    """Counts the probes the doctor runs, and answers as a test chooses."""

    def __init__(self) -> None:
        self.count = 0
        self.result = ProbeResult(passed=True, detail="ok")

    def __call__(self, directory: Path, *args, **kwargs) -> ProbeResult:
        self.count += 1
        return self.result


@pytest.fixture
def probes(monkeypatch: pytest.MonkeyPatch) -> Probes:
    found = Probes()
    monkeypatch.setattr(lock_probe, "probe_locking", found)
    return found


def lookup(fstype: str, *, source: str = "files:/export", options: str = "rw"):
    mount = Mount(fstype=fstype, source=source, options=options, local=fstype == "ext4")
    return lambda path, table=None: mount


def test_a_share_that_passes_is_named_and_its_locking_is_ok(tmp_path: Path, probes: Probes) -> None:
    config = in_repo(tmp_path / "app")

    checks = checks_of(config, mount_of=lookup("nfs4"))

    [mount] = named(checks, MOUNT)
    assert mount.status == "info"
    assert "nfs4" in mount.detail
    assert "files:/export" in mount.detail
    assert "one pipeline host" in mount.detail
    [locking] = named(checks, LOCKING)
    assert locking.status == "ok"


def test_a_failed_probe_fails_with_the_mount_type_and_the_fix(
    tmp_path: Path, probes: Probes
) -> None:
    probes.result = ProbeResult(
        passed=False, detail="two processes both held the lock on cifs", fix="mount with nobrl"
    )
    config = in_repo(tmp_path / "app")

    [found] = named(checks_of(config, mount_of=lookup("cifs")), LOCKING)

    assert found.status == "FAIL"
    assert "cifs" in said(found)
    assert "nobrl" in found.fix


def test_a_local_state_gives_no_mount_line_and_runs_the_probe_once(
    tmp_path: Path, probes: Probes
) -> None:
    config = in_repo(tmp_path / "app")

    checks = checks_of(config, mount_of=lookup("ext4"))

    assert named(checks, MOUNT) == []
    assert named(checks, LOCKING) == []
    assert probes.count == 1


def test_a_hard_nfs_mount_warns_naming_the_option(tmp_path: Path, probes: Probes) -> None:
    config = in_repo(tmp_path / "app")

    checks = checks_of(config, mount_of=lookup("nfs4", options="rw,hard,vers=4.2"))

    [warning] = [c for c in named(checks, MOUNT) if c.status == "warn"]
    assert "hard" in said(warning)
