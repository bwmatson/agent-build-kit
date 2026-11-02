"""A test module does not walk the checkout by hand (spec: repo-wide-guards).

The detection is `tests/hand_walks.py`; this file tests it against synthetic modules and runs
it over the real `tests/` tree.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.hand_walks import hand_walks
from tests.time_limit import LOADED_TEST_TIME_LIMIT

TESTS = Path(__file__).resolve().parent
# Modules that walk only `src/` or `tests/`, or only name the calls, each with its reason.
UNLISTED_WALKS = {
    "test_atomic_write_guard.py": "walks src/ only",
    "test_secret_leak_guards.py": "walks src/ and tests/ only",
    "test_one_definition_per_pattern.py": "walks src/ and tests/ only",
    "test_record_metric_guard.py": "walks src/ only",
    "test_verdict_readers_guard.py": "walks src/ only",
    "test_test_helpers_defined_once.py": "walks tests/ only",
    "timing_hazards.py": "walks tests/ only",
    "tracked_files.py": "is the helper",
    "attach_driver.py": "lists the changes in a scratch repository",
    "test_chat_editing_claude_code.py": "lists the changes in a scratch repository",
    "test_planning_in_repo_live_stack.py": "reads the index of a scratch repository",
    "test_work_graph.py": "lists the changes in a scratch repository",
    "test_openspec_cli_users.py": "globs tests/fixtures only",
    "hand_walks.py": "names the calls it looks for",
    "test_repo_wide_guards_use_the_helper.py": "names the calls it looks for",
}


def test_a_module_that_globs_the_root_is_named_by_line() -> None:
    source = (
        "from pathlib import Path\n"
        "\n"
        "ROOT = Path(__file__).parents[1]\n"
        "\n"
        "files = ROOT.rglob('*.md')\n"
    )

    assert hand_walks(source) == [5]


def test_ls_files_and_a_glob_on_a_name_bound_from_file_are_named() -> None:
    source = (
        "import subprocess\n"
        "from pathlib import Path\n"
        "BASE = Path(__file__).resolve().parents[2]\n"
        "out = subprocess.run(['git', 'ls-files'])\n"
        "docs = BASE.glob('*.md')\n"
    )

    assert hand_walks(source) == [4, 5]


def test_a_module_that_imports_the_helper_passes() -> None:
    source = (
        "from tests.tracked_files import guarded_files\n"
        "ROOT = Path(__file__).parents[1]\n"
        "ROOT.rglob('*.md')\n"
    )

    assert hand_walks(source) == []


def test_a_call_on_a_temporary_path_passes() -> None:
    source = "def f(tmp_path):\n    return list(tmp_path.rglob('*.md'))\n"

    assert hand_walks(source) == []


@pytest.mark.time_limit(LOADED_TEST_TIME_LIMIT)
def test_no_test_module_walks_the_checkout_by_hand() -> None:
    problems = [
        f"{path.relative_to(TESTS.parent)}:{line}"
        for path in sorted(TESTS.rglob("*.py"))
        if path.name not in UNLISTED_WALKS
        for line in hand_walks(path.read_text())
    ]

    assert not problems, "read the files through tests/tracked_files.py:\n" + "\n".join(problems)
