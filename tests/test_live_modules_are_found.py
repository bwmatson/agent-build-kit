"""The drift test finds every live-stack module under `tests/` by its syntax, at any depth."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.live_tag_drift import INTEGRATION, find_live_modules
from tests.runtime_tag_collection import ROOT

# One module per way a test is marked `local_stack`.
MARKS = {
    "pytestmark": (
        "import pytest\n\npytestmark = pytest.mark.local_stack\n\n\ndef test_x():\n    pass\n"
    ),
    "decorator": "import pytest\n\n\n@pytest.mark.local_stack\ndef test_x():\n    pass\n",
    "param": (
        "import pytest\n\n\n@pytest.mark.parametrize(\n"
        '    "n", [pytest.param(1, marks=pytest.mark.local_stack)]\n)\n'
        "def test_x(n):\n    pass\n"
    ),
    "class": (
        "import pytest\n\n\n@pytest.mark.local_stack\n"
        "class TestX:\n    def test_x(self):\n        pass\n"
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
def test_a_module_marked_local_stack_is_found_in_any_place_under_any_name(
    tmp_path: Path, mark: str, place: str
) -> None:
    path = write(tmp_path, place, MARKS[mark])
    write(tmp_path, "unit/test_plain.py", "def test_y():\n    pass\n")

    assert find_live_modules(tmp_path / "tests") == [path]


def test_a_word_in_a_string_or_a_comment_does_not_make_a_module_live(tmp_path: Path) -> None:
    write(tmp_path, "test_string.py", 'TEXT = "@pytest.mark.local_stack"\n')
    write(tmp_path, "test_comment.py", "# pytestmark = pytest.mark.local_stack\n")
    live = write(tmp_path, "integration/test_live.py", MARKS["pytestmark"])

    assert find_live_modules(tmp_path / "tests") == [live]


def test_a_module_that_cannot_be_parsed_is_named_in_a_failure(tmp_path: Path) -> None:
    write(tmp_path, "integration/test_broken.py", "def test_x(:\n    local_stack\n")

    with pytest.raises(pytest.fail.Exception, match="test_broken.py"):
        find_live_modules(tmp_path / "tests")


@pytest.mark.integration
def test_every_module_the_old_glob_and_text_match_found_is_still_found() -> None:
    old = [
        path
        for path in INTEGRATION.glob("test_*.py")
        if re.search(r"\blocal_stack\b", path.read_text())
    ]
    assert old

    found = find_live_modules(ROOT / "tests")

    assert set(old) <= set(found)
    assert found == sorted(found)
