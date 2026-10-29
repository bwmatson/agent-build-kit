from pathlib import Path

from agent_build_kit.path_discovery import find_up


def _touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x")
    return path


def test_start_folder_is_searched_first(tmp_path: Path):
    _touch(tmp_path / "config.yaml")
    inner = _touch(tmp_path / "a" / "config.yaml")
    assert find_up(["config.yaml"], tmp_path / "a", stop=tmp_path) == inner


def test_nearest_folder_above_wins(tmp_path: Path):
    _touch(tmp_path / "config.yaml")
    near = _touch(tmp_path / "a" / "config.yaml")
    (tmp_path / "a" / "b" / "c").mkdir(parents=True)
    assert find_up(["config.yaml"], tmp_path / "a" / "b" / "c", stop=tmp_path) == near


def test_names_are_tried_in_order_within_a_folder(tmp_path: Path):
    _touch(tmp_path / "b.yaml")
    first = _touch(tmp_path / "a.yaml")
    assert find_up(["a.yaml", "b.yaml"], tmp_path, stop=tmp_path) == first


def test_walk_stops_at_the_stop_folder(tmp_path: Path):
    _touch(tmp_path / "config.yaml")
    start = tmp_path / "stop" / "a"
    start.mkdir(parents=True)
    assert find_up(["config.yaml"], start, stop=tmp_path / "stop") is None


def test_stop_folder_itself_is_searched(tmp_path: Path):
    found = _touch(tmp_path / "stop" / "config.yaml")
    start = tmp_path / "stop" / "a"
    start.mkdir()
    assert find_up(["config.yaml"], start, stop=tmp_path / "stop") == found


def test_start_outside_the_stop_folder_finds_nothing(tmp_path: Path):
    _touch(tmp_path / "config.yaml")
    (tmp_path / "other").mkdir()
    (tmp_path / "stop").mkdir()
    assert find_up(["config.yaml"], tmp_path / "other", stop=tmp_path / "stop") is None


def test_file_and_missing_start_are_accepted(tmp_path: Path):
    found = _touch(tmp_path / "config.yaml")
    sibling = _touch(tmp_path / "a" / "file.txt")
    missing = tmp_path / "a" / "b" / "c"
    assert find_up(["config.yaml"], sibling, stop=tmp_path) == found
    assert find_up(["config.yaml"], missing, stop=tmp_path) == found


def test_nothing_found_is_none(tmp_path: Path):
    (tmp_path / "a").mkdir()
    assert find_up(["config.yaml"], tmp_path / "a", stop=tmp_path) is None


def test_outermost_match_on_request(tmp_path: Path):
    outer = _touch(tmp_path / "config.yaml")
    _touch(tmp_path / "a" / "config.yaml")
    start = tmp_path / "a" / "b"
    start.mkdir()
    assert find_up(["config.yaml"], start, stop=tmp_path, outermost=True) == outer


def test_rejected_candidate_is_skipped(tmp_path: Path):
    higher = _touch(tmp_path / "config.yaml")
    rejected = _touch(tmp_path / "a" / "config.yaml")
    start = tmp_path / "a" / "b"
    start.mkdir()
    found = find_up(["config.yaml"], start, stop=tmp_path, accept=lambda p: p != rejected)
    assert found == higher


def test_every_candidate_rejected_is_none(tmp_path: Path):
    _touch(tmp_path / "config.yaml")
    _touch(tmp_path / "a" / "config.yaml")
    assert find_up(["config.yaml"], tmp_path / "a", stop=tmp_path, accept=lambda p: False) is None
