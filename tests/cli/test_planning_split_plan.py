"""`abk planning split` prints a plan, writes nothing without `--apply`, and exits by it."""

import re

import pytest

from agent_build_kit.cli.pipeline import record_plans
from tests.factories import new_unit
from tests.planning_split_support import load, split, write_installation
from tests.split_sources import snapshot_tree, write_change, write_spec, write_units


@pytest.fixture
def trees(tmp_path):
    source, destination = tmp_path / "source", tmp_path / "destination"
    source.mkdir()
    destination.mkdir()
    write_installation(source)
    write_installation(destination, {"lib": ()})
    return source, destination


def populated(source):
    installation = load(source)
    write_change(installation, "one", ["app"], deltas=["capability"])
    write_change(installation, "two", ["app"])
    write_change(installation, "old", ["app"], archived="2025-01-01")
    write_change(installation, "stays", ["lib"])
    write_spec(installation, "other")
    write_units(
        installation,
        new_unit("one/1", state="merged"),
        new_unit("one/2", state="merged"),
        new_unit("two/1", state="failed"),
        new_unit("stays/1", repo="lib", state="merged"),
    )
    plans = {"hash": "h", "attempts": 0, "ok": True}
    record_plans(installation, {"one": plans, "two": plans, "stays": plans})
    return installation


def kind_line(out, label):
    (line,) = [line for line in out.splitlines() if line.strip().startswith(label)]
    return line


def test_the_default_prints_the_plan_and_writes_nothing(trees, capsys):
    source, destination = trees
    populated(source)
    before = (snapshot_tree(source), snapshot_tree(destination))

    code = split(source, "--repo", "app", "--to", str(destination))

    out = capsys.readouterr().out
    assert code == 0
    assert (snapshot_tree(source), snapshot_tree(destination)) == before
    assert str(source) in out and str(destination) in out
    assert "app" in out
    assert "nothing was written" in out.splitlines()[-1].lower()


def test_a_count_is_printed_for_each_kind(trees, capsys):
    source, destination = trees
    populated(source)

    split(source, "--repo", "app", "--to", str(destination))

    out = capsys.readouterr().out
    for label, count in {
        "changes": 2,
        "archive entries": 1,
        "specs": 1,
        "units": 3,
        "plan records": 2,
        "config entries": 1,
    }.items():
        assert re.search(rf"\b{count}\b", kind_line(out, label)), label


def test_each_refusal_is_its_own_line_and_the_exit_is_one(trees, capsys):
    source, destination = trees
    installation = populated(source)
    write_change(installation, "both", ["app", "lib"])

    code = split(source, "--repo", "app", "--to", str(destination))

    out = capsys.readouterr().out
    assert code == 1
    (refusal,) = [line for line in out.splitlines() if "both" in line and "mixed" in line.lower()]
    assert "lib" in refusal
    assert "nothing was written" in out.splitlines()[-1].lower()


@pytest.mark.parametrize("argv", [("--allow-mixed", "both"), ("--spec", "nothing-here")])
def test_a_usage_problem_exits_two_naming_it(trees, capsys, argv):
    source, destination = trees
    populated(source)

    code = split(source, "--repo", "app", "--to", str(destination), *argv)

    assert code == 2
    assert argv[1] in capsys.readouterr().err


def test_an_undeclared_project_exits_two_naming_the_project(trees, capsys):
    source, destination = trees
    populated(source)

    code = split(source, "--repo", "app", "--project", "mobile", "--to", str(destination))

    assert code == 2
    assert "mobile" in capsys.readouterr().err


def test_dry_run_is_the_default_spelled_out(trees, capsys):
    source, destination = trees
    populated(source)
    before = (snapshot_tree(source), snapshot_tree(destination))

    code = split(source, "--repo", "app", "--to", str(destination), "--dry-run")

    assert code == 0
    assert (snapshot_tree(source), snapshot_tree(destination)) == before
    assert "nothing was written" in capsys.readouterr().out.lower()


def test_dry_run_with_apply_is_a_usage_problem(trees, capsys):
    source, destination = trees
    populated(source)
    before = (snapshot_tree(source), snapshot_tree(destination))

    code = split(source, "--repo", "app", "--to", str(destination), "--dry-run", "--apply")

    err = capsys.readouterr().err
    assert code == 2
    assert "--dry-run" in err and "--apply" in err
    assert (snapshot_tree(source), snapshot_tree(destination)) == before


def test_remove_without_apply_lists_what_it_would_remove(trees, capsys):
    source, destination = trees
    populated(source)
    before = (snapshot_tree(source), snapshot_tree(destination))

    code = split(source, "--repo", "app", "--to", str(destination), "--remove")

    out = capsys.readouterr().out
    assert code == 0
    removing = [line for line in out.splitlines() if "remove" in line.lower()]
    assert any("one" in line for line in removing) and any("one/1" in line for line in removing)
    assert (snapshot_tree(source), snapshot_tree(destination)) == before
