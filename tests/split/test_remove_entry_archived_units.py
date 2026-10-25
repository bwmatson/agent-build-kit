"""The repo's entry goes only when no unit of the repo is left, archived and no-directory ones
included."""

import shutil

from tests.factories import new_unit
from tests.planning_split_support import split
from tests.split_archived_units_support import archived_trees
from tests.split_remove_support import declare_project
from tests.split_sources import write_change, write_units

ARGV = ("--repo", "app", "--apply", "--remove")


def test_the_entry_goes_when_only_archived_and_no_directory_units_were_left(tmp_path):
    source, destination, installation = archived_trees(tmp_path)
    shutil.rmtree(installation.changes_dir / "one")
    write_units(installation, new_unit("one/1", repo="lib", state="merged"))

    code = split(source, *ARGV, "--to", str(destination))

    assert code == 0
    assert "  app:\n" not in (source / "abk.yaml").read_text()


def test_a_staying_unit_of_the_repo_keeps_the_entry_naming_the_unit(tmp_path, capsys):
    source, destination, installation = archived_trees(tmp_path)
    write_change(installation, "both", ["app", "lib"])
    write_units(installation, new_unit("both/1", repo="app", state="merged"))

    code = split(source, *ARGV, "--allow-mixed", "source", "--to", str(destination))

    out = capsys.readouterr().out
    assert code == 1
    (line,) = [x for x in out.splitlines() if x.startswith("kept repo app: still named by")]
    assert "unit both/1" in line
    assert "  app:\n" in (source / "abk.yaml").read_text()


def test_a_project_split_leaves_the_entry(tmp_path):
    source, destination, installation = archived_trees(tmp_path)
    for root in (source, destination):
        declare_project(root, "app", "web")
    write_units(installation, new_unit("site/1", repo="app", project="web", state="merged"))
    original = (source / "abk.yaml").read_text()

    code = split(source, *ARGV, "--project", "web", "--to", str(destination))

    assert code == 0
    assert (source / "abk.yaml").read_text() == original
