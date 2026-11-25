"""The specification of what the wide-scan detector flags (spec: integration-scans).

One table: each row is the test modules written to a temporary folder (name to source text), the
baseline and the expected report, run through `check_tests`. An unmarked scan is reported by name,
the same scan marked `integration` passes, a test over its own temporary tree or a named folder is
not a scan, and the baseline may only shrink. The marks and the baseline of the real repository
are checked in `test_wide_scans_are_integration.py`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.wide_scans import check_tests

NONE: frozenset[str] = frozenset()
MARK = "@pytest.mark.integration\n"
NOT_MARKED = "not marked integration"
STALE = "stale baseline entry"
UNPARSED = "cannot be parsed"


def scan(call: str, *, mark: str = "") -> str:
    """A test module whose one test makes `call`, with `mark` placed above the test."""
    return f"import pytest\n\n\n{mark}def test_x():\n    {call}\n"


def scan_fixture_module(root: str) -> str:
    """A module whose `scan` fixture builds a `Scan` over `root` and whose one test takes it."""
    return (
        "import pytest\n\n\n@pytest.fixture\ndef scan(tmp_path):\n"
        f"    return Scan({root})\n\n\ndef test_x(scan):\n    scan.hits(rule)\n"
    )


WHOLE_TREE_CALLS = [
    "guarded_files()",
    "guarded_files(ROOT)",
    "guarded_files(ROOT, suffixes=['.md'])",
    "hits(ROOT, rule)",
    "files(ROOT)",
    "leaks(ROOT)",
    "home_path_leaks(ROOT)",
    "repo_path_leaks(ROOT)",
    "find_live_modules(ROOT / 'tests')",
    "check_sources(SRC_ROOT, allowlist={})",
    "check_source_trees()",
    "[p for _, p in source_files()]",
    "splits_by_syntax(ROOT / 'tests')",
    "[ast.parse(p.read_text()) for p in ROOT.rglob('*.py')]",
    "[p.read_text() for p in sorted(SOURCE_ROOT.rglob('*.py'))]",
    "[p for p in (ROOT / 'docs').glob('*.md')]",
    "[p for p in Path(__file__).parent.rglob('*.py')]",
    "[p for p in WORKFLOWS.glob('*.yml')]",
]

OWN_TREE_OR_FOLDER = {
    "tmp_path": "def test_x(tmp_path):\n    leaks(tmp_path)\n",
    "derived": "def test_x(tmp_path):\n    root = tmp_path / 'plan'\n    guarded_files(root)\n",
    "derived twice": (
        "def test_x(tmp_path):\n    root = tmp_path / 'plan'\n"
        "    again = root / 'x'\n    hits(again, rule)\n"
    ),
    "tmp_path tree walked": (
        "def test_x(tmp_path):\n    [ast.parse(p.read_text()) for p in tmp_path.rglob('*.py')]\n"
    ),
    "tmp_path glob": (
        "def test_x(tmp_path):\n    [p.read_text() for p in (tmp_path / 'a').glob('*.md')]\n"
    ),
    "tmp_path module scan": "def test_x(tmp_path):\n    find_live_modules(tmp_path / 'tests')\n",
    "a folder the test made": (
        "def test_x():\n    repo = make_repo()\n    [p for p in repo.glob('work-*.txt')]\n"
    ),
    "a fixture's folder": "def test_x(inst):\n    sorted(inst.changes_dir.rglob('*'))\n",
    "a named folder": "def test_x():\n    guarded_files(ROOT, under=['tests/child_modules'])\n",
    "a literal": "def test_x():\n    ast.parse('x = 1')\n",
}

HELPER = "def walk():\n    return list(ROOT.rglob('*.py'))\n\n\n"
NAMES_HELPER = "def names():\n    return [p.name for p in walk()]\n\n\n"

# (files, baseline, expected); expected is a list of (entry, reason found in its message).
# A row with `whole_repository` runs the check over the test trees of the temporary repository.
ROWS: dict[str, tuple[dict[str, str], frozenset[str], list[tuple[str, str]]]] = {
    "an unmarked scan in a package test tree is reported relative to the repository": (
        {
            "tests/test_a.py": "def test_x():\n    pass\n",
            "packages/pkg/tests/graph/test_scan.py": scan("guarded_files()"),
        },
        NONE,
        [("packages/pkg/tests/graph/test_scan.py::test_x", NOT_MARKED)],
    ),
    "a module-level integration mark counts as marked": (
        {
            "test_scan.py": (
                "import pytest\n\npytestmark = pytest.mark.integration\n\n\n"
                "def test_x():\n    leaks(ROOT)\n"
            )
        },
        NONE,
        [],
    ),
    "a class-level integration mark counts as marked": (
        {
            "test_scan.py": (
                "import pytest\n\n\n@pytest.mark.integration\nclass TestScan:\n"
                "    def test_x(self):\n        leaks(ROOT)\n"
            )
        },
        NONE,
        [],
    ),
    "a test that calls a helper of its module that scans is a scan": (
        {"test_scan.py": HELPER + "def test_x():\n    walk()\n"},
        NONE,
        [("test_scan.py::test_x", NOT_MARKED)],
    ),
    "a helper that scans through another helper makes its caller a scan": (
        {"test_scan.py": HELPER + NAMES_HELPER + "def test_x():\n    names()\n"},
        NONE,
        [("test_scan.py::test_x", NOT_MARKED)],
    ),
    "a scan helper that no test calls reports nothing": (
        {"test_scan.py": HELPER + "def test_x():\n    pass\n"},
        NONE,
        [],
    ),
    "a marked test that calls a scan helper passes": (
        {
            "test_scan.py": (
                "import pytest\n\n\n" + HELPER + "@pytest.mark.integration\n"
                "def test_x():\n    walk()\n"
            )
        },
        NONE,
        [],
    ),
    "a helper that works over the path it is given is not a scan": (
        {
            "test_logic.py": (
                "def walk(root):\n    return list(root.rglob('*.py'))\n\n\n"
                "def test_x(tmp_path):\n    walk(tmp_path)\n"
            )
        },
        NONE,
        [],
    ),
    "a scan in the baseline is not reported and one missing from it is": (
        {"test_old.py": scan("leaks(ROOT)"), "test_new.py": scan("home_path_leaks(ROOT)")},
        frozenset({"test_old.py::test_x"}),
        [("test_new.py::test_x", NOT_MARKED)],
    ),
    "a baseline entry that is now marked is stale": (
        {"test_old.py": scan("leaks(ROOT)", mark=MARK)},
        frozenset({"test_old.py::test_x"}),
        [("test_old.py::test_x", STALE)],
    ),
    "a baseline entry that is no longer a scan is stale": (
        {"test_old.py": "def test_x(tmp_path):\n    leaks(tmp_path)\n"},
        frozenset({"test_old.py::test_x"}),
        [("test_old.py::test_x", STALE)],
    ),
    "a baseline entry whose file is gone is stale": (
        {},
        frozenset({"test_old.py::test_x"}),
        [("test_old.py::test_x", STALE)],
    ),
    "a syntax error in a test file is named, not raised": (
        {"test_broken.py": "def test_x(:\n    leaks(ROOT)\n"},
        NONE,
        [("test_broken.py", UNPARSED)],
    ),
    "a test that takes a scan fixture of the repository is a scan": (
        {"test_scan.py": scan_fixture_module("ROOT")},
        NONE,
        [("test_scan.py::test_x", NOT_MARKED)],
    ),
    "a test that takes a scan fixture of its own temporary tree is not a scan": (
        {"test_scan.py": scan_fixture_module("tmp_path")},
        NONE,
        [],
    ),
}
for _call in WHOLE_TREE_CALLS:
    ROWS[f"an unmarked scan {_call} is reported by name"] = (
        {"pipeline/test_scan.py": scan(_call)},
        NONE,
        [("pipeline/test_scan.py::test_x", NOT_MARKED)],
    )
    ROWS[f"the same scan {_call} marked integration passes"] = (
        {"test_scan.py": scan(_call, mark=MARK)},
        NONE,
        [],
    )
for _name, _source in OWN_TREE_OR_FOLDER.items():
    ROWS[f"a test over {_name} is not a scan"] = ({"test_logic.py": _source}, NONE, [])

WHOLE_REPOSITORY = {
    "an unmarked scan in a package test tree is reported relative to the repository"
}


@pytest.mark.parametrize("row", ROWS, ids=list(ROWS))
def test_the_detector_reports_what_the_row_expects(tmp_path: Path, row: str) -> None:
    files, baseline, expected = ROWS[row]
    for name, text in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    if row in WHOLE_REPOSITORY:
        problems = check_tests(baseline=baseline, repository=tmp_path)
    else:
        problems = check_tests(tmp_path, baseline=baseline)

    assert len(problems) == len(expected)
    for problem, (entry, reason) in zip(problems, expected, strict=True):
        assert problem.startswith(entry)
        assert reason in problem
