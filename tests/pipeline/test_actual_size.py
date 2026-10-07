"""A unit's actual size: recorded when its pull request is opened and again
when a push updates it, from the host's own totals less generated files, and
logged where it passes the ceiling without ever stopping the unit."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.forges import FileChange, RepoId
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import UnitState
from agent_build_kit.pipeline.wiring import build_open_pr
from tests.factories import activate_with, stored_unit
from tests.factories import unit as plan_unit

REPO = RepoId(forge="fake", account="example", name="app")


class SizedForge:
    """A host that answers how big a pull request is, file by file."""

    name = "fake"
    implemented = True
    supports_stacks = False

    def __init__(self, changes: list[FileChange]) -> None:
        self.changes = changes
        self.existing: int | None = None

    def find_pr(self, repo, *, head):
        return self.existing

    def create_pr(self, repo, *, head, base, title, body):
        self.existing = 12
        return 12

    def update_pr(self, repo, pr, *, base="", body=""):
        pass

    def pr_changes(self, repo, pr):
        return list(self.changes)

    def stack_of(self, repo, pr):
        raise AssertionError("a host without stacks was asked about one")

    def create_stack(self, repo, pulls):
        raise AssertionError("a host without stacks was asked about one")

    def add_to_stack(self, repo, stack, pulls):
        raise AssertionError("a host without stacks was asked about one")


def change(path: str, additions: int, deletions: int = 0) -> FileChange:
    return FileChange(path=path, additions=additions, deletions=deletions)


@pytest.fixture(autouse=True)
def ceiling() -> None:
    activate_with(limits={"min_unit_lines": 400, "max_unit_lines": 750})


@pytest.fixture
def store(tmp_path: Path) -> UnitStore:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([stored_unit("feature/1", estimated_lines=600), stored_unit("feature/2")])
    store.set_state("feature/1", UnitState.RUNNING, branch="spec/feature/1")
    return store


def open_for(
    forge: SizedForge, store: UnitStore, tmp_path: Path, logged: list[str] | None = None
) -> int:
    log = logged.append if logged is not None else (lambda message: None)
    open_pr = build_open_pr(for_repo=lambda repo: (forge, REPO), store=store, log=log)
    unit = plan_unit("feature/1", change="feature", estimated_lines=600)
    return open_pr(unit, body="b", base="main", cwd=tmp_path)


def test_opening_a_pull_request_records_the_lines_it_changes(
    store: UnitStore, tmp_path: Path
) -> None:
    forge = SizedForge([change("src/app.py", 300, 20), change("tests/test_app.py", 250, 30)])

    open_for(forge, store, tmp_path)

    assert store.get("feature/1").actual_lines == 600


def test_a_unit_with_no_pull_request_has_no_actual_size(store: UnitStore, tmp_path: Path) -> None:
    open_for(SizedForge([change("src/app.py", 10)]), store, tmp_path)

    assert store.get("feature/1").actual_lines == 10
    assert store.get("feature/2").actual_lines is None


def test_a_push_after_a_rework_updates_it(store: UnitStore, tmp_path: Path) -> None:
    """Overwritten, not added to: it is the size the reviewer sees now."""
    forge = SizedForge([change("src/app.py", 900, 100)])
    open_for(forge, store, tmp_path)
    assert store.get("feature/1").actual_lines == 1000

    forge.changes = [change("src/app.py", 400, 50)]
    open_for(forge, store, tmp_path)

    assert store.get("feature/1").actual_lines == 450


def test_planning_again_keeps_the_recorded_size(store: UnitStore, tmp_path: Path) -> None:
    open_for(SizedForge([change("src/app.py", 300)]), store, tmp_path)

    store.upsert([plan_unit("feature/1", change="feature", estimated_lines=600)])

    assert store.get("feature/1").actual_lines == 300


def test_lockfiles_are_not_counted(store: UnitStore, tmp_path: Path) -> None:
    forge = SizedForge(
        [
            change("src/app.py", 100, 20),
            change("uv.lock", 500, 300),
            change("web/package-lock.json", 40, 10),
        ]
    )

    open_for(forge, store, tmp_path)

    assert store.get("feature/1").actual_lines == 120


def test_the_generated_files_are_the_configured_patterns(store: UnitStore, tmp_path: Path) -> None:
    activate_with(
        limits={"min_unit_lines": 400, "max_unit_lines": 750, "generated_files": ["*.snap"]}
    )
    forge = SizedForge([change("src/app.py", 50), change("out.snap", 400, 100)])

    open_for(forge, store, tmp_path)

    assert store.get("feature/1").actual_lines == 50


def test_a_unit_over_the_ceiling_says_so_and_is_not_blocked(
    store: UnitStore, tmp_path: Path
) -> None:
    logged: list[str] = []
    forge = SizedForge([change("src/app.py", 1000, 400)])

    number = open_for(forge, store, tmp_path, logged)

    assert number == 12
    assert "estimated 600, landed 1400, over the ceiling of 750" in "\n".join(logged)
    unit = store.get("feature/1")
    assert unit.actual_lines == 1400
    assert unit.state == UnitState.RUNNING


def test_a_unit_within_the_ceiling_logs_nothing_about_it(store: UnitStore, tmp_path: Path) -> None:
    logged: list[str] = []

    open_for(SizedForge([change("src/app.py", 750)]), store, tmp_path, logged)

    assert store.get("feature/1").actual_lines == 750
    assert "over the ceiling" not in "\n".join(logged)
