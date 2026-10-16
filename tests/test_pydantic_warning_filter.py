"""A pydantic serializer warning fails a test, and every other `UserWarning` is only reported
(spec: ci-runs-without-warnings). The entry is the repository's own, read from pyproject.toml
and applied to a child pytest."""

import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

SERIALIZES = """
import warnings
from pydantic import BaseModel

class Holder(BaseModel):
    values: tuple[int, ...] = ()

def test_dumps_{kind}():
    holder = Holder.model_construct(values={value})
    holder.model_dump()
"""

OTHER_USER_WARNING = """
import warnings

def test_warns():
    warnings.warn("an unrelated user warning", UserWarning)
"""


def pydantic_entry() -> str:
    options = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["pytest"]["ini_options"]
    entries = [e for e in options.get("filterwarnings", []) if "Pydantic serializer warnings" in e]
    assert len(entries) == 1, (
        "pyproject.toml has one filterwarnings entry for the serializer warning"
    )
    return entries[0]


def run_with_entry(pytester: pytest.Pytester) -> pytest.RunResult:
    return pytester.runpytest_subprocess(
        "-o", f"filterwarnings={pydantic_entry()}", "-p", "no:cacheprovider"
    )


def test_the_entry_turns_the_serializer_warning_into_an_error_scoped_by_its_message() -> None:
    action, message, category, *_ = pydantic_entry().split(":")

    assert action == "error"
    assert "Pydantic serializer warnings" in message
    assert category == "UserWarning"


def test_a_test_that_serialises_a_list_in_a_tuple_field_fails(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(test_list=SERIALIZES.format(kind="list", value="[1]"))

    result = run_with_entry(pytester)

    result.assert_outcomes(failed=1)
    result.stdout.fnmatch_lines(["*Pydantic serializer warnings*"])


def test_a_test_that_serialises_a_tuple_in_a_tuple_field_passes(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(test_tuple=SERIALIZES.format(kind="tuple", value="(1,)"))

    result = run_with_entry(pytester)

    result.assert_outcomes(passed=1)


def test_any_other_user_warning_is_reported_and_does_not_fail(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(test_other=OTHER_USER_WARNING)

    result = run_with_entry(pytester)

    result.assert_outcomes(passed=1, warnings=1)
