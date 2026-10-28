"""`abk doctor` over the state directory's mount and lock probe (spec: state-locking-on-a-share)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.installation import load_installation
from agent_build_kit.pipeline import mounts
from agent_build_kit.pipeline.lock_probe import ProbeResult
from agent_build_kit.pipeline.mounts import Mount
from tests.cli.in_repo_doctor import checks_of, in_repo, named
from tests.cli.public_content_repo import said
from tests.lock_probe_fakes import Probes, count_probes, mount

MOUNT = "state mount"
LOCKING = "state locking"


@pytest.fixture
def probes(monkeypatch: pytest.MonkeyPatch) -> Probes:
    return count_probes(monkeypatch)


def lookup(fstype: str, *, source: str = "files:/export", options: str = "rw"):
    found = mount(fstype, source=source, options=options)
    return lambda path, table=None: found


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


def test_the_real_mount_lookup_is_used_when_none_is_given(
    tmp_path: Path, probes: Probes, monkeypatch: pytest.MonkeyPatch
) -> None:
    looked_up: list[Path] = []
    found = mount("nfs4")

    def fake(path: Path, table: str | None = None) -> Mount:
        looked_up.append(path)
        return found

    monkeypatch.setattr(mounts, "mount_of", fake)
    config = in_repo(tmp_path / "app")

    checks = checks_of(config)

    [line] = [c for c in named(checks, MOUNT) if c.status == "info"]
    assert "nfs4" in line.detail
    inst = load_installation(config)
    assert inst.state_dir in looked_up
    assert inst.local_dir in looked_up
