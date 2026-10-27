"""A new test module does not build a child pytest's source as a string
(spec: a new test module does not build a child pytest's source as a string)."""

from __future__ import annotations

from pathlib import Path

from tests.child_sources import ALLOWED, check_tests, source_hits
from tests.tracked_files import ROOT, guarded_files

STRING_RUN = '''\
def test_runs_a_string(pytester):
    pytester.makepyfile("""
        def test_x():
            assert True
    """)
    pytester.runpytest_subprocess()
'''

FIXTURE_RUN = '''\
SOURCE = """
import pytest

@pytest.fixture
def thing():
    return 1
"""


def test_it():
    run_child(SOURCE)
'''

ONLY_PARSED = '''\
import ast

SOURCE = """
def test_x():
    pass
"""


def test_it():
    ast.parse(SOURCE)
'''

COPIES_EXAMPLE = """\
def test_it(pytester):
    pytester.copy_example("marked_time_limit")
    pytester.runpytest_subprocess("blocks.py")
"""


def write_module(folder: Path, relative: str, text: str) -> Path:
    module = folder / relative
    module.parent.mkdir(parents=True, exist_ok=True)
    module.write_text(text)
    return module


def test_a_string_with_a_test_given_to_makepyfile_and_run_gives_its_line() -> None:
    assert source_hits(STRING_RUN) == [2]


def test_a_string_with_a_fixture_and_a_run_child_call_gives_its_line() -> None:
    assert source_hits(FIXTURE_RUN) == [1]


def test_a_string_with_a_test_only_given_to_ast_parse_gives_none() -> None:
    assert source_hits(ONLY_PARSED) == []


def test_a_module_that_copies_an_example_and_holds_no_such_string_gives_none() -> None:
    assert source_hits(COPIES_EXAMPLE) == []


def test_a_hit_in_a_module_not_allowed_names_the_module_and_line(tmp_path: Path) -> None:
    module = write_module(tmp_path, "tests/test_new.py", STRING_RUN)

    problems = check_tests([module], allowed={}, root=tmp_path)

    assert problems == ["tests/test_new.py:2"]


def test_an_allowed_module_with_no_hit_is_reported_as_a_stale_entry(tmp_path: Path) -> None:
    module = write_module(tmp_path, "tests/test_old.py", COPIES_EXAMPLE)

    problems = check_tests([module], allowed={"tests/test_old.py": "migrate"}, root=tmp_path)

    assert len(problems) == 1
    assert "tests/test_old.py" in problems[0] and "stale" in problems[0]


def test_an_allowed_module_with_a_hit_passes(tmp_path: Path) -> None:
    module = write_module(tmp_path, "tests/test_old.py", STRING_RUN)

    assert check_tests([module], allowed={"tests/test_old.py": "migrate"}, root=tmp_path) == []


def test_a_module_under_child_modules_with_a_test_string_is_exempt(tmp_path: Path) -> None:
    module = write_module(tmp_path, "tests/child_modules/scenario/helper.py", STRING_RUN)

    assert check_tests([module], allowed={}, root=tmp_path) == []


def test_the_repository_has_no_unlisted_or_stale_module() -> None:
    files = guarded_files(ROOT, under=["tests"], suffixes={".py"})

    assert check_tests(files) == []


def test_the_migrated_time_limit_modules_are_not_allowed() -> None:
    assert "tests/test_marked_time_limit.py" not in ALLOWED
    assert "tests/test_e2e_time_limit.py" not in ALLOWED
