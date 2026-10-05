"""Which check a failed tier 1 command was, as the python-uv profile reads it
from the pre-commit run's per-hook lines and the `$ command` header."""

from __future__ import annotations

from agent_build_kit.pipeline.check_failures import failed_check

LINT_COMMAND = "$ uv run pre-commit run --from-ref main --to-ref HEAD (exit 1)"


def hooks(**results: str) -> str:
    lines = [f"{hook.replace('_', '-')}{'.' * 40}{result}" for hook, result in results.items()]
    return "\n".join([LINT_COMMAND, *lines])


def test_a_failed_linter_hook_with_a_passing_type_checker_is_lint() -> None:
    output = hooks(ruff="Failed", ruff_format="Passed", pyrefly_check="Passed")
    assert failed_check(output) == "lint"


def test_a_failed_type_checker_hook_is_types() -> None:
    output = hooks(ruff="Passed", pyrefly_check="Failed")
    assert failed_check(output) == "types"


def test_a_skipped_type_checker_does_not_make_a_lint_failure_types() -> None:
    output = hooks(ruff="Failed", pyrefly_check="(no files to check)Skipped")
    assert failed_check(output) == "lint"


def test_a_failed_pytest_command_is_test() -> None:
    output = (
        "$ uv run --package app --isolated pytest app -q (exit 1)\n"
        "FAILED tests/test_x.py::test_y - AssertionError\n"
        "pyrefly mentioned in a traceback"
    )
    assert failed_check(output) == "test"
