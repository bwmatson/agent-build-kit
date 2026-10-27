"""`abk doctor` over the local directory: it must be on a local filesystem, an old machine-local
file left in the state directory is reported, and a tracked `planning.local_dir` is a machine key
(spec: planning-local-directory)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from agent_build_kit.cli.doctor import MACHINE_KEYS
from agent_build_kit.pipeline.mounts import Mount
from tests.cli.in_repo_doctor import PROTECTED, STATE_IGNORES, checks_of, host_says, named
from tests.cli.public_content_repo import OVERLAY, committed_config, planning, said

LOCAL_DIR = "local dir"


def mount_of_type(fstype: str):
    """A mount lookup that puts every path on a filesystem of this type."""

    def lookup(path: Path) -> Mount:
        local = fstype in {"ext4", "xfs", "btrfs", "tmpfs", "overlay"}
        return Mount(fstype=fstype, source="//box/share", options="rw", local=local)

    return lookup


def with_local_dir(root: Path) -> tuple[Path, Path, Path]:
    """The `abk.yaml` of an in-repo installation keeping its state in `runs` under the root and
    its local files in `local` beside it, set in the ignored local file; the config, the state
    directory and the local directory."""
    host_says(PROTECTED)
    config = planning(root, ignore=STATE_IGNORES, publish="branch")
    local = root.parent / "local"
    (root / OVERLAY).write_text(yaml.safe_dump({"planning": {"local_dir": str(local)}}))
    return config, root / "runs", local


@pytest.mark.parametrize("fstype", ["cifs", "nfs4"])
def test_a_local_directory_on_a_share_fails_naming_the_type_and_the_settings(
    tmp_path: Path, fstype: str
) -> None:
    config, _, local = with_local_dir(tmp_path / "app")

    [found] = named(checks_of(config, mount_of=mount_of_type(fstype)), LOCAL_DIR)

    assert found.status == "fail"
    assert fstype in found.detail
    assert str(local) in found.detail
    assert "planning.local_dir" in found.fix
    assert "ABK_LOCAL_DIR" in found.fix


def test_a_local_directory_on_local_disk_is_ok(tmp_path: Path) -> None:
    config, _, _ = with_local_dir(tmp_path / "app")

    [found] = named(checks_of(config, mount_of=mount_of_type("ext4")), LOCAL_DIR)

    assert found.status == "ok"


@pytest.mark.parametrize(
    "leftover", ["locks", "leases", "e2e.lock", "environment.lock", "unit-graphs.sqlite"]
)
def test_an_old_machine_local_file_in_the_state_directory_is_one_warning_naming_it(
    tmp_path: Path, leftover: str
) -> None:
    config, state, _ = with_local_dir(tmp_path / "app")
    old = state / leftover
    old.parent.mkdir(parents=True, exist_ok=True)
    if "." in leftover:
        old.write_text("")
    else:
        old.mkdir()

    found = named(checks_of(config, mount_of=mount_of_type("ext4")), LOCAL_DIR)

    [warning] = [c for c in found if c.status == "warn"]
    assert leftover in warning.detail
    assert "delete" in said(warning)


def test_a_state_directory_with_no_old_files_gives_no_warning(tmp_path: Path) -> None:
    config, state, _ = with_local_dir(tmp_path / "app")
    state.mkdir(parents=True)

    found = named(checks_of(config, mount_of=mount_of_type("ext4")), LOCAL_DIR)

    assert [c.status for c in found] == ["ok"]


def test_a_tracked_local_dir_is_a_machine_key_like_the_state_dir(tmp_path: Path) -> None:
    config = committed_config(
        tmp_path / "app", {"planning": {"local_dir": str(tmp_path / "somewhere")}}
    )

    keys = named(checks_of(config, mount_of=mount_of_type("ext4")), MACHINE_KEYS)

    [found] = [c for c in keys if "planning.local_dir" in c.detail]
    assert found.status == "warn"
    assert str(tmp_path / "somewhere") not in said(found)
