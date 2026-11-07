"""A failed test's id is read whole and reaches pytest as one argument (spec: test-rerun-ids)."""

from __future__ import annotations

import shlex
from typing import Any

from agent_build_kit.profiles.python_uv import PythonUvProfile

SPACED = "tests/a/test_x.py::test_y[no conversation found with session id sess-1]"
FILES = ["tests/a/test_x.py"]


def test_a_summary_names_a_parametrized_id_with_spaces_whole_and_leaves_the_reason_out() -> None:
    output = (
        "=========== short test summary info ===========\n"
        f"FAILED {SPACED} - AssertionError: no conversation\n"
        "FAILED tests/a/test_x.py::test_plain - AssertionError: no\n"
        f"ERROR {SPACED.replace('sess-1', 'sess-2')}\n"
        "ERROR tests/a/test_x.py::TestGroup::test_setup[a b] - RuntimeError: boom\n"
    )

    assert PythonUvProfile().failed_tests(output) == [
        SPACED,
        "tests/a/test_x.py::test_plain",
        SPACED.replace("sess-1", "sess-2"),
        "tests/a/test_x.py::TestGroup::test_setup[a b]",
    ]


def test_the_by_id_red_command_passes_an_id_with_spaces_and_brackets_as_one_argument() -> None:
    profile: Any = PythonUvProfile()

    command = profile.red_command(FILES, [SPACED])

    first, _, after = command.partition('if [ "$status" -eq 4 ]; then ')
    assert shlex.quote(SPACED) in first
    assert shlex.quote(SPACED) not in after, "the retry runs the files whole"
    assert after.startswith("uv run pytest tests/a/test_x.py -p no:cacheprovider")
