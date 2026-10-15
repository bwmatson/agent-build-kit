"""`--apply --remove` takes out of the source only what was moved, after the copy is verified."""

import json

from agent_build_kit.split import copy
from tests.planning_split_support import load, split
from tests.split_remove_support import populate, trees, unit_ids
from tests.split_sources import snapshot_tree

KEPT = ("usage-ledger.jsonl", "spec-snapshots", "logs")


def test_what_moved_is_gone_from_the_source_and_present_in_the_destination(tmp_path, capsys):
    source, destination = trees(tmp_path)
    installation = populate(source)

    code = split(source, "--repo", "app", "--to", str(destination), "--apply", "--remove")

    moved = load(destination)
    assert code == 0, capsys.readouterr().out
    for name in ("one", "two"):
        assert not (installation.changes_dir / name).exists()
        assert (moved.changes_dir / name / "tasks.md").is_file()
    assert not (installation.changes_dir / "archive" / "2025-01-01-old").exists()
    assert (moved.changes_dir / "archive" / "2025-01-01-old" / "tasks.md").is_file()
    assert not (installation.specs_dir / "specs" / "capability").exists()
    assert (moved.specs_dir / "specs" / "capability" / "spec.md").is_file()
    assert unit_ids(installation) == ["stays/1"]
    assert unit_ids(moved) == ["one/1", "two/1"]
    plans = json.loads((installation.state_dir / "planned.json").read_text())
    assert set(plans) == {"stays"}
    assert set(json.loads((moved.state_dir / "planned.json").read_text())) == {"one", "two"}


def test_a_directory_is_removed_only_when_empty(tmp_path):
    source, destination = trees(tmp_path)
    installation = populate(source)
    (installation.changes_dir / "one" / "tasks.md.lock").write_text("held\n")

    split(source, "--repo", "app", "--to", str(destination), "--apply", "--remove")

    left = sorted(p.name for p in (installation.changes_dir / "one").rglob("*") if p.is_file())
    assert left == ["tasks.md.lock"]
    assert not (installation.changes_dir / "two").exists()


def test_a_destination_file_that_differs_after_the_copy_removes_nothing(
    tmp_path, monkeypatch, capsys
):
    source, destination = trees(tmp_path)
    populate(source)
    real = copy.carry_out

    def corrupting(src, dest, plan, **kwargs):
        report = real(src, dest, plan, **kwargs)
        (dest.changes_dir / "one" / "proposal.md").write_text("changed behind the copy\n")
        return report

    monkeypatch.setattr(copy, "carry_out", corrupting)
    before = snapshot_tree(source)

    code = split(source, "--repo", "app", "--to", str(destination), "--apply", "--remove")

    assert code == 1
    assert snapshot_tree(source) == before
    assert "one/proposal.md" in capsys.readouterr().out


def test_nothing_else_is_removed(tmp_path):
    source, destination = trees(tmp_path)
    installation = populate(source)
    others = snapshot_tree(installation.state_dir)
    staying = snapshot_tree(installation.changes_dir / "stays")

    split(source, "--repo", "app", "--to", str(destination), "--apply", "--remove")

    after = snapshot_tree(installation.state_dir)
    for relative in (p for p in others if p.startswith(KEPT)):
        assert after[relative] == others[relative]
    assert snapshot_tree(installation.changes_dir / "stays") == staying
    assert unit_ids(installation) == ["stays/1"]
