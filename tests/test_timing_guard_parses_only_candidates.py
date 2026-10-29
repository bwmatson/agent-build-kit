"""The timing guard parses only a file that could hold a hazard (spec: test-determinism).

The guard walks the whole test tree, and parsing every file of it under load can pass the
per-test time limit. A file that names none of what a hazard is made of cannot hold one, so
it is not parsed. Whether a file is parsed is observed without the clock: a file that does
not parse is a candidate for no hazard, and is read past instead of raising.
"""

from __future__ import annotations

from pathlib import Path

from tests.timing_hazards import check_tests

NONE: frozenset[str] = frozenset()

NOT_PYTHON = "def test_x(:\n    pass\n"


def test_a_file_naming_nothing_a_hazard_is_made_of_is_not_parsed(tmp_path: Path) -> None:
    (tmp_path / "test_plain.py").write_text(NOT_PYTHON)

    assert check_tests(tmp_path, allowlist=NONE, shared=NONE) == []


def test_such_a_file_does_not_hide_a_hazard_in_a_file_beside_it(tmp_path: Path) -> None:
    (tmp_path / "test_plain.py").write_text(NOT_PYTHON)
    (tmp_path / "test_slow.py").write_text("import time\n\n\ndef test_x():\n    time.sleep(1)\n")

    problems = check_tests(tmp_path, allowlist=NONE, shared=NONE)

    assert len(problems) == 1
    assert "test_slow.py:5" in problems[0]
