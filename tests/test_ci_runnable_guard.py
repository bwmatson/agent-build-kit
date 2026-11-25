"""The specification of what the CI-runnable guard flags (spec: marker-taxonomy).

One table: each row is a test module's source text, the baseline and the expected report, run
through `check_tests` over a temporary folder. Each cause is reported naming the test and what it
needs, a conformant test passes, a test without the `integration` selector is not looked at, and
the baseline may only shrink. The last test runs the guard over the kit and asserts it read some
`integration` tests.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tests.ci_runnable import check_tests, load_baseline, required_settings_fields
from tests.time_limit import LOADED_TEST_TIME_LIMIT
from tests.tracked_files import test_trees
from tests.wide_scans import walk_test_modules, walk_tests

NONE: frozenset[str] = frozenset()
REQUIRED = {"Settings": frozenset({"api_token"})}
ENTRY = "pipeline/test_it.py::test_x"


def module(body: str, *, mark: str = "@pytest.mark.integration\n") -> str:
    """A test module whose one test runs `body`, with `mark` placed above the test."""
    return (
        "import os\nimport shutil\n\nimport pytest\n\nfrom tests.scratch_tick import run_tick\n\n\n"
        f"{mark}def test_x():\n    {body}\n"
    )


CAUSES = [
    ("Settings()", "api_token"),
    ('os.environ["TOKEN"]', "TOKEN"),
    ('os.environ.get("TOKEN")', "TOKEN"),
    ('os.getenv("TOKEN")', "TOKEN"),
    ("run_tick(scratch)", "starts a real agent"),
    ('shutil.which("claude")', "starts a real agent"),
    ('fetch("https://api.github.com/repos")', "api.github.com"),
]
CONFORMANT = [
    'Settings(api_token="x")',
    'os.environ.get("TOKEN", "default")',
    'os.getenv("TOKEN", "default")',
    'fetch("http://127.0.0.1:8000/api")',
    'fetch("http://localhost:8000/api")',
    'Card(link="https://boards.example/items/42")',
    'fetch("https://example.org/api")',
    "drive = lambda: None; drive()",
    '"""https://api.github.com/docs"""',
]
FIXTURE_CAUSE = (
    "import os\n\nimport pytest\n\n\n"
    '@pytest.fixture\ndef token():\n    return os.environ["TOKEN"]\n\n\n'
    "@pytest.mark.integration\ndef test_x(token):\n    assert token\n"
)
DEEP_CAUSE = (
    "import os\n\nimport pytest\n\n\n"
    '@pytest.fixture\ndef b():\n    return os.environ["TOKEN"]\n\n\n'
    "@pytest.fixture\ndef a(b):\n    return b\n\n\n"
    "@pytest.mark.integration\ndef test_x(a):\n    assert a\n"
)
AGENT_NAMED_HELPER = (
    "import pytest\n\n\ndef drive():\n    pass\n\n\n"
    "@pytest.mark.integration\ndef test_x():\n    drive()\n"
)
MODULE_MARKED = (
    "import os\n\nimport pytest\n\npytestmark = pytest.mark.integration\n\n\n"
    'def test_x():\n    os.environ["TOKEN"]\n'
)

# (path of the module, its source, baseline, expected); expected is a list of reasons the one
# problem's message names, or empty when nothing is reported.
Row = tuple[str, str, frozenset[str], list[str]]
ROWS: dict[str, Row] = {}
for _body, _named in CAUSES:
    ROWS[f"an integration test that does {_body} is reported naming the test and {_named}"] = (
        "pipeline/test_it.py",
        module(_body),
        NONE,
        [ENTRY, _named],
    )
    ROWS[f"a test without the integration selector that does {_body} is not checked"] = (
        "test_it.py",
        module(_body, mark=""),
        NONE,
        [],
    )
for _body in CONFORMANT:
    ROWS[f"a conformant integration test that does {_body} passes"] = (
        "test_it.py",
        module(_body),
        NONE,
        [],
    )
ROWS.update(
    {
        "a cause in a fixture of the same module is reported for the test": (
            "test_it.py",
            FIXTURE_CAUSE,
            NONE,
            ["test_it.py::test_x", "TOKEN"],
        ),
        "a cause two fixtures deep is reported for the test": (
            "test_it.py",
            DEEP_CAUSE,
            NONE,
            ["TOKEN"],
        ),
        "a module helper named like an agent signal is not an agent start": (
            "test_it.py",
            AGENT_NAMED_HELPER,
            NONE,
            [],
        ),
        "a module-level integration mark makes the test checked": (
            "test_it.py",
            MODULE_MARKED,
            NONE,
            ["test_it.py::test_x"],
        ),
        "a violator named in the baseline passes": (
            "test_it.py",
            module('os.environ["TOKEN"]'),
            frozenset({"test_it.py::test_x"}),
            [],
        ),
        "a baseline entry that is no longer a violator is reported as stale": (
            "test_it.py",
            module('Settings(api_token="x")'),
            frozenset({"test_it.py::test_x"}),
            ["test_it.py::test_x", "stale"],
        ),
    }
)


@pytest.mark.parametrize("row", ROWS, ids=list(ROWS))
def test_the_guard_reports_what_the_row_expects(tmp_path: Path, row: str) -> None:
    name, source, baseline, expected = ROWS[row]
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source)

    problems = check_tests(tmp_path, baseline=baseline, required_fields=REQUIRED)

    assert len(problems) == (1 if expected else 0)
    assert all(reason in problems[0] for reason in expected)


@pytest.mark.time_limit(LOADED_TEST_TIME_LIMIT)
@pytest.mark.integration
def test_no_integration_test_of_the_kit_needs_more_than_ci_has() -> None:
    integration = [
        node
        for _, path in walk_test_modules(test_trees())
        for node, marked in walk_tests(ast.parse(path.read_text()))
        if marked
    ]

    assert len(integration) > 0
    problems = check_tests(baseline=load_baseline(), required_fields=required_settings_fields())
    assert problems == []
