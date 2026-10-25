"""`abk planning split` prints the units by origin, the no-directory ids and the dropped edges."""

from tests.factories import new_unit
from tests.planning_split_support import split
from tests.split_archived_units_support import archived_trees
from tests.split_sources import snapshot_tree, write_change, write_units


def line_with(out, *words):
    (line,) = [x for x in out.splitlines() if all(word in x for word in words)]
    return line


def test_the_units_are_split_by_origin_under_the_total(tmp_path, capsys):
    source, destination, installation = archived_trees(tmp_path)
    write_change(installation, "two", ["app"])
    write_change(installation, "older", ["app"], archived="2024-01-01")
    write_units(
        installation,
        new_unit("one/2", state="merged"),
        new_unit("two/1", state="merged"),
        new_unit("older/1", state="merged"),
        new_unit("stays/2", repo="lib", state="merged"),
        new_unit("stays/3", repo="lib", state="merged"),
        new_unit("stays/4", repo="lib", state="merged"),
    )
    before = (snapshot_tree(source), snapshot_tree(destination))

    code = split(source, "--repo", "app", "--to", str(destination))

    out = capsys.readouterr().out
    lines = out.splitlines()
    assert code == 0
    assert (snapshot_tree(source), snapshot_tree(destination)) == before
    total = lines.index(line_with(out, "units:"))
    assert "units: 7" in lines[total]
    assert lines.index("    3 active") > total
    assert "    3 archived" in lines
    assert "    1 with no change directory, moved by repo: gone/1" in lines
    assert "    4 left in the source" in lines


def test_a_dropped_edge_is_one_line_with_a_count(tmp_path, capsys):
    source, destination, _ = archived_trees(tmp_path, dropped_edge=True)

    code = split(source, "--repo", "app", "--to", str(destination))

    out = capsys.readouterr().out
    assert code == 0
    line_with(out, "old/2", "depends_on", "stays/1", "dropped")
    assert "  dropped edges: 1" in out.splitlines()


def test_a_remove_without_apply_describes_the_archived_units_among_the_removals(tmp_path, capsys):
    source, destination, _ = archived_trees(tmp_path)
    before = (snapshot_tree(source), snapshot_tree(destination))

    code = split(source, "--repo", "app", "--to", str(destination), "--remove")

    lines = capsys.readouterr().out.splitlines()
    assert code == 0
    for unit in ("old/1", "old/2", "gone/1"):
        assert f"  would remove unit {unit}" in lines
    assert "  would remove unit stays/1" not in lines
    assert (snapshot_tree(source), snapshot_tree(destination)) == before
