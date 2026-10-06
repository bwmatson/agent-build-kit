"""Which check a failed tier 1 command was, as the python-uv profile reads it
from pre-commit's real output: `<hook name>....<result>` per hook, and under a
failed one `- hook id: <id>`, `- exit code: N`, a blank line, the tool's output."""

from __future__ import annotations

from agent_build_kit.pipeline.check_failures import failed_check

LINT_COMMAND = "$ uv run pre-commit run --from-ref main --to-ref HEAD (exit 1)"
DOTS = "." * 30

RUFF_FORMAT_PASSED = f"ruff format{DOTS}Passed"
RUFF_CHECK_FAILED = (
    f"ruff check{DOTS}Failed\n"
    "- hook id: ruff\n"
    "- exit code: 1\n"
    "\n"
    "src/app.py:1:8: F401 `os` imported but unused\n"
)
PYREFLY_PASSED = f"pyrefly check{DOTS}Passed"
PYREFLY_SKIPPED = f"pyrefly check{DOTS}(no files to check)Skipped"
PYREFLY_FAILED = (
    f"pyrefly check{DOTS}Failed\n"
    "- hook id: pyrefly-check\n"
    "- exit code: 1\n"
    "\n"
    "ERROR `None` is not assignable to `int` [bad-assignment]\n"
)
RENAMED_TYPE_CHECKER_FAILED = (
    f"Type check{DOTS}Failed\n- hook id: mypy\n- exit code: 1\n\nerror: Incompatible types\n"
)


def run(*results: str) -> str:
    return "\n".join([LINT_COMMAND, *results])


def test_a_failed_linter_hook_with_a_passing_type_checker_is_lint() -> None:
    assert failed_check(run(RUFF_FORMAT_PASSED, RUFF_CHECK_FAILED, PYREFLY_PASSED)) == "lint"


def test_a_failed_type_checker_hook_is_types() -> None:
    assert failed_check(run(RUFF_FORMAT_PASSED, PYREFLY_FAILED)) == "types"


def test_a_skipped_type_checker_does_not_make_a_lint_failure_types() -> None:
    assert failed_check(run(RUFF_FORMAT_PASSED, RUFF_CHECK_FAILED, PYREFLY_SKIPPED)) == "lint"


def test_a_failed_type_checker_is_found_by_its_id_not_its_name() -> None:
    assert failed_check(run(RUFF_FORMAT_PASSED, RENAMED_TYPE_CHECKER_FAILED)) == "types"


def test_a_failed_linter_and_a_failed_type_checker_is_types() -> None:
    assert failed_check(run(RUFF_CHECK_FAILED, PYREFLY_FAILED)) == "types"


def test_a_failed_pytest_command_is_test() -> None:
    output = (
        "$ uv run --package app --isolated pytest app -q (exit 1)\n"
        "FAILED tests/test_x.py::test_y - AssertionError\n"
        "pyrefly mentioned in a traceback"
    )
    assert failed_check(output) == "test"
