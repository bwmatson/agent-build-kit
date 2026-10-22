"""The pipeline runs the fixers before the stub loop's static check, so before the tests commit
(spec: fixers-run-before-commits). A hook that reformats a file and exits non-zero is stood for
by a fake that rewrites it, and the static check passes only on a formatted tree."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.pipeline.unit_store import UnitStore
from tests.factories import unit
from tests.graph.branch_fakes import titled, write_tasks
from tests.graph.fixer_fakes import FIXERS, FORMATTED, Formatting
from tests.graph.stub_loop_fakes import stubbed_build
from tests.graph.test_build_path import build
from tests.graph_driver import fresh as fresh_store

TESTS_FILE = "tests/test_x.py"


def test_the_fixers_format_the_tests_before_the_static_check_which_then_passes_first_time(
    tmp_path: Path,
) -> None:
    stubbed_build()
    recorder = Formatting(fresh_store(tmp_path).store, leaves={"claude:tests": TESTS_FILE})

    outcome = build(tmp_path, recorder, **recorder.overrides(tmp_path))

    assert outcome.status == "open", outcome.detail
    assert recorder.events[:4] == ["claude:tests", FIXERS, "stub-checks", "commit:test"], (
        "the fixers ran after the tests agent and before the check, and the check made no fix"
    )
    assert recorder.formatted_at_check[0] is True
    assert "claude:fix_stub" not in recorder.events, "no agent call was made for the format"
    assert not [s for s in recorder.subjects if s.startswith("fix:")]
    assert recorder.held_by("test:")[TESTS_FILE] == FORMATTED
    assert any(
        "fixers changed 1 file(s)" in line and TESTS_FILE in line for line in recorder.logged
    ), recorder.logged


def test_a_test_only_groups_lone_tests_commit_is_formatted_the_same_way(tmp_path: Path) -> None:
    stubbed_build()
    write_tasks(tmp_path, "add-marker", titled(1, 2, 3), tests_only=(1, 2, 3))
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit(groups=(1, 2, 3))])
    recorder = Formatting(store, leaves={"claude:tests": TESTS_FILE})

    build(tmp_path, recorder, **recorder.overrides(tmp_path))

    assert recorder.events[:4] == ["claude:tests", FIXERS, "stub-checks", "commit:test"]
    assert "claude:fix_stub" not in recorder.events
    assert recorder.held_by("test:")[TESTS_FILE] == FORMATTED
    assert any("fixers changed 1 file(s)" in line for line in recorder.logged)
