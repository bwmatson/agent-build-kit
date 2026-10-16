"""A test that forks a multi-threaded process fails, a pydantic serializer warning fails, and
every other warning is left as it was (spec: test-determinism, ci-runs-without-warnings). The
fork guard is the plugin `tests.fork_warning_guard`: CPython drops the exception a
`filterwarnings = error` entry would raise for that warning. The serializer guard is the
repository's own scoped `filterwarnings` entry, read from pyproject.toml and applied to a child
pytest."""

import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
OTHER_WARNING = "an unrelated deprecation"

FORKS_WHILE_THREADED = """
import os, threading

def test_forks():
    parked = threading.Event()
    keeper = threading.Thread(target=parked.wait, daemon=True)
    keeper.start()
    try:
        pid = os.fork()
        if pid == 0:
            os._exit(0)
        os.waitpid(pid, 0)
    finally:
        parked.set()
        keeper.join()
"""

SPAWNS_WHILE_THREADED = """
import multiprocessing, threading

def test_spawns():
    parked = threading.Event()
    keeper = threading.Thread(target=parked.wait, daemon=True)
    keeper.start()
    try:
        process = multiprocessing.get_context("spawn").Process(target=int)
        process.start()
        process.join(timeout=30)
        assert process.exitcode == 0
    finally:
        parked.set()
        keeper.join()
"""

OTHER_DEPRECATION = f"""
import warnings

def test_warns():
    warnings.warn({OTHER_WARNING!r}, DeprecationWarning)
"""


def run_with_the_guard(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> pytest.RunResult:
    monkeypatch.setenv("PYTHONPATH", str(ROOT))
    return pytester.runpytest_subprocess("-p", "tests.fork_warning_guard", "-p", "no:cacheprovider")


def test_the_repositorys_tests_run_with_the_guard(pytestconfig: pytest.Config) -> None:
    assert pytestconfig.pluginmanager.has_plugin("tests.fork_warning_guard")


def test_a_test_that_forks_while_another_thread_is_alive_fails_with_the_warning(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytester.makepyfile(test_forking=FORKS_WHILE_THREADED)

    result = run_with_the_guard(pytester, monkeypatch)

    result.assert_outcomes(failed=1)
    result.stdout.fnmatch_lines(["*multi-threaded, use of fork() may lead to deadlocks*"])


def test_a_test_that_spawns_while_another_thread_is_alive_passes(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytester.makepyfile(test_spawning=SPAWNS_WHILE_THREADED)

    result = run_with_the_guard(pytester, monkeypatch)

    result.assert_outcomes(passed=1)


def test_another_deprecation_warning_is_reported_and_does_not_fail(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytester.makepyfile(test_other=OTHER_DEPRECATION)

    result = run_with_the_guard(pytester, monkeypatch)

    result.assert_outcomes(passed=1, warnings=1)


SERIALIZES = """
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
