"""With the e2e-test tier deferred for a unit's repo, the routing after review, after prepare at an
approved head and after the unit-test node on a moved base skips the e2e node and records
`deferred`; a scheduled run is not affected (spec: e2e-before-merge)."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.config import REST_SPLIT
from agent_build_kit.pipeline.file_lock import file_lock
from agent_build_kit.pipeline.stack_runner import RunStatus
from agent_build_kit.pipeline.unit_store import E2eState
from agent_build_kit.pipeline.units import IN_REVIEW
from tests.conftest import make_installation
from tests.factories import unit
from tests.graph.test_build_path import build, restacked
from tests.graph.test_fresh_base_builds import Moving
from tests.graph.test_remaining_paths import fresh
from tests.runner_fakes import Recorder
from tests.scheduled_e2e_fakes import ScheduledRun

UNIT_ID = unit().id
DEFERRED = {"e2e_before_merge": "deferred"}
APP = {"path": "checkouts/app", "slug": "example/app"}


class Lock:
    """The e2e node's runner, taking the host's e2e lock as the real one does."""

    def __init__(self, recorder: Recorder, lock: Path) -> None:
        self.recorder, self.lock = recorder, lock
        recorder.needs_result = True
        self.taken = 0

    def run(self, *, cwd: Path, base: str | None = None) -> tuple[bool, str]:
        with file_lock(self.lock):
            self.taken += 1
            return self.recorder.e2e(cwd=cwd, base=base)


def assert_opened_as_deferred(recorder: Recorder) -> None:
    """The pull request was opened, with no e2e status, and its body says the tier was deferred."""
    assert "status" not in recorder.events, "no result exists to post a status for"
    assert recorder.store.get(UNIT_ID).state == IN_REVIEW
    [body, *_] = recorder.bodies
    assert "e2e-test deferred to verify" in body
    assert "Not recorded" not in body


def deferring(tmp_path: Path, **config: object) -> Lock:
    inst = make_installation(tmp_path, **({"global_limits": DEFERRED} | config))
    return Lock(fresh(tmp_path, tier="e2e-test"), inst.e2e_lock)


def test_a_unit_approved_by_review_goes_on_without_the_e2e_node_and_records_deferred(
    tmp_path: Path,
) -> None:
    e2e = deferring(tmp_path)
    recorder = e2e.recorder

    outcome = build(tmp_path, recorder, run_e2e=e2e.run)

    assert outcome.status == RunStatus.OPEN, outcome
    assert "e2e-test" not in recorder.events and e2e.taken == 0, "the node did not run"
    assert "push" in recorder.events and recorder.pr_opens == 1
    assert recorder.store.get(UNIT_ID).e2e_state is E2eState.DEFERRED
    assert_opened_as_deferred(recorder)


def test_the_repos_own_value_defers_where_the_global_one_requires(tmp_path: Path) -> None:
    inst = make_installation(
        tmp_path,
        global_limits={"e2e_before_merge": "required"},
        repos={"app": {**APP, "tests": DEFERRED}},
    )
    e2e = Lock(fresh(tmp_path, tier="e2e-test"), inst.e2e_lock)

    build(tmp_path, e2e.recorder, run_e2e=e2e.run)

    assert "e2e-test" not in e2e.recorder.events and e2e.taken == 0
    assert e2e.recorder.store.get(UNIT_ID).e2e_state is E2eState.DEFERRED
    assert_opened_as_deferred(e2e.recorder)


def test_a_unit_approved_at_its_head_on_a_resumed_run_goes_on_without_the_e2e_node(
    tmp_path: Path,
) -> None:
    e2e = deferring(tmp_path)
    recorder = e2e.recorder
    recorder.made = 1
    recorder.store.record_approval(UNIT_ID, recorder.head(tmp_path))

    outcome = build(tmp_path, recorder, run_e2e=e2e.run)

    assert outcome.status == RunStatus.OPEN, outcome
    assert "review" not in recorder.events, "review was not asked again: this is a resumed run"
    assert "e2e-test" not in recorder.events and e2e.taken == 0
    assert "push" in recorder.events
    assert recorder.store.get(UNIT_ID).e2e_state is E2eState.DEFERRED
    assert_opened_as_deferred(recorder)


def test_a_unit_moved_onto_a_new_base_goes_from_unit_test_on_without_the_e2e_node(
    tmp_path: Path,
) -> None:
    e2e = deferring(tmp_path)
    recorder = e2e.recorder
    moving = Moving(recorder, restacked(old_base="old-base-sha"))

    outcome = build(tmp_path, recorder, run_e2e=e2e.run, **moving.overrides())

    assert outcome.status == RunStatus.OPEN, outcome
    after = recorder.events[recorder.events.index("moved") :]
    assert "unit-test" in after and "push" in after, "it was checked on the new base and pushed"
    assert "e2e-test" not in recorder.events and e2e.taken == 0
    assert recorder.store.get(UNIT_ID).e2e_state is E2eState.DEFERRED
    assert_opened_as_deferred(recorder)


def test_a_scheduled_run_runs_the_e2e_node_though_the_tier_is_deferred(tmp_path: Path) -> None:
    run = ScheduledRun(tmp_path, split=REST_SPLIT, limits=DEFERRED)

    outcome = run.tick()

    assert outcome.status == RunStatus.SATISFIED, outcome
    assert run.ran.commands, "the suite ran"
    assert run.stored.e2e_state is E2eState.PASSED


def test_with_the_tier_required_the_node_runs_and_its_status_is_posted(tmp_path: Path) -> None:
    inst = make_installation(tmp_path)
    e2e = Lock(fresh(tmp_path, tier="e2e-test"), inst.e2e_lock)

    outcome = build(tmp_path, e2e.recorder, run_e2e=e2e.run)

    assert outcome.status == RunStatus.OPEN, outcome
    assert e2e.taken == 1
    assert e2e.recorder.events.index("e2e-test") < e2e.recorder.events.index("status")
    assert "e2e-test deferred to verify" not in e2e.recorder.bodies[0]
