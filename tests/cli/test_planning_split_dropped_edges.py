"""`abk planning split` prints why each dropped edge's target stays, and the count by reason."""

import re

from tests.factories import new_unit
from tests.planning_split_support import load, split
from tests.split_remove_support import trees
from tests.split_sources import snapshot_tree, write_change, write_units

STAYS = ", stays in the source)"
KEPT = f"(merged unit of a change kept in the source{STAYS}"
FOREIGN = f"(merged unit of another repo{STAYS}"
PROJECT = f"(merged unit of another project{STAYS}"


def kept_and_foreign(tmp_path):
    """A moved `app` change `g` whose unit depends on a merged unit of the kept mixed change `m`
    and on one of the staying `lib` change `o`, and whose group 1 has `Needs: m group 4`."""
    source, destination = trees(tmp_path)
    installation = load(source)
    tasks = write_change(installation, "g", ["app"]) / "tasks.md"
    tasks.write_text(tasks.read_text().replace("\n- [ ]", "\nNeeds: m group 4\n\n- [ ]", 1))
    write_change(installation, "m", ["app", "lib", "app", "app"])
    write_change(installation, "o", ["lib"])
    write_units(
        installation,
        new_unit("g/1", depends_on=("m/4", "o/1")),
        new_unit("m/4", repo="app", state="merged"),
        new_unit("o/1", repo="lib", state="merged"),
    )
    return source, destination


def dropped_lines(out):
    return [line for line in out.splitlines() if "dropped" in line and "unit " in line]


def test_each_dropped_edge_line_ends_with_why_the_target_stays(tmp_path, capsys):
    source, destination = kept_and_foreign(tmp_path)
    before = (snapshot_tree(source), snapshot_tree(destination))

    code = split(source, "--repo", "app", "--allow-mixed", "source", "--to", str(destination))

    out = capsys.readouterr().out
    assert code == 0, out
    lines = dropped_lines(out)
    assert [line.endswith(KEPT) for line in lines if "m/4" in line] == [True]
    assert [line.endswith(FOREIGN) for line in lines if "o/1" in line] == [True]
    assert (snapshot_tree(source), snapshot_tree(destination)) == before


def test_the_count_lists_only_the_reasons_that_occurred(tmp_path, capsys):
    source, destination = kept_and_foreign(tmp_path)

    split(source, "--repo", "app", "--allow-mixed", "source", "--to", str(destination))

    assert (
        "  dropped edges: 2 (another repo: 1, kept change: 1)"
        in capsys.readouterr().out.splitlines()
    )


def test_one_reason_leaves_the_count_plain(tmp_path, capsys):
    source, destination = trees(tmp_path)
    installation = load(source)
    write_change(installation, "g", ["app"])
    write_change(installation, "m", ["app", "lib", "app", "app"])
    write_units(
        installation,
        new_unit("g/1", depends_on=("m/4",)),
        new_unit("m/4", repo="app", state="merged"),
    )

    code = split(source, "--repo", "app", "--allow-mixed", "source", "--to", str(destination))

    out = capsys.readouterr().out
    assert code == 0, out
    assert "  dropped edges: 1" in out.splitlines()


def test_the_needs_note_is_a_warning_line_and_the_exit_is_zero(tmp_path, capsys):
    source, destination = kept_and_foreign(tmp_path)

    code = split(source, "--repo", "app", "--allow-mixed", "source", "--to", str(destination))

    out = capsys.readouterr().out
    assert code == 0, out
    (line,) = [x for x in out.splitlines() if x.startswith("warning:") and "group 1" in x]
    assert re.search(r"\bg\b", line) and re.search(r"\bm\b", line)
    assert not [x for x in out.splitlines() if x.startswith("refused:")]


def test_a_project_target_names_another_project(tmp_path, capsys):
    source, destination = trees(tmp_path)
    config = source / "abk.yaml"
    marker = "    slug: example/app\n"
    config.write_text(
        config.read_text().replace(
            marker, f"{marker}    projects:\n      - path: web\n      - path: api\n"
        )
    )
    installation = load(source)
    write_change(installation, "w", ["app/web"])
    write_change(installation, "p", ["app/api"])
    write_units(
        installation,
        new_unit("w/1", depends_on=("p/1",), project="web"),
        new_unit("p/1", repo="app", project="api", state="merged"),
    )
    before = (snapshot_tree(source), snapshot_tree(destination))

    argv = ("--repo", "app", "--project", "web", "--allow-mixed", "source")
    code = split(source, *argv, "--to", str(destination))

    out = capsys.readouterr().out
    assert code == 0, out
    (line,) = dropped_lines(out)
    assert line.endswith(PROJECT)
    assert "  dropped edges: 1" in out.splitlines()
    assert (snapshot_tree(source), snapshot_tree(destination)) == before
