"""Which mount holds a path, read from the text of `mountinfo` (spec: state-locking-on-a-share)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.pipeline import mounts
from agent_build_kit.pipeline.mounts import mount_of

TABLE = "\n".join(
    [
        "22 1 8:1 / / rw,relatime shared:1 - ext4 /dev/sda1 rw,errors=remount-ro",
        "40 22 0:35 / /mnt/share rw,relatime shared:9 - nfs4 files:/export "
        "rw,vers=4.2,hard,local_lock=all",
        "41 40 0:36 / /mnt/share/deep rw,relatime shared:10 - cifs //box/deep rw,nobrl",
        "42 22 0:37 / /scratch rw - tmpfs tmpfs rw,size=1G",
    ]
)


def test_the_longest_mount_point_holding_the_path_is_the_one() -> None:
    mount = mount_of(Path("/mnt/share/deep/state"), TABLE)

    assert (mount.fstype, mount.source) == ("cifs", "//box/deep")
    assert "nobrl" in mount.options


def test_a_mount_names_its_type_source_and_options() -> None:
    mount = mount_of(Path("/mnt/share/runs"), TABLE)

    assert (mount.fstype, mount.source) == ("nfs4", "files:/export")
    assert "local_lock=all" in mount.options
    assert "hard" in mount.options


def test_a_path_outside_every_other_mount_is_on_the_root() -> None:
    mount = mount_of(Path("/srv/state"), TABLE)

    assert (mount.fstype, mount.source) == ("ext4", "/dev/sda1")


def test_a_mount_point_is_not_matched_by_a_longer_name_sharing_its_prefix() -> None:
    mount = mount_of(Path("/mnt/share-other/state"), TABLE)

    assert mount.fstype == "ext4"


@pytest.mark.parametrize(
    "fstype", ["nfs4", "cifs", "9p", "drvfs", "fuse.sshfs", "virtiofs", "nfs", "smb3"]
)
def test_a_network_or_foreign_filesystem_is_not_local(fstype: str) -> None:
    table = f"30 1 0:30 / /mnt/x rw - {fstype} src rw"

    assert not mount_of(Path("/mnt/x/state"), table).local


@pytest.mark.parametrize("fstype", ["ext4", "xfs", "btrfs", "tmpfs", "overlay"])
def test_a_disk_or_memory_filesystem_is_local(fstype: str) -> None:
    table = f"30 1 0:30 / /mnt/x rw - {fstype} src rw"

    assert mount_of(Path("/mnt/x/state"), table).local


@pytest.mark.parametrize("table", ["", "not a mount table\nat all"])
def test_an_unreadable_table_gives_unknown_which_is_not_local_and_says_so(table: str) -> None:
    mount = mount_of(Path("/mnt/x"), table)

    assert mount.fstype == "unknown"
    assert not mount.local
    assert "mountinfo" in mount.source


def test_a_later_mount_on_the_same_point_covers_the_earlier_one() -> None:
    table = "\n".join(
        [
            "30 1 0:30 / /mnt/share rw - autofs systemd-1 rw",
            "31 30 0:31 / /mnt/share rw - nfs4 files:/export rw",
        ]
    )

    mount = mount_of(Path("/mnt/share/state"), table)

    assert mount.fstype == "nfs4"
    assert not mount.local


def test_a_missing_table_gives_unknown_naming_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    missing = tmp_path / "mountinfo"
    monkeypatch.setattr(mounts, "MOUNTINFO", missing)

    mount = mount_of(Path("/mnt/x"))

    assert mount.fstype == "unknown"
    assert not mount.local
    assert str(missing) in mount.source
