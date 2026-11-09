"""The guard that a test with the `integration` selector can run in CI (spec: marker-taxonomy).

Each case writes synthetic test modules to a temporary folder and runs `check_tests` over it: each
cause is reported naming the test and what it needs, a conformant test passes, a test without the
selector is not looked at, and the baseline may only shrink. The last test runs the guard over the
kit.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.ci_runnable import check_tests, load_baseline, required_settings_fields

NONE: frozenset[str] = frozenset()
REQUIRED = {"Settings": frozenset({"api_token"})}


def tree(root: Path, files: dict[str, str]) -> Path:
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return root


def module(body: str, *, mark: str = "@pytest.mark.integration\n") -> str:
    """A test module whose one test runs `body`, with `mark` placed above the test."""
    return f"import os\n\nimport pytest\n\n\n{mark}def test_x():\n    {body}\n"


CAUSES = [
    ("Settings()", "api_token"),
    ('os.environ["TOKEN"]', "TOKEN"),
    ('os.environ.get("TOKEN")', "TOKEN"),
    ('os.getenv("TOKEN")', "TOKEN"),
    ("run_tick(scratch)", "run_tick"),
    ('fetch("https://example.org/api")', "example.org"),
]


@pytest.mark.parametrize(("body", "named"), CAUSES)
def test_an_integration_test_that_cannot_run_in_ci_is_reported_naming_the_test_and_the_cause(
    tmp_path: Path, body: str, named: str
) -> None:
    root = tree(tmp_path, {"pipeline/test_it.py": module(body)})

    problems = check_tests(root, baseline=NONE, required_fields=REQUIRED)

    assert len(problems) == 1
    assert "pipeline/test_it.py::test_x" in problems[0]
    assert named in problems[0]


CONFORMANT = [
    'Settings(api_token="x")',
    'os.environ.get("TOKEN", "default")',
    'os.getenv("TOKEN", "default")',
    'fetch("http://127.0.0.1:8000/api")',
    'fetch("http://localhost:8000/api")',
]


@pytest.mark.parametrize("body", CONFORMANT)
def test_a_conformant_integration_test_passes(tmp_path: Path, body: str) -> None:
    root = tree(tmp_path, {"test_it.py": module(body)})

    assert check_tests(root, baseline=NONE, required_fields=REQUIRED) == []


@pytest.mark.parametrize(("body", "named"), CAUSES)
def test_a_test_without_the_integration_selector_is_not_checked(
    tmp_path: Path, body: str, named: str
) -> None:
    root = tree(tmp_path, {"test_it.py": module(body, mark="")})

    assert check_tests(root, baseline=NONE, required_fields=REQUIRED) == []


def test_a_module_level_integration_mark_makes_the_test_checked(tmp_path: Path) -> None:
    source = (
        "import os\n\nimport pytest\n\npytestmark = pytest.mark.integration\n\n\n"
        'def test_x():\n    os.environ["TOKEN"]\n'
    )
    root = tree(tmp_path, {"test_it.py": source})

    problems = check_tests(root, baseline=NONE, required_fields=REQUIRED)

    assert len(problems) == 1
    assert "test_it.py::test_x" in problems[0]


def test_a_violator_named_in_the_baseline_passes(tmp_path: Path) -> None:
    root = tree(tmp_path, {"test_it.py": module('os.environ["TOKEN"]')})

    problems = check_tests(
        root, baseline=frozenset({"test_it.py::test_x"}), required_fields=REQUIRED
    )

    assert problems == []


def test_a_baseline_entry_that_is_no_longer_a_violator_is_reported_as_stale(
    tmp_path: Path,
) -> None:
    root = tree(tmp_path, {"test_it.py": module('Settings(api_token="x")')})

    problems = check_tests(
        root, baseline=frozenset({"test_it.py::test_x"}), required_fields=REQUIRED
    )

    assert len(problems) == 1
    assert "test_it.py::test_x" in problems[0]
    assert "stale" in problems[0]


@pytest.mark.integration
def test_no_integration_test_of_the_kit_needs_more_than_ci_has() -> None:
    problems = check_tests(baseline=load_baseline(), required_fields=required_settings_fields())

    assert problems == []
