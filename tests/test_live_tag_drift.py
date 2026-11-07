"""The drift test finds every live-stack module under `tests/` by its syntax, at any depth.

The scan gives the same answer whatever else touches `tests/` while it runs: a file listed and gone
by the time it is read is not a module, and not an error.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.live_tag_drift import INTEGRATION, find_live_modules
from tests.runtime_tag_collection import ROOT

# One module per way a test is marked `e2e`.
MARKS = {
    "pytestmark": ("import pytest\n\npytestmark = pytest.mark.e2e\n\n\ndef test_x():\n    pass\n"),
    "decorator": "import pytest\n\n\n@pytest.mark.e2e\ndef test_x():\n    pass\n",
    "param": (
        "import pytest\n\n\n@pytest.mark.parametrize(\n"
        '    "n", [pytest.param(1, marks=pytest.mark.e2e)]\n)\n'
        "def test_x(n):\n    pass\n"
    ),
    "class": (
        "import pytest\n\n\n@pytest.mark.e2e\nclass TestX:\n    def test_x(self):\n        pass\n"
    ),
}
PLACES = ["integration/runtimes/test_x.py", "integration/replay_unit_x.py"]


def write(root: Path, relative: str, text: str) -> Path:
    path = root / "tests" / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


@pytest.mark.parametrize("mark", MARKS)
@pytest.mark.parametrize("place", PLACES)
def test_a_module_marked_e2e_is_found_in_any_place_under_any_name(
    tmp_path: Path, mark: str, place: str
) -> None:
    path = write(tmp_path, place, MARKS[mark])
    write(tmp_path, "unit/test_plain.py", "def test_y():\n    pass\n")

    assert find_live_modules(tmp_path / "tests") == [path]


def test_a_word_in_a_string_or_a_comment_does_not_make_a_module_live(tmp_path: Path) -> None:
    write(tmp_path, "test_string.py", 'TEXT = "@pytest.mark.e2e"\n')
    write(tmp_path, "test_comment.py", "# pytestmark = pytest.mark.e2e\n")
    live = write(tmp_path, "integration/test_live.py", MARKS["pytestmark"])

    assert find_live_modules(tmp_path / "tests") == [live]


def test_a_module_that_cannot_be_parsed_is_named_in_a_failure(tmp_path: Path) -> None:
    write(tmp_path, "integration/test_broken.py", "def test_x(:\n    e2e\n")

    with pytest.raises(pytest.fail.Exception, match="test_broken.py"):
        find_live_modules(tmp_path / "tests")


def test_a_file_listed_and_gone_before_it_is_read_is_skipped(tmp_path: Path) -> None:
    live = tmp_path / "tests" / "integration" / "test_live.py"
    live.parent.mkdir(parents=True)
    live.write_text(MARKS["pytestmark"])
    # A link to a file that was removed: the directory still lists it, reading it fails, which
    # is what another test deleting a file during the scan looks like, with no clock involved.
    (tmp_path / "tests" / "test_vanished.py").symlink_to(tmp_path / "removed.py")

    assert find_live_modules(tmp_path / "tests") == [live]


@pytest.mark.integration
def test_every_module_the_old_glob_and_text_match_found_is_still_found() -> None:
    old = [
        path for path in INTEGRATION.glob("test_*.py") if re.search(r"\be2e\b", path.read_text())
    ]
    assert old

    found = find_live_modules(ROOT / "tests")

    assert set(old) <= set(found)
    assert found == sorted(found)
