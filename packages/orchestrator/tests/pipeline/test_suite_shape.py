"""The five figures of a repository's tests, over temporary git repositories built here.

Commits carry fixed dates, and the report's clock and window start are given, so no case
depends on the day it runs.
"""

from __future__ import annotations

import os
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from agent_build_kit.config import ProjectConfig
from agent_build_kit.pipeline.run_log import TestRun, append_test_run, run_ledger_path
from agent_build_kit.pipeline.shell import git
from agent_build_kit.pipeline.suite_shape import ShapeReport, shape_report
from agent_build_kit.pipeline.unit_store import UnitStore
from tests.conftest import make_installation
from tests.factories import init_repo, stored_unit

NOW = datetime(2026, 11, 27, 12, tzinfo=UTC)
SINCE = date(2026, 11, 20)
BEFORE = "2026-10-01T10:00:00+00:00"
IN_WINDOW = "2026-11-22T10:00:00+00:00"
LATER = "2026-11-23T10:00:00+00:00"
LATEST = "2026-11-24T10:00:00+00:00"

STORE = "def store():\n    return 1\n"
CLOCK = "def clock():\n    return 2\n"

ONE_TEST = "def test_a():\n    assert 1\n"

TWO_TESTS = """\
from app.old import thing


def test_a():
    assert thing(1) == 2


def test_b():
    assert thing(2) == 3
"""

THREE_ASSERTIONS_ONE_SETUP = """\
def test_ok():
    box = make()
    result = run(box)
    assert result.ok


def test_count():
    thing = make()
    out = run(thing)
    assert out.count == 1


def test_name():
    item = make()
    done = run(item)
    assert done.name == "x"


def test_other_call():
    box = make()
    result = other(box)
    assert result.a
    assert result.b
"""


def commit_at(
    repo: Path,
    when: str,
    message: str,
    files: dict[str, str] | None = None,
    *,
    rename: dict[str, str] | None = None,
) -> None:
    """Write `files`, rename the keys of `rename` to its values, and commit all of it dated
    `when`."""
    for old, new in (rename or {}).items():
        (repo / new).parent.mkdir(parents=True, exist_ok=True)
        git(repo, "mv", old, new)
    for name, content in (files or {}).items():
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text(content)
    git(repo, "add", "-A")
    stamped = {**os.environ, "GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when}
    git(repo, "commit", "-qm", message, env=stamped)


def merge_at(repo: Path, when: str, branch: str) -> None:
    stamped = {**os.environ, "GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when}
    git(repo, "merge", "--no-ff", "-qm", f"merge {branch}", branch, env=stamped)


def fresh(tmp_path: Path, name: str = "app") -> Path:
    return init_repo(tmp_path / name)


def report_of(
    tmp_path: Path,
    repos: dict[str, dict],
    name: str = "app",
    *,
    runs: dict[str, list[TestRun]] | None = None,
    units: dict[str, str] | None = None,
) -> ShapeReport:
    """The report for `name` in an installation of `repos` (name to its config), whose ledger
    holds `runs` (file name to rows) and whose store holds the units of `units` (id to repo)."""
    inst = make_installation(
        tmp_path / "planning",
        repos=repos,
        planning=dict(state_dir=".", worktree_root=str(tmp_path / "trees")),
    )
    for file, rows in (runs or {}).items():
        for row in rows:
            append_test_run(run_ledger_path(inst.state_dir).with_name(file), row)
    if units:
        UnitStore(inst.state_dir / "units.json").upsert(
            [stored_unit(uid, repo=repo) for uid, repo in units.items()]
        )
    return shape_report(inst, name, since=SINCE, now=NOW)


def python_repo(path: Path, **extra: object) -> dict[str, dict]:
    return {"app": {"path": str(path), "slug": "example/app", **extra}}


def row(unit: str, minutes: float, **fields: object) -> TestRun:
    """A whole-suite ledger row that passed, in the window, of this length."""
    defaults: dict[str, object] = dict(
        started=IN_WINDOW,
        outcome="passed",
        failed=[],
        load_start=None,
        load_end=None,
        workers=None,
        tick="t",
        units_running=[],
        full=True,
    )
    return TestRun.model_validate({"unit": unit, "seconds": minutes * 60, **{**defaults, **fields}})


def test_placement_counts_unit_test_files_not_named_for_a_source_module(tmp_path: Path) -> None:
    app = fresh(tmp_path)
    commit_at(
        app,
        BEFORE,
        "start",
        {
            "src/app/store.py": STORE,
            "tests/test_store.py": ONE_TEST,
            "tests/test_store_lease.py": ONE_TEST,
            "tests/test_retry_behaviour.py": ONE_TEST,
            "tests/conftest.py": "",
            "tests/integration/test_net.py": ONE_TEST,
            "tests/e2e/test_live.py": ONE_TEST,
        },
    )
    (app / "tests" / "test_uncommitted.py").write_text(ONE_TEST)

    report = report_of(tmp_path, python_repo(app))

    assert (report.unplaced, report.unit_test_files) == (2, 3)


def test_new_files_counts_those_not_for_a_source_module_added_in_the_window(
    tmp_path: Path,
) -> None:
    app = fresh(tmp_path)
    commit_at(
        app,
        BEFORE,
        "start",
        {
            "src/app/store.py": STORE,
            "tests/test_store.py": ONE_TEST,
            "tests/test_old_extra.py": ONE_TEST,
        },
    )
    commit_at(app, "2026-11-10T10:00:00+00:00", "early", {"tests/test_early.py": ONE_TEST})
    commit_at(
        app,
        IN_WINDOW,
        "clock",
        {"src/app/clock.py": CLOCK, "tests/test_clock.py": ONE_TEST},
    )
    commit_at(app, LATER, "more", {"tests/test_store_more.py": ONE_TEST})
    commit_at(
        app, LATEST, "rename", rename={"tests/test_old_extra.py": "tests/test_old_renamed.py"}
    )

    report = report_of(tmp_path, python_repo(app))

    assert (report.new_files_not_for_new_module, report.new_files) == (1, 2)


def test_added_and_modified_tests_are_counted_over_commits_not_the_working_copy(
    tmp_path: Path,
) -> None:
    app = fresh(tmp_path)
    commit_at(app, BEFORE, "start", {"tests/test_store.py": TWO_TESTS})
    changed = TWO_TESTS.replace("thing(1) == 2", "thing(1) == 20")
    commit_at(
        app,
        IN_WINDOW,
        "work",
        {
            "tests/test_store.py": changed
            + "\n\ndef test_c():\n    assert 3\n\n\ndef test_d():\n    assert 4\n"
        },
    )
    with (app / "tests" / "test_store.py").open("a") as handle:
        handle.write("\n\ndef test_e():\n    assert 5\n")

    report = report_of(tmp_path, python_repo(app))

    assert (report.added, report.modified) == (2, 1)


def test_a_test_moved_between_files_or_an_import_renamed_is_neither_added_nor_modified(
    tmp_path: Path,
) -> None:
    app = fresh(tmp_path)
    commit_at(app, BEFORE, "start", {"tests/test_store.py": TWO_TESTS})
    moved = "from app.old import thing\n\n\ndef test_b():\n    assert thing(2) == 3\n"
    commit_at(
        app,
        IN_WINDOW,
        "move",
        {
            "tests/test_store.py": TWO_TESTS.split("\n\ndef test_b")[0] + "\n",
            "tests/test_x.py": moved,
        },
    )
    renamed = TWO_TESTS.split("\n\ndef test_b")[0].replace("app.old", "app.new") + "\n"
    commit_at(app, LATER, "import", {"tests/test_store.py": renamed})

    report = report_of(tmp_path, python_repo(app))

    assert (report.added, report.modified) == (0, 0)


def test_a_merged_branch_counts_once_through_its_first_parent_commit(tmp_path: Path) -> None:
    app = fresh(tmp_path)
    commit_at(app, BEFORE, "start", {"tests/test_store.py": ONE_TEST})
    git(app, "checkout", "-qb", "feature")
    first = ONE_TEST + "\n\ndef test_x():\n    assert 1\n"
    commit_at(app, IN_WINDOW, "x", {"tests/test_store.py": first})
    second = first.replace("def test_x():\n    assert 1", "def test_x():\n    assert 10")
    commit_at(
        app, LATER, "y", {"tests/test_store.py": second + "\n\ndef test_y():\n    assert 2\n"}
    )
    git(app, "checkout", "-q", "main")
    merge_at(app, LATEST, "feature")

    report = report_of(tmp_path, python_repo(app))

    assert (report.added, report.modified) == (2, 0)


def test_shape_counts_tests_sharing_setup_and_action_and_those_with_one_assertion(
    tmp_path: Path,
) -> None:
    app = fresh(tmp_path)
    commit_at(app, BEFORE, "start", {"tests/test_store.py": THREE_ASSERTIONS_ONE_SETUP})

    report = report_of(tmp_path, python_repo(app))

    assert (report.sharing, report.single_assertion, report.tests_read) == (3, 3, 4)


def test_a_file_that_does_not_parse_is_counted_apart_as_unreadable(tmp_path: Path) -> None:
    app = fresh(tmp_path)
    commit_at(
        app,
        BEFORE,
        "start",
        {"tests/test_store.py": ONE_TEST, "tests/test_broken.py": "def test_x(:\n"},
    )

    report = report_of(tmp_path, python_repo(app))

    assert (report.unreadable, report.tests_read) == (1, 1)


def test_cost_is_the_median_of_the_repositorys_whole_suite_runs_in_the_window(
    tmp_path: Path,
) -> None:
    app = fresh(tmp_path)
    commit_at(
        app,
        BEFORE,
        "start",
        {"src/app/store.py": STORE, "tests/test_store.py": TWO_TESTS},
    )
    units = {"app/1": "app", "app/2": "app", "app/3": "app", "app/4": "app", "plat/1": "platform"}
    runs = {
        "test-runs.jsonl": [
            row("app/1", 40),
            row("app/2", 44, outcome="failed"),
            row("app/4", 12, full=False),
            row("app/4", 99, reused=True),
            row("app/4", 98, timed_out=True),
            row("app/4", 97, started="2026-11-01T10:00:00+00:00"),
            row("app/4", 96, full=None),
            row("plat/1", 500),
        ],
        # The rotated copy holds older rows of the ledger, which count as well.
        "test-runs.jsonl.1": [row("app/3", 50)],
    }

    report = report_of(tmp_path, python_repo(app), runs=runs, units=units)

    assert (report.median_minutes, report.full_runs) == (44.0, 3)
    assert (report.suite_tests, report.suite_files) == (2, 1)


@pytest.mark.parametrize(
    "runs",
    [{}, {"test-runs.jsonl": [row("app/1", 12, full=False), row("app/1", 99, reused=True)]}],
    ids=["no ledger", "no whole-suite row"],
)
def test_cost_says_there_is_no_median_without_a_ledger_or_a_whole_suite_row(
    tmp_path: Path, runs: dict[str, list[TestRun]]
) -> None:
    app = fresh(tmp_path)
    commit_at(app, BEFORE, "start", {"tests/test_store.py": ONE_TEST})

    report = report_of(tmp_path, python_repo(app), runs=runs, units={"app/1": "app"})

    assert (report.median_minutes, report.full_runs) == (None, 0)
    assert report.suite_tests == 1


def test_a_repository_whose_profile_cannot_read_tests_is_unsupported_by_name(
    tmp_path: Path,
) -> None:
    web = fresh(tmp_path, "web")
    commit_at(
        web,
        BEFORE,
        "start",
        {"src/store.ts": "export const a = 1;\n", "src/store.test.ts": "test('a', () => {});\n"},
    )
    repos = {"web": {"path": str(web), "slug": "example/web", "profile": "node-npm"}}

    report = report_of(tmp_path, repos, "web")

    assert report.unsupported_profile == "node-npm"
    assert (report.unplaced, report.new_files, report.sharing) == (None, None, None)


def test_a_project_whose_profile_cannot_read_tests_is_left_out_and_named(tmp_path: Path) -> None:
    app = fresh(tmp_path)
    commit_at(
        app,
        BEFORE,
        "start",
        {
            "src/app/store.py": STORE,
            "tests/test_store.py": ONE_TEST,
            "web/src/a.test.ts": "test('a', () => {});\n",
        },
    )
    projects = [
        ProjectConfig(path=".", profile="python-uv").model_dump(mode="json"),
        ProjectConfig(path="web", profile="node-npm").model_dump(mode="json"),
    ]

    report = report_of(tmp_path, python_repo(app, projects=projects))

    assert report.left_out == ("web (node-npm)",)
    assert (report.unplaced, report.unit_test_files) == (0, 1)
    assert report.unsupported_profile is None
