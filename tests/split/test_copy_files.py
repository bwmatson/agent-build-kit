"""A split copies a moved change's files without overwriting a different one."""

import os
import stat

import pytest

from agent_build_kit.split.copy import CopyRefused, carry_out
from agent_build_kit.split.select import plan_split
from tests.split_sources import snapshot_tree, source_installation, write_change, write_spec


def installations(tmp_path):
    destination = source_installation(tmp_path / "destination")
    return source_installation(tmp_path / "source"), destination


def test_a_moved_change_is_copied_file_by_file_with_its_bytes_and_mode_and_without_lock_files(
    tmp_path,
):
    source, destination = installations(tmp_path)
    change = write_change(source, "moves", ["app"], deltas=["cap"])
    entry = write_change(source, "old", ["app"], archived="2026-01-01")
    (change / "design.md").write_bytes(b"caf\xc3\xa9 \r\n\x00bytes")
    (change / "tasks.md.lock").write_text("")
    script = change / "scripts" / "run.sh"
    script.parent.mkdir()
    script.write_text("#!/bin/sh\n")
    script.chmod(0o755)
    spec = write_spec(source, "cap")
    plan = plan_split(source, "app")
    assert plan.specs_moved == ("cap",)

    carry_out(source, destination, plan)

    copied = snapshot_tree(destination.specs_dir)
    assert not [name for name in copied if name.endswith(".lock")]
    for directory in (change, entry, spec):
        for path in directory.rglob("*"):
            if path.is_file() and path.suffix != ".lock":
                relative = path.relative_to(source.specs_dir)
                assert copied[str(relative)] == path.read_bytes()
    mode = stat.S_IMODE((destination.changes_dir / "moves" / "scripts" / "run.sh").stat().st_mode)
    assert mode == 0o755


def test_an_identical_destination_file_is_left_and_its_modification_time_does_not_move(tmp_path):
    source, destination = installations(tmp_path)
    change = write_change(source, "moves", ["app"])
    existing = destination.changes_dir / "moves" / "proposal.md"
    existing.parent.mkdir(parents=True)
    existing.write_bytes((change / "proposal.md").read_bytes())
    os.utime(existing, ns=(10**9, 10**9))

    report = carry_out(source, destination, plan_split(source, "app"))

    assert existing.stat().st_mtime_ns == 10**9
    assert report.files_unchanged == 1
    assert report.files_copied == 1
    assert (destination.changes_dir / "moves" / "tasks.md").is_file()


def test_a_different_destination_file_is_a_conflict_naming_the_path_with_nothing_written(tmp_path):
    source, destination = installations(tmp_path)
    write_change(source, "moves", ["app"])
    write_change(source, "also", ["app"])
    existing = destination.changes_dir / "moves" / "proposal.md"
    existing.parent.mkdir(parents=True)
    existing.write_text("a different proposal\n")
    before = snapshot_tree(destination.root)

    with pytest.raises(CopyRefused) as refused:
        carry_out(source, destination, plan_split(source, "app"))

    (error,) = refused.value.errors
    assert "moves/proposal.md" in error
    assert snapshot_tree(destination.root) == before
