"""`abk planning split` follows each side's state directory: it refuses two sides that share one,
and reads the state of a side outside its repository as not under git (spec:
planning-state-external-checks)."""

from pathlib import Path

from agent_build_kit.split.select import SplitUsageError, load_destination
from tests.planning_split_support import load, split
from tests.split_remove_support import populate, trees, unit_ids
from tests.split_sources import snapshot_tree


def give_state(root: Path, state: Path) -> None:
    """The installation at `root` keeps its state in `state`, an existing directory."""
    state.mkdir(parents=True, exist_ok=True)
    config = root / "abk.yaml"
    config.write_text(config.read_text() + f"planning:\n  state_dir: {state}\n")


def test_a_shared_state_directory_is_refused_and_separate_ones_each_keep_their_records(
    tmp_path, capsys
):
    source, destination = trees(tmp_path)
    shared = tmp_path / "shared-state"
    give_state(source, shared)
    give_state(destination, shared)
    populate(source)
    before = (snapshot_tree(source), snapshot_tree(destination), snapshot_tree(shared))

    try:
        load_destination(destination, load(source))
    except SplitUsageError as refused:
        assert str(shared) in str(refused)
        assert "planning.home" in str(refused)
    else:
        raise AssertionError("a shared state directory was accepted")
    code = split(source, "--repo", "app", "--to", str(destination), "--apply", "--remove")
    assert code != 0
    assert str(shared) in capsys.readouterr().err
    assert (snapshot_tree(source), snapshot_tree(destination), snapshot_tree(shared)) == before

    own = tmp_path / "destination-state"
    config = destination / "abk.yaml"
    config.write_text(config.read_text().replace(str(shared), str(own)))
    own.mkdir()

    assert split(source, "--repo", "app", "--to", str(destination), "--apply", "--remove") == 0

    assert unit_ids(load(source)) == ["stays/1"]
    assert unit_ids(load(destination)) == ["one/1", "two/1"]
    assert (own / "units.json").is_file()


def test_the_plan_says_the_outside_state_is_not_under_git(tmp_path, capsys):
    source, destination = trees(tmp_path)
    give_state(source, tmp_path / "source-state")
    give_state(destination, tmp_path / "destination-state")

    code = split(source, "--repo", "app", "--to", str(destination))

    out = capsys.readouterr().out
    assert code == 0, out
    state = str(tmp_path / "source-state")
    assert [line for line in out.splitlines() if state in line and "not under git" in line]
