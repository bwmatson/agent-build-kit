"""The syntax guard that finds a whole-repository scan with no `integration` selector (spec:
wide-scans-are-integration).

Each case writes synthetic test modules to a temporary folder and runs `check_tests` over it: a
scan is reported by name, the same scan marked `integration` passes, a test over its own temporary
tree or a named folder is not a scan, and the baseline may only shrink. The marks and the lists of
the real repository are checked in `test_wide_scans_are_integration.py`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.wide_scans import check_tests

NONE: frozenset[str] = frozenset()


def tree(root: Path, files: dict[str, str]) -> Path:
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return root


def scan(call: str, *, mark: str = "") -> str:
    """A test module whose one test makes `call`, with `mark` placed above the test."""
    return f"import pytest\n\n\n{mark}def test_x():\n    {call}\n"


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
    "splits_by_syntax(ROOT / 'tests')",
    "[ast.parse(p.read_text()) for p in ROOT.rglob('*.py')]",
    "[p.read_text() for p in sorted(SOURCE_ROOT.rglob('*.py'))]",
    "[p for p in (ROOT / 'docs').glob('*.md')]",
    "[p for p in Path(__file__).parent.rglob('*.py')]",
    "[p for p in WORKFLOWS.glob('*.yml')]",
]


@pytest.mark.parametrize("call", WHOLE_TREE_CALLS)
def test_an_unmarked_scan_of_the_repository_is_reported_by_name(tmp_path: Path, call: str) -> None:
    root = tree(tmp_path, {"pipeline/test_scan.py": scan(call)})

    problems = check_tests(root, baseline=NONE)

    assert len(problems) == 1
    assert "pipeline/test_scan.py::test_x" in problems[0]


@pytest.mark.parametrize("call", WHOLE_TREE_CALLS)
def test_the_same_scan_marked_integration_on_the_test_passes(tmp_path: Path, call: str) -> None:
    root = tree(tmp_path, {"test_scan.py": scan(call, mark="@pytest.mark.integration\n")})

    assert check_tests(root, baseline=NONE) == []


def test_a_module_level_integration_mark_counts_as_marked(tmp_path: Path) -> None:
    source = (
        "import pytest\n\npytestmark = pytest.mark.integration\n\n\n"
        "def test_x():\n    leaks(ROOT)\n"
    )
    root = tree(tmp_path, {"test_scan.py": source})

    assert check_tests(root, baseline=NONE) == []


def test_a_class_level_integration_mark_counts_as_marked(tmp_path: Path) -> None:
    source = (
        "import pytest\n\n\n@pytest.mark.integration\nclass TestScan:\n"
        "    def test_x(self):\n        leaks(ROOT)\n"
    )
    root = tree(tmp_path, {"test_scan.py": source})

    assert check_tests(root, baseline=NONE) == []


@pytest.mark.parametrize(
    "source",
    [
        "def test_x(tmp_path):\n    leaks(tmp_path)\n",
        "def test_x(tmp_path):\n    root = tmp_path / 'plan'\n    guarded_files(root)\n",
        (
            "def test_x(tmp_path):\n    root = tmp_path / 'plan'\n"
            "    again = root / 'x'\n    hits(again, rule)\n"
        ),
        "def test_x(tmp_path):\n    [ast.parse(p.read_text()) for p in tmp_path.rglob('*.py')]\n",
        "def test_x(tmp_path):\n    [p.read_text() for p in (tmp_path / 'a').glob('*.md')]\n",
        "def test_x(tmp_path):\n    find_live_modules(tmp_path / 'tests')\n",
        "def test_x():\n    repo = make_repo()\n    [p for p in repo.glob('work-*.txt')]\n",
        "def test_x(inst):\n    sorted(inst.changes_dir.rglob('*'))\n",
        "def test_x():\n    guarded_files(ROOT, under=['tests/child_modules'])\n",
        "def test_x():\n    ast.parse('x = 1')\n",
    ],
    ids=[
        "tmp_path",
        "derived",
        "derived twice",
        "tmp_path tree walked",
        "tmp_path glob",
        "tmp_path module scan",
        "a folder the test made",
        "a fixture's folder",
        "a named folder",
        "a literal",
    ],
)
def test_a_test_that_works_over_its_own_temporary_tree_or_a_folder_is_not_a_scan(
    tmp_path: Path, source: str
) -> None:
    root = tree(tmp_path, {"test_logic.py": source})

    assert check_tests(root, baseline=NONE) == []


HELPER = "def walk():\n    return list(ROOT.rglob('*.py'))\n\n\n"


def test_a_test_that_calls_a_helper_of_its_module_that_scans_is_a_scan(tmp_path: Path) -> None:
    root = tree(tmp_path, {"test_scan.py": HELPER + "def test_x():\n    walk()\n"})

    problems = check_tests(root, baseline=NONE)

    assert len(problems) == 1 and "test_scan.py::test_x" in problems[0]


def test_a_helper_that_scans_through_another_helper_still_makes_its_caller_a_scan(
    tmp_path: Path,
) -> None:
    source = (
        HELPER
        + "def names():\n    return [p.name for p in walk()]\n\n\ndef test_x():\n    names()\n"
    )
    root = tree(tmp_path, {"test_scan.py": source})

    assert [p.split(": ")[0] for p in check_tests(root, baseline=NONE)] == ["test_scan.py::test_x"]


def test_a_scan_helper_that_no_test_calls_reports_nothing(tmp_path: Path) -> None:
    root = tree(tmp_path, {"test_scan.py": HELPER + "def test_x():\n    pass\n"})

    assert check_tests(root, baseline=NONE) == []


def test_a_marked_test_that_calls_a_scan_helper_passes(tmp_path: Path) -> None:
    source = HELPER + "@pytest.mark.integration\ndef test_x():\n    walk()\n"
    root = tree(tmp_path, {"test_scan.py": "import pytest\n\n\n" + source})

    assert check_tests(root, baseline=NONE) == []


def test_a_helper_that_works_over_the_path_it_is_given_is_not_a_scan(tmp_path: Path) -> None:
    source = (
        "def walk(root):\n    return list(root.rglob('*.py'))\n\n\n"
        "def test_x(tmp_path):\n    walk(tmp_path)\n"
    )
    root = tree(tmp_path, {"test_logic.py": source})

    assert check_tests(root, baseline=NONE) == []


def test_a_scan_in_the_baseline_is_not_reported_and_one_missing_from_it_is(
    tmp_path: Path,
) -> None:
    root = tree(
        tmp_path,
        {"test_old.py": scan("leaks(ROOT)"), "test_new.py": scan("home_path_leaks(ROOT)")},
    )

    problems = check_tests(root, baseline=frozenset({"test_old.py::test_x"}))

    assert len(problems) == 1
    assert "test_new.py::test_x" in problems[0]


@pytest.mark.parametrize(
    "files",
    [
        {"test_old.py": scan("leaks(ROOT)", mark="@pytest.mark.integration\n")},
        {"test_old.py": "def test_x(tmp_path):\n    leaks(tmp_path)\n"},
        {},
    ],
    ids=["now marked", "no longer a scan", "file gone"],
)
def test_a_baseline_entry_that_is_no_longer_an_unmarked_scan_is_reported_as_stale(
    tmp_path: Path, files: dict[str, str]
) -> None:
    root = tree(tmp_path, files)

    problems = check_tests(root, baseline=frozenset({"test_old.py::test_x"}))

    assert len(problems) == 1
    assert "stale" in problems[0] and "test_old.py::test_x" in problems[0]


def test_a_syntax_error_in_a_test_file_is_named_not_raised(tmp_path: Path) -> None:
    root = tree(tmp_path, {"test_broken.py": "def test_x(:\n    leaks(ROOT)\n"})

    problems = check_tests(root, baseline=NONE)

    assert len(problems) == 1 and "test_broken.py" in problems[0]


def scan_fixture_module(root: str) -> str:
    """A module whose `scan` fixture builds a `Scan` over `root` and whose one test takes it."""
    return (
        "import pytest\n\n\n@pytest.fixture\ndef scan(tmp_path):\n"
        f"    return Scan({root})\n\n\ndef test_x(scan):\n    scan.hits(rule)\n"
    )


def test_a_test_that_takes_a_scan_fixture_of_the_repository_is_a_scan(tmp_path: Path) -> None:
    root = tree(tmp_path, {"test_scan.py": scan_fixture_module("ROOT")})

    problems = check_tests(root, baseline=NONE)

    assert len(problems) == 1 and "test_scan.py::test_x" in problems[0]


def test_a_test_that_takes_a_scan_fixture_of_its_own_temporary_tree_is_not_a_scan(
    tmp_path: Path,
) -> None:
    root = tree(tmp_path, {"test_scan.py": scan_fixture_module("tmp_path")})

    assert check_tests(root, baseline=NONE) == []
