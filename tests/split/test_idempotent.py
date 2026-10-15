"""A second run changes nothing, and the source is not written without `--remove`."""

from tests.planning_split_support import load, split
from tests.split_remove_support import mtimes, populate, trees, unit_ids
from tests.split_sources import snapshot_tree


def state_of(*roots):
    return [(snapshot_tree(root), mtimes(root)) for root in roots]


def test_a_second_run_of_an_applied_split_has_nothing_to_do(tmp_path, capsys):
    source, destination = trees(tmp_path)
    populate(source)
    argv = ("--repo", "app", "--to", str(destination), "--apply", "--remove")
    assert split(source, *argv) == 0
    capsys.readouterr()
    before = state_of(source, destination)

    code = split(source, *argv)

    assert code == 0
    assert "nothing to do" in capsys.readouterr().out
    assert state_of(source, destination) == before


def test_a_source_that_still_holds_the_units_is_finished_by_remove(tmp_path):
    source, destination = trees(tmp_path)
    installation = populate(source)
    split(source, "--repo", "app", "--to", str(destination), "--apply")
    copied = state_of(destination)

    code = split(source, "--repo", "app", "--to", str(destination), "--apply", "--remove")

    assert code == 0
    assert unit_ids(installation) == ["stays/1"]
    assert not (load(source).changes_dir / "one").exists()
    assert state_of(destination) == copied


def test_without_remove_the_source_is_not_written_and_a_rerun_has_nothing_to_do(tmp_path, capsys):
    source, destination = trees(tmp_path)
    populate(source)
    argv = ("--repo", "app", "--to", str(destination), "--apply")
    before = state_of(source)

    assert split(source, *argv) == 0

    assert state_of(source) == before
    capsys.readouterr()
    copied = state_of(destination)
    assert split(source, *argv) == 0
    assert "nothing to do" in capsys.readouterr().out
    assert state_of(source, destination) == [*before, *copied]
