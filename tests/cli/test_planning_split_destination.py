"""The destination must already be an installation; the command never creates one."""

import pytest

from tests.planning_split_support import load, split, write_installation
from tests.split_sources import snapshot_tree, write_change


@pytest.fixture
def source(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    write_installation(root)
    write_change(load(root), "moves", ["app"])
    return root


def apply(source, destination):
    before = (snapshot_tree(source), snapshot_tree(destination))
    code = split(source, "--repo", "app", "--to", str(destination), "--apply")
    assert (snapshot_tree(source), snapshot_tree(destination)) == before
    return code


def test_an_empty_directory_is_refused_naming_abk_yaml_and_abk_init(tmp_path, source, capsys):
    destination = tmp_path / "empty"
    destination.mkdir()

    assert apply(source, destination) == 2

    err = capsys.readouterr().err
    assert "abk.yaml" in err and "abk init" in err


def test_a_config_without_the_rules_stamp_is_refused_naming_the_file(tmp_path, source, capsys):
    destination = tmp_path / "destination"
    destination.mkdir()
    write_installation(destination, {"lib": ()}, stamp=False)

    assert apply(source, destination) == 2

    assert str(destination / "openspec" / "config.yaml") in capsys.readouterr().err


def test_a_missing_state_directory_is_refused(tmp_path, source, capsys):
    destination = tmp_path / "destination"
    destination.mkdir()
    write_installation(destination, {"lib": ()}, state=False)

    assert apply(source, destination) == 2

    assert str(destination / "runs") in capsys.readouterr().err


def test_a_destination_that_is_the_source_is_refused(source, capsys):
    assert apply(source, source / ".") == 2

    assert "source" in capsys.readouterr().err
