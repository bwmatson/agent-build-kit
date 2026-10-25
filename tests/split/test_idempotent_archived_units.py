"""A split that moved archived units and dropped an edge reruns to nothing, and a copy is finished
by `--remove`."""

from tests.planning_split_support import split
from tests.split_archived_units_support import archived_trees
from tests.split_remove_support import mtimes, unit_ids
from tests.split_sources import snapshot_tree


def state_of(*roots):
    return [(snapshot_tree(root), mtimes(root)) for root in roots]


def test_a_second_run_has_nothing_to_do_and_changes_no_file(tmp_path, capsys):
    source, destination, _ = archived_trees(tmp_path, dropped_edge=True)
    argv = ("--repo", "app", "--to", str(destination), "--apply", "--remove")
    assert split(source, *argv) == 0
    capsys.readouterr()
    before = state_of(source, destination)

    code = split(source, *argv)

    assert code == 0
    assert "nothing to do" in capsys.readouterr().out
    assert state_of(source, destination) == before


def test_a_source_that_still_holds_the_archived_units_is_finished_by_remove(tmp_path):
    source, destination, installation = archived_trees(tmp_path, dropped_edge=True)
    split(source, "--repo", "app", "--to", str(destination), "--apply")
    copied = state_of(destination)
    assert "old/1" in unit_ids(installation)

    code = split(source, "--repo", "app", "--to", str(destination), "--apply", "--remove")

    assert code == 0
    assert unit_ids(installation) == ["stays/1"]
    assert state_of(destination) == copied
