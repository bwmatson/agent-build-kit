"""`--apply --remove` removes the archived and no-directory units that moved, and no others."""

from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.split import copy
from tests.planning_split_support import load, split
from tests.split_archived_units_support import archived_trees
from tests.split_remove_support import unit_ids
from tests.split_sources import snapshot_tree

ARGV = ("--repo", "app", "--apply", "--remove")


def test_the_archive_entry_and_its_units_and_the_no_directory_unit_are_gone(tmp_path, capsys):
    source, destination, installation = archived_trees(tmp_path)
    staying = snapshot_tree(installation.changes_dir / "stays")

    code = split(source, *ARGV, "--to", str(destination))

    moved = load(destination)
    assert code == 0, capsys.readouterr().out
    assert not (installation.changes_dir / "archive" / "2025-01-01-old").exists()
    assert unit_ids(installation) == ["stays/1"]
    assert sorted(unit_ids(moved)) == ["gone/1", "old/1", "old/2", "one/1"]
    assert snapshot_tree(installation.changes_dir / "stays") == staying
    kept = UnitStore(installation.state_dir / "units.json").get("stays/1")
    assert kept.repo == "lib" and kept.state == "merged"


def test_a_destination_record_altered_after_the_copy_removes_nothing(tmp_path, monkeypatch, capsys):
    source, destination, _ = archived_trees(tmp_path)
    real = copy.carry_out

    def altering(src, dest, plan, **kwargs):
        report = real(src, dest, plan, **kwargs)
        store = UnitStore(dest.state_dir / "units.json")
        altered = store.get("old/1").model_copy(update={"feedback": "altered"})
        store.remove_units(["old/1"])
        store.import_units([altered])
        return report

    monkeypatch.setattr(copy, "carry_out", altering)
    before = snapshot_tree(source)

    code = split(source, *ARGV, "--to", str(destination))

    assert code == 1
    assert snapshot_tree(source) == before
    assert "old/1" in capsys.readouterr().out
