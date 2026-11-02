"""The two scratch live tests are named for what they drive, not for one runtime.

They run on every runtime, so `acp` is not in their names. A name that is found again,
in a file or as a module, means a reference was missed in the rename.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.time_limit import LOADED_TEST_TIME_LIMIT
from tests.tracked_files import ROOT, guarded_files

INTEGRATION = ROOT / "tests" / "integration"
# Built from parts so this file does not name what it looks for.
OLD_STEMS = ("test_" + "acp_build_unit", "test_graph_" + "acp_unit")
NEW_STEMS = ("test_build_unit", "test_graph_unit")
# The changelog keeps the history of released names.
EXEMPT = frozenset(["CHANGELOG.md"])


def tracked_files(root: Path = ROOT) -> list[Path]:
    return [path for path in guarded_files(root) if path.relative_to(root).as_posix() not in EXEMPT]


@pytest.mark.parametrize("stem", OLD_STEMS)
def test_an_old_module_name_is_gone(stem: str) -> None:
    assert not (INTEGRATION / f"{stem}.py").exists()


@pytest.mark.parametrize("stem", NEW_STEMS)
def test_a_new_module_name_exists(stem: str) -> None:
    assert (INTEGRATION / f"{stem}.py").is_file()


@pytest.mark.time_limit(LOADED_TEST_TIME_LIMIT)
def test_no_tracked_file_names_an_old_module() -> None:
    found: list[str] = []
    for path in tracked_files():
        if not path.is_file():
            continue
        try:
            text = path.read_text()
        except UnicodeDecodeError:
            continue
        found += [f"{path.relative_to(ROOT)}: {s}" for s in OLD_STEMS if s in text]
    assert found == []
