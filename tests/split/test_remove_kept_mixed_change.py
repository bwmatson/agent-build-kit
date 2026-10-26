"""`--apply --remove` with a mixed change kept in the source moves a unit that depended on one of
its merged units, and leaves the change, its units and the repo's entry in the source."""

from pathlib import Path

from agent_build_kit.pipeline.unit_store import UnitStore
from tests.factories import new_unit
from tests.planning_split_support import load, split
from tests.split_remove_support import mtimes, trees, unit_ids
from tests.split_sources import snapshot_tree, write_change, write_units

KEPT = ("--allow-mixed", "source")


def kept_trees(tmp_path):
    """A source holding the `app` change `g`, whose unit depends on `m/4`, a merged `app` unit of
    the mixed change `m` (kept in the source), and a destination declaring only `lib`."""
    source, destination = trees(tmp_path)
    installation = load(source)
    write_change(installation, "g", ["app"])
    write_change(installation, "m", ["app", "lib", "app", "app"])
    write_units(
        installation,
        new_unit("g/1", depends_on=("m/4",), needs=("m/4",), merge_needs=("m/4",)),
        new_unit("m/4", repo="app", state="merged"),
    )
    return source, destination, installation


def state_of(*roots: Path):
    return [(snapshot_tree(root), mtimes(root)) for root in roots]


def test_the_moved_unit_goes_and_the_kept_change_and_its_units_stay(tmp_path, capsys):
    source, destination, installation = kept_trees(tmp_path)
    kept_unit = UnitStore(installation.state_dir / "units.json").get("m/4")
    kept_change = snapshot_tree(installation.changes_dir / "m")

    code = split(source, "--repo", "app", *KEPT, "--to", str(destination), "--apply", "--remove")

    out = capsys.readouterr().out
    moved = load(destination)
    assert code == 1, out
    assert not (installation.changes_dir / "g").exists()
    assert (moved.changes_dir / "g" / "tasks.md").is_file()
    assert unit_ids(installation) == ["m/4"]
    assert UnitStore(installation.state_dir / "units.json").get("m/4") == kept_unit
    assert snapshot_tree(installation.changes_dir / "m") == kept_change
    assert unit_ids(moved) == ["g/1"]
    assert UnitStore(moved.state_dir / "units.json").get("g/1").depends_on == ()
    assert not (moved.changes_dir / "m").exists()
    assert not [
        relative
        for relative, content in snapshot_tree(destination).items()
        if b"m/4" in content or relative.startswith("openspec/changes/m/")
    ]


def test_the_repo_entry_is_kept_naming_the_kept_unit(tmp_path, capsys):
    source, destination, _ = kept_trees(tmp_path)
    original = (source / "abk.yaml").read_text()

    code = split(source, "--repo", "app", *KEPT, "--to", str(destination), "--apply", "--remove")

    out = capsys.readouterr().out
    (line,) = [x for x in out.splitlines() if x.startswith("kept repo app: still named by")]
    assert code == 1
    assert "unit m/4" in line
    assert (source / "abk.yaml").read_text() == original


def test_a_second_run_has_nothing_to_do_and_changes_no_file(tmp_path, capsys):
    source, destination, _ = kept_trees(tmp_path)
    argv = ("--repo", "app", *KEPT, "--to", str(destination), "--apply")
    split(source, *argv, "--remove")
    capsys.readouterr()
    before = state_of(source, destination)

    code = split(source, *argv)

    assert code == 0
    assert "nothing to do" in capsys.readouterr().out
    assert state_of(source, destination) == before


def test_a_source_that_still_holds_the_change_after_a_copy_is_finished_by_remove(tmp_path, capsys):
    source, destination, installation = kept_trees(tmp_path)
    assert split(source, "--repo", "app", *KEPT, "--to", str(destination), "--apply") == 0
    copied = state_of(destination)
    assert "g/1" in unit_ids(installation)
    capsys.readouterr()

    split(source, "--repo", "app", *KEPT, "--to", str(destination), "--apply", "--remove")

    assert unit_ids(installation) == ["m/4"]
    assert not (installation.changes_dir / "g").exists()
    assert state_of(destination) == copied
