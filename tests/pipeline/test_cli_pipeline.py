"""The tick a timer calls every five minutes.

Each step is tested on its own elsewhere; what matters here is that a tick is
safe to run at any moment, since that is the whole premise of putting it on a
short timer. In particular it must not spend anything when the usage window is
low, and must not build anything while paused.
"""

import json
import re
import subprocess
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest

from agent_build_kit import runtimes
from agent_build_kit.cli import pipeline as cli
from agent_build_kit.cli.pipeline import _has_identity as real_has_identity
from agent_build_kit.cli.pipeline import plan_all as real_plan_all
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline import pause
from agent_build_kit.pipeline.archive import archive_ready_changes as real_archive_ready
from agent_build_kit.pipeline.pause import pause_until
from agent_build_kit.pipeline.stack_runner import RunOutcome
from agent_build_kit.pipeline.unit_store import StoredUnit, UnitStore
from agent_build_kit.pipeline.units import IN_REVIEW
from agent_build_kit.pipeline.usage_guard import Decision, UsageReading
from agent_build_kit.pipeline.workspaces import BranchBusy
from tests.conftest import make_installation
from tests.runtimes.stand_in import StandInRuntime

inst: Installation = cast(Installation, None)  # set per test by `isolated`


def reading(**overrides) -> UsageReading:
    defaults: dict = {
        "session_pct": 10,
        "weekly_pct": 10,
        "resets_at": datetime.now(UTC) + timedelta(hours=2),
        "observed_at": datetime.now(UTC),
        "source": "live",
        "credits_enabled": True,
        "credits_used_dollars": 0.0,
        "spend_limit_reached": False,
    }
    return UsageReading(**{**defaults, **overrides})


@pytest.fixture(autouse=True)
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Keep the real runs/ directory — and the real GitHub — out of it.

    `poll_all` is stubbed for every test rather than per test: it shells out
    to `gh` against two live repos, and a test that forgets to stub it turns
    a millisecond into several seconds and starts depending on the network.
    """
    # The state directory is the planning root itself, so the paths the tests
    # write (units.json, paused.json, openspec/changes/...) sit under tmp_path.
    global inst
    inst = make_installation(
        tmp_path, planning={"state_dir": ".", "worktree_root": str(tmp_path.parent / "trees")}
    )
    # A tick that pauses schedules a resume; here it goes nowhere. Without
    # this the suite created a real systemd timer on every run.
    monkeypatch.setattr(pause, "systemd_resume", lambda seconds, command, **k: None)
    monkeypatch.setattr(cli, "poll_all", lambda inst, **kwargs: None)
    # Stubbed like poll_all: it fetches both code repos over the network.
    monkeypatch.setattr(cli, "fetch_all", lambda inst: None)
    # Stubbed for the same reason as poll_all: it shells out to Claude, and a
    # test that forgets to stub it would spend real money. The tests that are
    # about planning call `real_plan_all`, bound above.
    monkeypatch.setattr(cli, "plan_all", lambda inst, **kwargs: None)
    monkeypatch.setattr(cli, "_has_identity", lambda inst, repo: True)
    # Deploys to the live stack and tests against it. Stubbed to "verified"
    # for every test; the ones about it call `real_verify_ready`.
    monkeypatch.setattr(cli, "verify_ready", lambda inst, units, **kwargs: lambda change: True)


def test_a_low_window_pauses_before_planning(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The point of checking usage first: a tick must cost nothing when there
    is no room to work."""
    UnitStore(tmp_path / "units.json").upsert([stored()])  # work, so it gets that far
    planned: list[str] = []
    monkeypatch.setattr(cli, "current_usage", lambda: reading(session_pct=88))
    monkeypatch.setattr(
        cli,
        "may_start_unit",
        lambda r: Decision(may_start=False, reason="session usage at 88%", resume_at=r.resets_at),
    )
    monkeypatch.setattr(cli, "archive_ready_changes", lambda *a, **k: planned.append("archive"))

    assert cli.cmd_tick(argv_namespace(dry_run=True), inst) == 0
    assert planned == []
    assert (tmp_path / "paused.json").exists()


def test_a_tick_while_paused_does_nothing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Otherwise the five-minute timer would undo the pause immediately."""
    checked: list[str] = []
    pause_until(
        datetime.now(UTC) + timedelta(hours=1),
        reason="weekly at 92%",
        marker=tmp_path / "paused.json",
        schedule=lambda s, c: None,
    )
    monkeypatch.setattr(cli, "current_usage", lambda: checked.append("usage") or reading())

    assert cli.cmd_tick(argv_namespace(dry_run=True), inst) == 0
    assert checked == [], "a paused tick shouldn't even read usage"


def test_a_healthy_tick_reports_what_it_would_build(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "current_usage", lambda: reading())
    monkeypatch.setattr(cli, "may_start_unit", lambda r: Decision(may_start=True, reason="plenty"))
    monkeypatch.setattr(cli, "archive_ready_changes", lambda *a, **k: [])

    assert cli.cmd_tick(argv_namespace(dry_run=True), inst) == 0


def test_status_never_changes_anything(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """It is the command to run when something looks wrong, so it must be safe
    to run then."""
    monkeypatch.setattr(cli, "current_usage", lambda: reading())

    assert cli.cmd_status(argv_namespace(), inst) == 0
    assert list(tmp_path.iterdir()) == []


def argv_namespace(**kwargs):
    import argparse

    return argparse.Namespace(**kwargs)


def stored(uid: str = "add-marker/1", **overrides) -> StoredUnit:
    defaults: dict = {
        "id": uid,
        "change": "add-marker",
        "title": "Register the marker",
        "repo": "app",
        "tier": "tier1",
        "depends_on": (),
        "estimated_lines": 140,
        "groups": (1,),
    }
    return StoredUnit(**{**defaults, **overrides})


@pytest.fixture
def healthy(monkeypatch: pytest.MonkeyPatch):
    """A tick with room in the window and nothing to archive."""
    monkeypatch.setattr(cli, "current_usage", lambda: reading())
    monkeypatch.setattr(cli, "may_start_unit", lambda r: Decision(may_start=True, reason="plenty"))
    monkeypatch.setattr(cli, "archive_ready_changes", lambda *a, **k: [])


def test_a_ready_unit_is_actually_built(
    healthy, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The whole point of the tick. Until this passed it only ever reported
    what it would have done."""
    UnitStore(tmp_path / "units.json").upsert([stored()])
    built: list[str] = []
    monkeypatch.setattr(cli, "build_runner", lambda unit, **kwargs: FakeRunner(built))

    assert cli.cmd_tick(argv_namespace(dry_run=False), inst) == 0
    assert built == ["add-marker/1"]


def test_a_dry_run_still_builds_nothing(
    healthy, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    UnitStore(tmp_path / "units.json").upsert([stored()])
    built: list[str] = []
    monkeypatch.setattr(cli, "build_runner", lambda unit, **kwargs: FakeRunner(built))

    assert cli.cmd_tick(argv_namespace(dry_run=True), inst) == 0
    assert built == []


def test_a_unit_whose_branch_is_held_is_skipped_not_failed(
    healthy, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Contention means another tick is already building it. Marking it failed
    would take it out of the plan for work that is going fine."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([stored(), stored("add-marker/2")])
    built: list[str] = []

    def runner(unit, **kwargs):
        if unit.id == "add-marker/1":
            raise BranchBusy("held by pid 1234")
        return FakeRunner(built)

    monkeypatch.setattr(cli, "build_runner", runner)

    assert cli.cmd_tick(argv_namespace(dry_run=False), inst) == 0
    assert built == ["add-marker/2"], "the second unit still gets built"
    assert store.get("add-marker/1").state == "planned"


def test_a_unit_that_raises_is_recorded_as_failed_and_the_tick_continues(
    healthy, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """An unattended run has nobody to catch the traceback. A crash in one
    unit must not take the other ready units down with it."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([stored(), stored("add-marker/2")])
    built: list[str] = []

    def runner(unit, **kwargs):
        if unit.id == "add-marker/1":
            return Exploding()
        return FakeRunner(built)

    monkeypatch.setattr(cli, "build_runner", runner)

    assert cli.cmd_tick(argv_namespace(dry_run=False), inst) == 0
    assert built == ["add-marker/2"]
    assert store.get("add-marker/1").state == "failed"


def test_a_pause_resumes_when_the_window_resets(
    healthy, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Not the generic retry: the window's own reset is known, and waking
    before it just burns a tick finding the window still full."""
    UnitStore(tmp_path / "units.json").upsert([stored()])
    resets = datetime.now(UTC) + timedelta(hours=3)
    monkeypatch.setattr(cli, "current_usage", lambda: reading(resets_at=resets))
    monkeypatch.setattr(cli, "build_runner", lambda unit, **kwargs: Pausing())

    cli.cmd_tick(argv_namespace(dry_run=False), inst)

    paused = json.loads((tmp_path / "paused.json").read_text())
    assert datetime.fromisoformat(paused["until"]) > resets


def test_a_unit_that_pauses_records_the_pause_without_stopping_the_others(
    healthy, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Ready units start together, so there is no "next one" left for a pause
    to hold back: the others are already running, and each checks the usage
    guard itself before its first Claude run. The pause still stops the
    following ticks."""
    UnitStore(tmp_path / "units.json").upsert([stored(), stored("add-marker/2")])
    built: list[str] = []

    def runner(unit, **kwargs):
        if unit.id == "add-marker/1":
            return Pausing()
        return FakeRunner(built)

    monkeypatch.setattr(cli, "build_runner", runner)

    assert cli.cmd_tick(argv_namespace(dry_run=False), inst) == 0
    assert built == ["add-marker/2"]
    assert (tmp_path / "paused.json").exists()


class FakeRunner:
    def __init__(self, built: list[str]) -> None:
        self.built = built

    def run(self, unit, *, base, graph):
        self.built.append(unit.id)
        return RunOutcome(status="open", detail="opened #1", pr=1)


class Exploding:
    def run(self, unit, *, base, graph):
        raise RuntimeError("git exploded")


class Pausing:
    def run(self, unit, *, base, graph):
        return RunOutcome(status="paused", detail="session usage at 71%")


def test_the_tick_polls_before_it_plans(
    healthy, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A PR that merged since the last tick frees a depth slot and changes
    what the units above it should sit on. Scheduling first would build
    against the graph as it was five minutes ago."""
    UnitStore(tmp_path / "units.json").upsert([stored()])  # work, so it gets that far
    order: list[str] = []
    monkeypatch.setattr(cli, "poll_all", lambda inst, **k: order.append("poll"))
    monkeypatch.setattr(cli, "ready_units", lambda *a, **k: order.append("schedule") or [])

    cli.cmd_tick(argv_namespace(dry_run=True), inst)

    assert order == ["poll", "schedule"]


def test_a_poller_failure_does_not_stop_the_tick(
    healthy, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """GitHub being unreachable is a reason to skip the update, not to stop
    building units whose work does not depend on it."""
    UnitStore(tmp_path / "units.json").upsert([stored()])
    built: list[str] = []

    def explode(inst, **kwargs):
        raise RuntimeError("github unreachable")

    monkeypatch.setattr(cli, "poll_all", explode)
    monkeypatch.setattr(cli, "build_runner", lambda unit, **kwargs: FakeRunner(built))

    assert cli.cmd_tick(argv_namespace(dry_run=False), inst) == 0
    assert built == ["add-marker/1"]


def test_nothing_is_built_in_a_repo_with_no_configured_identity(
    healthy, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The agent commits as whoever the repo is configured for. With nothing
    configured that is the machine's global identity — a personal address
    belonging to neither account — and every unit would be misattributed."""
    monkeypatch.setattr(cli, "_has_identity", lambda inst, repo: False)
    UnitStore(tmp_path / "units.json").upsert([stored()])
    built: list[str] = []
    monkeypatch.setattr(cli, "build_runner", lambda unit, **kwargs: FakeRunner(built))

    assert cli.cmd_tick(argv_namespace(dry_run=False), inst) == 1
    assert built == []


def test_the_refusal_names_what_to_fix(
    healthy, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    """An unattended pipeline that stops has to say what to do about it, or
    the next thing anyone sees is a timer that has done nothing for a day."""
    monkeypatch.setattr(cli, "_has_identity", lambda inst, repo: False)
    UnitStore(tmp_path / "units.json").upsert([stored()])

    cli.cmd_tick(argv_namespace(dry_run=False), inst)

    assert "user.email" in capsys.readouterr().out


def test_the_check_runs_before_anything_is_spent(
    healthy, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Catching it at the commit step would mean paying for two Claude runs
    first, and doing that again every five minutes."""
    monkeypatch.setattr(cli, "_has_identity", lambda inst, repo: False)
    monkeypatch.setattr(cli, "build_runner", lambda unit, **kwargs: pytest.fail("built anyway"))
    UnitStore(tmp_path / "units.json").upsert([stored()])

    assert cli.cmd_tick(argv_namespace(dry_run=False), inst) == 1


def test_a_dry_run_still_reports_without_a_configured_identity(
    healthy, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    """--dry-run is what you run to see what is pending before configuring
    anything, so the guard must not be what stops you looking."""
    monkeypatch.setattr(cli, "_has_identity", lambda inst, repo: False)
    UnitStore(tmp_path / "units.json").upsert([stored()])

    assert cli.cmd_tick(argv_namespace(dry_run=True), inst) == 0
    assert "add-marker/1" in capsys.readouterr().out


def test_a_repo_with_a_local_identity_passes_the_check(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Against a real checkout, not a stub: the whole point is what git
    actually resolves, and `--local` is what distinguishes a deliberate
    per-repo identity from inheriting the machine's global one."""
    repo = inst.checkouts["app"]
    repo.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)

    assert real_has_identity(inst, "app") is False

    subprocess.run(
        ["git", "config", "user.email", "example@users.noreply.github.com"],
        cwd=repo,
        check=True,
    )
    assert real_has_identity(inst, "app") is True


def test_a_repo_we_have_no_checkout_of_fails_the_check(monkeypatch: pytest.MonkeyPatch) -> None:
    """It can't be verified, and the worktree step would fail on it anyway —
    better to say so before a unit is started than after."""
    assert real_has_identity(inst, "not-a-repo") is False


def write_change(root: Path, name: str, tasks: str) -> Path:
    path = root / "openspec" / "changes" / name
    path.mkdir(parents=True)
    (path / "tasks.md").write_text(tasks)
    return path


# Opting out of the acceptance group, which these tests are not about: a
# change without one, or a reason, is refused before it is planned.
TASKS = """# Tasks

Acceptance: none — a fixture about planning, not about the acceptance group

## 1. [app] [tier1] Register the marker

- [ ] 1.1 Test: it selects only marked tests.
- [ ] 1.2 Register it.
"""


def test_a_change_with_no_units_is_planned(tmp_path: Path, monkeypatch) -> None:
    write_change(tmp_path, "add-marker", TASKS)
    asked: list[dict] = []
    monkeypatch.setattr(
        cli, "plan_round", lambda **kwargs: asked.append(kwargs) or [stored("add-marker/1")]
    )

    real_plan_all(inst, store=UnitStore(tmp_path / "units.json"))

    assert list(asked[0]["changes"]) == ["add-marker"]
    assert UnitStore(tmp_path / "units.json").get("add-marker/1").id == "add-marker/1"


def test_an_unchanged_change_is_not_planned_again(tmp_path: Path, monkeypatch) -> None:
    """Planning is a model call. A tick runs every five minutes, so re-planning
    a change nobody has touched would spend all day producing the same graph."""
    write_change(tmp_path, "add-marker", TASKS)
    calls: list[int] = []
    monkeypatch.setattr(cli, "plan_round", lambda **k: calls.append(1) or [stored("add-marker/1")])
    store = UnitStore(tmp_path / "units.json")

    real_plan_all(inst, store=store)
    real_plan_all(inst, store=store)

    assert len(calls) == 1


def test_an_edited_change_is_planned_again(tmp_path: Path, monkeypatch) -> None:
    """Its task groups are what units are derived from, so an edit that nobody
    re-plans leaves the graph describing work that no longer exists."""
    path = write_change(tmp_path, "add-marker", TASKS)
    calls: list[int] = []
    monkeypatch.setattr(cli, "plan_round", lambda **k: calls.append(1) or [stored("add-marker/1")])
    store = UnitStore(tmp_path / "units.json")

    real_plan_all(inst, store=store)
    (path / "tasks.md").write_text(TASKS + "\n## 2. [app] [tier1] More\n\n- [ ] 2.1 Do it.\n")
    real_plan_all(inst, store=store)

    assert len(calls) == 2


def test_a_change_with_bad_tags_is_not_planned(tmp_path: Path, monkeypatch, capsys) -> None:
    """The planner routes units by those tags. Planning against a broken one
    spends a model call to produce a graph that cannot be built."""
    write_change(tmp_path, "add-marker", "# Tasks\n\n## 1. Untagged\n\n- [ ] 1.1 Do it.\n")
    monkeypatch.setattr(cli, "plan_round", lambda **k: pytest.fail("planned anyway"))

    real_plan_all(inst, store=UnitStore(tmp_path / "units.json"))

    assert "add-marker" in capsys.readouterr().out


def test_an_archived_change_is_left_alone(tmp_path: Path, monkeypatch) -> None:
    """`archive/` is where finished changes go; re-planning one would rebuild
    work that has already merged."""
    (tmp_path / "openspec" / "changes" / "archive" / "old").mkdir(parents=True)
    (tmp_path / "openspec" / "changes" / "archive" / "old" / "tasks.md").write_text(TASKS)
    monkeypatch.setattr(cli, "plan_round", lambda **k: pytest.fail("planned an archived change"))

    real_plan_all(inst, store=UnitStore(tmp_path / "units.json"))


def test_a_planner_failure_is_retried(tmp_path: Path, monkeypatch) -> None:
    """A model call can fail for reasons that have nothing to do with the
    change, so one bad answer must not shelve it permanently."""
    write_change(tmp_path, "add-marker", TASKS)
    store = UnitStore(tmp_path / "units.json")

    def explode(inst, **kwargs):
        raise RuntimeError("no JSON in the planner's output")

    monkeypatch.setattr(cli, "plan_round", explode)
    real_plan_all(inst, store=store)

    calls: list[int] = []
    monkeypatch.setattr(cli, "plan_round", lambda **k: calls.append(1) or [stored("add-marker/1")])
    real_plan_all(inst, store=store)

    assert calls == [1]


def test_a_change_that_keeps_failing_is_given_up_on(tmp_path: Path, monkeypatch) -> None:
    """Retrying forever costs a model call every five minutes, all day, for a
    change the planner cannot satisfy — and nobody watching an unattended run
    would see it happening."""
    write_change(tmp_path, "add-marker", TASKS)
    store = UnitStore(tmp_path / "units.json")
    calls: list[int] = []

    def explode(**kwargs):
        calls.append(1)
        raise RuntimeError("cannot satisfy the constraints")

    monkeypatch.setattr(cli, "plan_round", explode)
    for _ in range(inst.config.limits.max_plan_attempts + 3):
        real_plan_all(inst, store=store)

    assert len(calls) == inst.config.limits.max_plan_attempts


def test_editing_the_change_starts_the_attempts_over(tmp_path: Path, monkeypatch) -> None:
    """Giving up is about one version of the tasks. Editing it is exactly the
    fix, so it has to be what un-shelves the change."""
    path = write_change(tmp_path, "add-marker", TASKS)
    store = UnitStore(tmp_path / "units.json")
    calls: list[int] = []

    def explode(**kwargs):
        calls.append(1)
        raise RuntimeError("cannot satisfy the constraints")

    monkeypatch.setattr(cli, "plan_round", explode)
    for _ in range(inst.config.limits.max_plan_attempts + 2):
        real_plan_all(inst, store=store)
    before = len(calls)

    (path / "tasks.md").write_text(TASKS + "\n## 2. [app] [tier1] More\n\n- [ ] 2.1 Do it.\n")
    real_plan_all(inst, store=store)

    assert len(calls) == before + 1


TWO_GROUPS = TASKS + "\n## 2. [app] [tier1] Use the marker\n\n- [ ] 2.1 Test: a\n- [ ] 2.2 Do a\n"


def plan_output(*units: dict) -> str:
    """What the planner model answers: prose around the JSON graph."""
    body = [
        {
            "change": "add-marker",
            "title": "Register the marker",
            "repo": "app",
            "tier": "tier1",
            "depends_on": [],
            **unit,
        }
        for unit in units
    ]
    return "Here is the plan.\n\n" + json.dumps({"units": body}) + "\n"


def planner_answering(monkeypatch: pytest.MonkeyPatch, *answers: str) -> StandInRuntime:
    """The runtime the real planner reaches, answering each graph call with
    the next of `answers` and repeating the last once they run out."""
    queue = list(answers)

    def next_answer(request) -> None:
        runtime.answer = queue.pop(0) if len(queue) > 1 else queue[0]

    runtime = StandInRuntime(act=next_answer)
    monkeypatch.setattr(runtimes, "active", lambda: runtime)
    return runtime


def test_a_plan_over_the_ceiling_is_re_asked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """Combining two groups past the ceiling is a mistake the planner can fix,
    so it is rejected like a malformed plan and asked again next tick."""
    write_change(tmp_path, "add-marker", TWO_GROUPS)
    store = UnitStore(tmp_path / "units.json")
    answers = [
        plan_output({"id": "add-marker/1", "groups": [1, 2], "estimated_lines": 1400}),
        plan_output(
            {"id": "add-marker/1", "groups": [1], "estimated_lines": 700},
            {
                "id": "add-marker/2",
                "groups": [2],
                "estimated_lines": 700,
                "depends_on": ["add-marker/1"],
            },
        ),
    ]
    runtime = planner_answering(monkeypatch, *answers)

    real_plan_all(inst, store=store)

    assert store.all() == []
    assert "ceiling" in capsys.readouterr().out

    real_plan_all(inst, store=store)

    assert len(runtime.requests) == 2
    assert [u.groups for u in store.all()] == [(1,), (2,)]


def test_a_plan_that_keeps_ignoring_the_ceiling_uses_up_the_attempts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_change(tmp_path, "add-marker", TWO_GROUPS)
    store = UnitStore(tmp_path / "units.json")
    runtime = planner_answering(
        monkeypatch,
        plan_output({"id": "add-marker/1", "groups": [1, 2], "estimated_lines": 1400}),
    )

    for _ in range(inst.config.limits.max_plan_attempts + 2):
        real_plan_all(inst, store=store)

    assert len(runtime.requests) == inst.config.limits.max_plan_attempts
    assert store.all() == []


def test_a_group_too_large_to_plan_is_reported_not_retried(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """Re-asking cannot help: one group over the ceiling is fixed in tasks.md,
    not in the plan. So the change is left unplanned, the log names the group
    and says to split it, and no further planning attempt is spent on it."""
    write_change(tmp_path, "add-marker", TASKS)
    store = UnitStore(tmp_path / "units.json")
    runtime = planner_answering(
        monkeypatch, plan_output({"id": "add-marker/1", "groups": [1], "estimated_lines": 1500})
    )

    for _ in range(inst.config.limits.max_plan_attempts + 2):
        real_plan_all(inst, store=store)

    assert len(runtime.requests) == 1
    assert store.all() == []
    out = capsys.readouterr().out
    assert "add-marker" in out
    assert "group 1" in out
    assert "split" in out


def test_ticking_a_checkbox_does_not_trigger_a_replan(tmp_path: Path, monkeypatch) -> None:
    """The agent ticks tasks.md as it works. That changed the file's hash, so
    the next tick re-planned — and the planner, seeing the work marked done,
    produced a graph claiming no groups at all. Checkbox state is progress,
    not specification."""
    path = write_change(tmp_path, "add-marker", TASKS)
    calls: list[int] = []
    monkeypatch.setattr(cli, "plan_round", lambda **k: calls.append(1) or [stored("add-marker/1")])
    store = UnitStore(tmp_path / "units.json")

    real_plan_all(inst, store=store)
    (path / "tasks.md").write_text(TASKS.replace("- [ ]", "- [x]"))
    real_plan_all(inst, store=store)

    assert len(calls) == 1


def test_changing_what_a_task_says_does_trigger_a_replan(tmp_path: Path, monkeypatch) -> None:
    """Only the checkbox is ignored. Editing the text of a task, or adding
    one, is a specification change and has to be re-planned."""
    path = write_change(tmp_path, "add-marker", TASKS)
    calls: list[int] = []
    monkeypatch.setattr(cli, "plan_round", lambda **k: calls.append(1) or [stored("add-marker/1")])
    store = UnitStore(tmp_path / "units.json")

    real_plan_all(inst, store=store)
    (path / "tasks.md").write_text(TASKS + "\n- [ ] 1.3 Something new.\n")
    real_plan_all(inst, store=store)

    assert len(calls) == 2


def test_the_planner_is_told_about_merged_units(tmp_path: Path, monkeypatch) -> None:
    """If a re-plan does happen after some units merged, the planner has to
    know they exist — otherwise it either re-plans work that is already in
    main, or drops the groups and the validator rejects the graph."""
    write_change(tmp_path, "add-marker", TASKS)
    store = UnitStore(tmp_path / "units.json")
    store.upsert([stored("add-marker/1")])
    store.set_state("add-marker/1", "merged", pr=1, branch="spec/add-marker/1")
    seen: list[dict] = []
    monkeypatch.setattr(cli, "plan_round", lambda **k: seen.append(k) or [stored("add-marker/1")])

    real_plan_all(inst, store=store)

    states = [u["state"] for u in seen[0]["in_flight"]]
    assert "merged" in states


def test_the_planner_is_told_about_satisfied_units(tmp_path: Path, monkeypatch) -> None:
    """A satisfied unit's groups are as done as a merged unit's — it added
    nothing because the work was already there — so a re-plan has to count
    them as built too, or it either re-plans them or the graph check rejects
    the plan for dropping them."""
    write_change(tmp_path, "add-marker", TASKS)
    store = UnitStore(tmp_path / "units.json")
    store.upsert([stored("add-marker/1", state="satisfied")])
    seen: list[dict] = []
    monkeypatch.setattr(cli, "plan_round", lambda **k: seen.append(k) or [stored("add-marker/1")])

    real_plan_all(inst, store=store)

    assert 1 in seen[0]["built"]


def test_a_unit_whose_process_died_is_reclaimed(
    healthy, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`ready_units` only picks up `planned`, so a unit left `running` when
    its tick was killed is stranded for good: a session ending mid-run leaves
    it with no process and no PR."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([stored()])
    store.set_state("add-marker/1", "running", branch="spec/add-marker/1")

    cli.cmd_tick(argv_namespace(dry_run=True), inst)

    assert store.get("add-marker/1").state == "planned"
    assert "reclaimed" in str(store.get("add-marker/1").history[-1])


def test_a_unit_a_live_process_holds_is_left_alone(
    healthy, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Two ticks can overlap — a slow unit outlives the five-minute timer. The
    branch lock is what says someone is on it, and reclaiming it would hand
    the same unit to a second runner."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([stored()])
    store.set_state("add-marker/1", "running", branch="spec/add-marker/1")
    monkeypatch.setattr(cli, "_branch_is_held", lambda inst, branch: True)

    cli.cmd_tick(argv_namespace(dry_run=True), inst)

    assert store.get("add-marker/1").state == "running"


def test_reclaiming_keeps_work_the_killed_run_had_not_committed(
    healthy, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A tick killed between writing tests and committing them leaves them
    uncommitted — and `prepare_worktree` then refuses the tree, so the unit is
    reclaimed into a state it cannot actually start from. Committing them is
    what makes the reclaim mean something; the next run's `git add -A` would
    have swept them into the tests commit anyway."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([stored()])
    store.set_state("add-marker/1", "running", branch="spec/add-marker/1")
    committed: list[tuple] = []
    monkeypatch.setattr(cli, "_commit_leftovers", lambda inst, unit: committed.append(unit.id))

    cli.cmd_tick(argv_namespace(dry_run=True), inst)

    assert committed == ["add-marker/1"]


def test_reclaiming_says_the_run_was_interrupted(
    healthy, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Committing the leftovers put commits on the branch, and the resume path
    reads commits as "the work is there" and skips building. So an interrupted
    unit went straight to tier 1 on half-written work and failed. Recording
    the interruption as feedback routes it to the rework path instead, which
    continues from what is there rather than skipping or starting over."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([stored()])
    store.set_state("add-marker/1", "running", branch="spec/add-marker/1")
    monkeypatch.setattr(cli, "_commit_leftovers", lambda inst, unit: 1)

    cli.cmd_tick(argv_namespace(dry_run=True), inst)

    assert "interrupted" in store.get("add-marker/1").feedback


def test_reclaiming_a_unit_that_wrote_nothing_adds_no_feedback(
    healthy, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Killed before it wrote anything, there is nothing to continue from —
    it should start cleanly, not be told to resume work that isn't there."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([stored()])
    store.set_state("add-marker/1", "running", branch="spec/add-marker/1")
    monkeypatch.setattr(cli, "_commit_leftovers", lambda inst, unit: 0)

    cli.cmd_tick(argv_namespace(dry_run=True), inst)

    assert store.get("add-marker/1").feedback == ""


def test_a_unit_another_tick_built_meanwhile_is_not_built_again(
    healthy, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Ticks overlap, and each fixes its ready list when it starts. If another
    tick has since built a unit and opened its PR, picking it up from the stale
    list would re-verify, re-push and re-open that PR."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([stored(), stored("add-marker/2")])
    stale = store.all()
    store.set_state("add-marker/2", IN_REVIEW, pr=9)  # the other tick
    monkeypatch.setattr(cli, "ready_units", lambda graph, **kwargs: stale)
    built: list[str] = []
    monkeypatch.setattr(cli, "build_runner", lambda unit, **kwargs: FakeRunner(built))

    assert cli.cmd_tick(argv_namespace(dry_run=False), inst) == 0
    assert built == ["add-marker/1"]


def test_ready_units_are_built_at_the_same_time(
    healthy, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Independent units used to build one after the other, each an hour or
    more. Both runners here wait for the other to arrive: built one at a time,
    the first would wait alone and time out."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([stored(), stored("add-marker/2")])
    built: list[str] = []
    both_running = threading.Barrier(2, timeout=5)

    class Together(FakeRunner):
        def run(self, unit, *, base, graph):
            both_running.wait()
            return super().run(unit, base=base, graph=graph)

    monkeypatch.setattr(cli, "build_runner", lambda unit, **kwargs: Together(built))

    assert cli.cmd_tick(argv_namespace(dry_run=False), inst) == 0
    assert sorted(built) == ["add-marker/1", "add-marker/2"]


def test_only_narrows_what_is_built_and_nothing_else(
    healthy, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """For pushing one unit through when usage is tight, without a second
    unit starting beside it and competing for the same headroom."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([stored(), stored("add-marker/2")])
    built: list[str] = []
    monkeypatch.setattr(cli, "build_runner", lambda unit, **kwargs: FakeRunner(built))
    args = argv_namespace(dry_run=False)
    args.only = ["add-marker/2"]

    assert cli.cmd_tick(args, inst) == 0
    assert built == ["add-marker/2"]
    assert store.get("add-marker/1").state == "planned"


def test_reclaiming_keeps_the_review_a_killed_rework_was_addressing(
    healthy, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Replacing waiting feedback with "you were interrupted" would lose what
    review asked for; the unit resumes at its recorded step with it intact."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([stored()])
    store.set_state("add-marker/1", "running", branch="spec/add-marker/1", resume_from="rework")
    store.set_feedback("add-marker/1", "make it a StrEnum")
    monkeypatch.setattr(cli, "_commit_leftovers", lambda inst, unit: 1)

    cli.cmd_tick(argv_namespace(dry_run=True), inst)

    stored_unit = store.get("add-marker/1")
    assert stored_unit.feedback == "make it a StrEnum"
    assert stored_unit.state == "planned"
    assert stored_unit.resume_from == "rework"


def test_a_killed_claude_run_is_an_interruption_not_a_failure(
    healthy, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A rework SIGKILLed seconds in would be recorded as failed, when
    nothing is known to be wrong with the work."""
    from agent_build_kit.pipeline.usage_guard import Interrupted

    store = UnitStore(tmp_path / "units.json")
    store.upsert([stored()])

    class Killed:
        def run(self, unit, *, base, graph):
            store.set_state(unit.id, "running")
            raise Interrupted("claude was killed by signal 9")

    monkeypatch.setattr(cli, "build_runner", lambda unit, **kwargs: Killed())

    assert cli.cmd_tick(argv_namespace(dry_run=False), inst) == 0
    assert store.get("add-marker/1").state == "running", "left for reclaim_stale"


def _needs_tasks(root: Path) -> None:
    change = root / "openspec" / "changes" / "feature"
    change.mkdir(parents=True)
    (change / "tasks.md").write_text(
        "# Tasks\n\n## 6. [platform] [tier2] Reachable\n\n"
        "Needs: sample-change group 2 — tier 2 runs against the dev stack.\n\n"
        "- [ ] 6.1 Test: reachable\n"
    )


def test_a_needs_line_links_the_unit_to_the_other_change_s_unit(
    healthy, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The planner orders groups within a change, and only sees another
    change's units once they are in flight. A dependency that must hold is
    written down and applied every tick, so a re-plan cannot drop it."""
    _needs_tasks(tmp_path)
    store = UnitStore(tmp_path / "units.json")
    store.upsert(
        [
            stored("sample-change/2", change="sample-change", groups=(2,)),
            stored("feature/5", change="feature", groups=(6,), depends_on=("feature/4",)),
        ]
    )

    cli.link_needs(inst, store=store)
    cli.link_needs(inst, store=store)

    assert store.get("feature/5").depends_on == ("feature/4", "sample-change/2")


def test_adding_a_needs_line_does_not_re_plan_the_change(tmp_path: Path) -> None:
    """A re-plan is a model call that can reshuffle units already built; a
    Needs: line only adds a dependency, which link_needs applies itself."""
    tasks = tmp_path / "tasks.md"
    tasks.write_text("## 1. [app] [tier1] G\n- [ ] 1.1 Do it\n")
    before = cli._specification(tasks)

    tasks.write_text("## 1. [app] [tier1] G\nNeeds: sample-change group 2 — why\n- [ ] 1.1 Do it\n")

    assert cli._specification(tasks) == before


def test_a_tick_with_nothing_in_progress_does_nothing_at_all(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The timer fires every five minutes; with nothing planned, running or in
    review, and no change waiting to be planned, it should not so much as read
    usage or call GitHub."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([stored()])
    store.set_state("add-marker/1", "merged")
    calls: list[str] = []
    monkeypatch.setattr(cli, "current_usage", lambda: calls.append("usage"))

    assert cli.cmd_tick(argv_namespace(dry_run=False), inst) == 0
    assert calls == []


def test_a_unit_in_review_keeps_the_ticks_coming(tmp_path: Path) -> None:
    """Its CI, comments and merge are only noticed by a poll."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([stored()])
    store.set_state("add-marker/1", "in_review", pr=4)

    assert cli.has_work(inst, store)


def test_a_change_not_yet_planned_is_work(tmp_path: Path) -> None:
    change = tmp_path / "openspec" / "changes" / "new-one"
    change.mkdir(parents=True)
    (change / "tasks.md").write_text("## 1. [app] [tier1] G\n- [ ] 1.1 x\n")

    assert cli.has_work(inst, UnitStore(tmp_path / "units.json"))


def test_a_change_ended_satisfied_is_work_until_verified_and_archived(tmp_path: Path) -> None:
    """A unit ends satisfied inside scheduling, after the tick's verify and
    archive step; the next tick must still come, and must be the last."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert(
        [stored("c/1", change="c"), stored("c/2", change="c", depends_on=("c/1",))], change="c"
    )
    store.set_state("c/1", "merged", pr=1)
    store.set_state("c/2", "satisfied")
    calls: list[str] = []

    assert cli.has_work(inst, store)
    may_archive = real_verify_ready(inst, store.all(), verify=_verifier([True], calls))
    assert calls == ["c"]
    assert may_archive("c")
    assert not cli.has_work(inst, store), "verified: nothing left for a tick"


def test_a_failed_verification_of_a_satisfied_change_does_not_keep_ticks_busy(
    tmp_path: Path,
) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([stored("c/1", change="c")], change="c")
    store.set_state("c/1", "satisfied")

    real_verify_ready(inst, store.all(), verify=_verifier([False], []))

    assert not cli.has_work(inst, store)


def test_an_archived_satisfied_change_has_no_work(tmp_path: Path) -> None:
    (tmp_path / "openspec" / "changes" / "archive" / "2026-09-01-c").mkdir(parents=True)
    store = UnitStore(tmp_path / "units.json")
    store.upsert([stored("c/1", change="c")], change="c")
    store.set_state("c/1", "satisfied")

    assert not cli.has_work(inst, store)


# --- verifying a merged change live before archive ---------------------------

real_verify_ready = cli.verify_ready


def _merged(*ids: str, change: str = "c") -> list:
    return [stored(i, change=change, state="merged", pr=n) for n, i in enumerate(ids, start=1)]


def _verifier(outcomes: list[bool], calls: list[str]):
    from agent_build_kit.pipeline.verify import Verification

    def verify(change, units):
        calls.append(change)
        return Verification(
            change=change,
            passed=outcomes.pop(0),
            detail="live tests failed",
            units=sorted(u.id for u in units if u.change == change and u.state == "merged"),
        )

    return verify


def test_a_ready_change_is_verified_live_before_it_may_archive(tmp_path: Path) -> None:
    calls: list[str] = []

    may_archive = real_verify_ready(inst, _merged("c/1", "c/2"), verify=_verifier([True], calls))

    assert calls == ["c"]
    assert may_archive("c")


def test_a_failed_verification_holds_the_archive_and_is_not_retried(tmp_path: Path) -> None:
    # Nothing retries on its own: the same units fail the same way until a
    # person, or a fix, changes something.
    calls: list[str] = []
    verify = _verifier([False, True], calls)

    assert not real_verify_ready(inst, _merged("c/1"), verify=verify)("c")
    assert not real_verify_ready(inst, _merged("c/1"), verify=verify)("c")
    assert calls == ["c"]


def test_a_change_that_gains_a_fix_is_verified_again(tmp_path: Path) -> None:
    calls: list[str] = []
    verify = _verifier([False, True], calls)

    real_verify_ready(inst, _merged("c/1"), verify=verify)
    may_archive = real_verify_ready(inst, _merged("c/1", "c/2"), verify=verify)

    assert calls == ["c", "c"]
    assert may_archive("c")


def test_an_unfinished_or_archived_change_is_not_verified(tmp_path: Path) -> None:
    calls: list[str] = []
    (tmp_path / "openspec" / "changes" / "archive" / "2026-09-01-old").mkdir(parents=True)
    units = [
        *_merged("old/1", change="old"),
        stored("open/1", change="open", state="in_review"),
    ]

    real_verify_ready(inst, units, verify=_verifier([], calls))

    assert calls == []


def test_verify_reruns_one_change_by_hand(tmp_path: Path, monkeypatch, capsys) -> None:
    calls: list[str] = []
    UnitStore(tmp_path / "units.json").upsert(_merged("c/1"))
    fake = _verifier([False, True], calls)
    monkeypatch.setattr(cli, "verify_one", lambda inst, change, units: fake(change, units))
    archiving: list[bool] = []

    def archive(units, *, planning_repo, may_archive, specs_dir="openspec", run_logs=None):
        archiving.append(may_archive("c") and not may_archive("other"))
        return ["c"]

    monkeypatch.setattr(cli, "archive_ready_changes", archive)

    assert cli.cmd_verify(argv_namespace(change="c"), inst) == 1
    assert archiving == [], "a failed verification archives nothing"
    assert cli.cmd_verify(argv_namespace(change="c"), inst) == 0
    assert calls == ["c", "c"]
    # the tick sees no work once everything merged, so a pass archives here
    assert archiving == [True]
    out = capsys.readouterr().out
    assert "live tests failed" in out
    assert "archived c" in out


def test_tags_over_an_empty_store_says_so_rather_than_printing_nothing(
    tmp_path: Path, capsys
) -> None:
    from tests.conftest import make_installation

    empty = make_installation(tmp_path / "planning")
    empty.changes_dir.mkdir(parents=True)

    assert cli.cmd_tags(argv_namespace(change=None, all=True), empty) == 0
    assert "no changes in" in capsys.readouterr().out


# --- a run log per unit ------------------------------------------------------------------


class Speaking:
    """A runner that says something through the `log` the tick gave it."""

    def __init__(self, log, outcome: RunOutcome | Exception) -> None:
        self.log = log
        self.outcome = outcome

    def run(self, unit, *, base, graph):
        self.log(f"said by {unit.id}")
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


def speaking(monkeypatch: pytest.MonkeyPatch, outcomes: dict[str, RunOutcome | Exception]) -> None:
    monkeypatch.setattr(
        cli, "build_runner", lambda unit, **kwargs: Speaking(kwargs["log"], outcomes[unit.id])
    )


def opened(number: int) -> RunOutcome:
    return RunOutcome(status="open", detail=f"opened #{number}", pr=number)


def run_logs() -> list[Path]:
    from agent_build_kit.pipeline.run_log import run_log_dir

    directory = run_log_dir(inst.state_dir)
    return sorted(directory.iterdir()) if directory.exists() else []


def test_a_units_run_is_written_to_a_file_named_for_it(
    healthy, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    UnitStore(tmp_path / "units.json").upsert([stored()])
    speaking(monkeypatch, {"add-marker/1": opened(1)})

    assert cli.cmd_tick(argv_namespace(dry_run=False), inst) == 0

    (path,) = run_logs()
    assert re.fullmatch(r"add-marker-01-\d{8}-\d{6}-[a-z_]+\.log", path.name)


def test_the_file_holds_only_its_units_lines_between_a_header_and_the_outcome(
    healthy, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    UnitStore(tmp_path / "units.json").upsert([stored(), stored("add-marker/2")])
    speaking(monkeypatch, {"add-marker/1": opened(1), "add-marker/2": opened(2)})

    assert cli.cmd_tick(argv_namespace(dry_run=False), inst) == 0

    first, second = run_logs()
    before, after = first.read_text().split("said by add-marker/1")
    assert "add-marker/1" in before
    assert "opened #1" in after
    assert "add-marker/2" not in first.read_text()
    assert "said by add-marker/2" in second.read_text()


def test_the_units_record_names_its_run_log(
    healthy, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([stored()])
    speaking(monkeypatch, {"add-marker/1": opened(1)})

    cli.cmd_tick(argv_namespace(dry_run=False), inst)

    (path,) = run_logs()
    assert store.get("add-marker/1").run_log == path.name


def test_a_failed_units_record_names_its_run_log(
    healthy, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([stored(), stored("add-marker/2")])
    speaking(
        monkeypatch,
        {
            "add-marker/1": RuntimeError("git exploded"),
            "add-marker/2": RunOutcome(status="failed", detail="tier 1 failed"),
        },
    )

    cli.cmd_tick(argv_namespace(dry_run=False), inst)

    first, second = run_logs()
    assert store.get("add-marker/1").state == "failed"
    assert store.get("add-marker/1").run_log == first.name
    assert "git exploded" in first.read_text()
    assert store.get("add-marker/2").run_log == second.name
    assert "tier 1 failed" in second.read_text()


def test_the_pass_still_prints_every_line_as_before(
    healthy, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    UnitStore(tmp_path / "units.json").upsert([stored(), stored("add-marker/2")])
    speaking(monkeypatch, {"add-marker/1": opened(1), "add-marker/2": opened(2)})

    cli.cmd_tick(argv_namespace(dry_run=False), inst)

    printed = capsys.readouterr().out.splitlines()
    for uid in ("add-marker/1", "add-marker/2"):
        assert any(
            re.fullmatch(rf"\[\d\d:\d\d:\d\d\] {uid}: said by {uid}", line) for line in printed
        )
    assert run_logs(), "and each unit's lines are also in its file"
    assert not any(line.startswith("model") or line.startswith("base") for line in printed), (
        "the file's header is not printed"
    )


def start_log(change: str, number: int = 1) -> Path:
    from agent_build_kit.pipeline.run_log import RunLog, run_log_dir
    from tests.factories import unit as make_unit

    log = RunLog(
        run_log_dir(inst.state_dir),
        make_unit(f"{change}/{number}", change=change),
        step="implement",
        model="m",
        base="main",
        started=datetime(2026, 9, 23, 22, 44, 5, tzinfo=UTC),
    )
    return run_log_dir(inst.state_dir) / log.name


def test_a_units_file_names_the_step_and_model_of_a_fresh_build(
    healthy, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _distinct_models(monkeypatch)
    UnitStore(tmp_path / "units.json").upsert([stored()])
    speaking(monkeypatch, {"add-marker/1": opened(1)})

    cli.cmd_tick(argv_namespace(dry_run=False), inst)

    (path,) = run_logs()
    assert path.name.endswith("-implement.log")
    assert "step: implement\nmodel: m-implement\n" in path.read_text()


def test_a_units_file_names_the_rework_of_waiting_feedback(
    healthy, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _distinct_models(monkeypatch)
    store = UnitStore(tmp_path / "units.json")
    store.upsert([stored()])
    store.set_feedback("add-marker/1", "rename the marker")
    speaking(monkeypatch, {"add-marker/1": opened(1)})

    cli.cmd_tick(argv_namespace(dry_run=False), inst)

    (path,) = run_logs()
    assert path.name.endswith("-rework.log")
    assert "step: rework\nmodel: m-rework\n" in path.read_text()


@pytest.mark.parametrize(
    ("resume", "model"),
    [
        ("review", "m-review"),
        ("rework_review", "m-rework-review"),
        ("tests", "m-implement"),
        ("verify", "none"),
    ],
)
def test_a_units_file_names_the_step_it_resumes_at(
    resume: str, model: str, healthy, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _distinct_models(monkeypatch)
    store = UnitStore(tmp_path / "units.json")
    store.upsert([stored()])
    store.record_step("add-marker/1", resume)
    speaking(monkeypatch, {"add-marker/1": opened(1)})

    cli.cmd_tick(argv_namespace(dry_run=False), inst)

    (path,) = run_logs()
    assert path.name.endswith(f"-{resume}.log")
    assert f"step: {resume}\nmodel: {model}\n" in path.read_text()


def _distinct_models(monkeypatch: pytest.MonkeyPatch) -> None:
    from agent_build_kit.config import ModelsConfig
    from agent_build_kit.pipeline import stack_runner

    monkeypatch.setattr(
        stack_runner,
        "models",
        lambda: ModelsConfig(
            implement="m-implement",
            rework="m-rework",
            review="m-review",
            rework_review="m-rework-review",
        ),
    )


def _unusable_log_dir() -> None:
    from agent_build_kit.pipeline.run_log import run_log_dir

    run_log_dir(inst.state_dir).write_text("a file where the directory should be")


def test_an_unusable_log_directory_does_not_touch_the_build(
    healthy, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([stored()])
    speaking(monkeypatch, {"add-marker/1": opened(1)})
    _unusable_log_dir()

    assert cli.cmd_tick(argv_namespace(dry_run=False), inst) == 0

    assert "said by add-marker/1" in capsys.readouterr().out
    assert store.get("add-marker/1").state != "failed"


def test_an_unusable_log_directory_still_records_a_failed_unit(
    healthy, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([stored()])
    speaking(monkeypatch, {"add-marker/1": RuntimeError("git exploded")})
    _unusable_log_dir()

    assert cli.cmd_tick(argv_namespace(dry_run=False), inst) == 0

    assert store.get("add-marker/1").state == "failed"
    assert "git exploded" in capsys.readouterr().out


def _archiving(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    from agent_build_kit import openspec

    archived: list[str] = []
    monkeypatch.setattr(
        openspec, "archive", lambda change, cwd, run=None: archived.append(change) or ""
    )
    return archived


def _two_changes_logged(tmp_path: Path) -> tuple[Path, Path]:
    UnitStore(tmp_path / "units.json").upsert(
        [*_merged("c/1"), *_merged("other/1", change="other")]
    )
    return start_log("c"), start_log("other")


def test_archiving_by_hand_removes_the_changes_logs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _archiving(monkeypatch)
    mine, other = _two_changes_logged(tmp_path)

    assert cli.cmd_archive(argv_namespace(change="c"), inst) == 0

    assert not mine.exists()
    assert other.exists()


def test_a_passing_verify_removes_the_changes_logs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    archived = _archiving(monkeypatch)
    mine, other = _two_changes_logged(tmp_path)
    fake = _verifier([True], [])
    monkeypatch.setattr(cli, "verify_one", lambda inst, change, units: fake(change, units))

    assert cli.cmd_verify(argv_namespace(change="c"), inst) == 0

    assert archived == ["c"]
    assert not mine.exists()
    assert other.exists()


def test_a_tick_that_archives_removes_the_changes_logs(
    healthy, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(cli, "archive_ready_changes", real_archive_ready)
    archived = _archiving(monkeypatch)
    mine, other = _two_changes_logged(tmp_path)
    monkeypatch.setattr(
        cli, "verify_ready", lambda inst, units, **kwargs: lambda change: change == "c"
    )
    monkeypatch.setattr(cli, "has_work", lambda inst, store: True)

    cli.cmd_tick(argv_namespace(dry_run=True), inst)

    assert archived == ["c"]
    assert not mine.exists()
    assert other.exists()


def _tick_one(monkeypatch: pytest.MonkeyPatch, outcome: RunOutcome | Exception) -> list[str]:
    speaking(monkeypatch, {"add-marker/1": outcome})
    cli.cmd_tick(argv_namespace(dry_run=False), inst)
    (path,) = run_logs()
    return path.read_text().splitlines()


def _closing(lines: list[str]) -> str:
    assert len([line for line in lines if line.startswith("outcome: ")]) == 1
    return [line for line in lines if line.strip()][-1]


def test_the_file_closes_with_a_returned_open_outcome(
    healthy, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    UnitStore(tmp_path / "units.json").upsert([stored()])

    lines = _tick_one(monkeypatch, opened(1))

    assert _closing(lines) == "outcome: open \u2014 opened #1"


def test_the_file_closes_with_a_returned_failure(
    healthy, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    UnitStore(tmp_path / "units.json").upsert([stored()])

    lines = _tick_one(monkeypatch, RunOutcome(status="failed", detail="tier 1 failed"))

    assert _closing(lines) == "outcome: failed \u2014 tier 1 failed"


def test_the_file_closes_with_a_raised_error(
    healthy, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    UnitStore(tmp_path / "units.json").upsert([stored()])

    lines = _tick_one(monkeypatch, RuntimeError("git exploded"))

    assert _closing(lines) == "outcome: failed, RuntimeError: git exploded"


def test_the_file_closes_interrupted_and_the_unit_is_not_failed(
    healthy, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from agent_build_kit.pipeline.usage_guard import Interrupted

    store = UnitStore(tmp_path / "units.json")
    store.upsert([stored()])

    lines = _tick_one(monkeypatch, Interrupted("claude was killed by signal 9"))

    assert _closing(lines).startswith("outcome: interrupted (")
    assert store.get("add-marker/1").state != "failed"


def test_the_file_closes_rate_limited(
    healthy, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from agent_build_kit.pipeline.usage_guard import RateLimited

    UnitStore(tmp_path / "units.json").upsert([stored()])
    when = datetime.now(UTC) + timedelta(hours=1)

    lines = _tick_one(monkeypatch, RateLimited("usage limit reached", resets_at=when))

    assert _closing(lines).startswith("outcome: rate limited \u2014 pausing until")


HEADER = re.compile(
    r"unit: add-marker/1\nchange: add-marker\nstep: implement\nmodel: m-implement\n"
    r"base: (?P<base>.+)\nstarted: \d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[.\d]*\+00:00\n\n"
)


def test_the_file_opens_with_the_unit_change_step_model_base_and_start(
    healthy, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _distinct_models(monkeypatch)
    UnitStore(tmp_path / "units.json").upsert([stored()])
    speaking(monkeypatch, {"add-marker/1": opened(1)})

    cli.cmd_tick(argv_namespace(dry_run=False), inst)

    (path,) = run_logs()
    header = HEADER.match(path.read_text())
    assert header
    assert header["base"] == "main"


def test_a_stacked_units_file_names_its_parents_branch_as_the_base(
    healthy, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from agent_build_kit.pipeline.units import base_of

    _distinct_models(monkeypatch)
    store = UnitStore(tmp_path / "units.json")
    parent = stored("add-marker/1", state=IN_REVIEW)
    child = stored("add-marker/2", depends_on=("add-marker/1",))
    store.upsert([parent, child])
    speaking(monkeypatch, {"add-marker/2": opened(2)})

    cli.cmd_tick(argv_namespace(dry_run=False), inst)

    (path,) = run_logs()
    expected = base_of(child, store.all())
    assert expected != "main"
    assert f"step: implement\nmodel: m-implement\nbase: {expected}\nstarted: " in path.read_text()


def test_the_files_lines_carry_the_stamp_the_tick_prints(
    healthy, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    UnitStore(tmp_path / "units.json").upsert([stored()])
    speaking(monkeypatch, {"add-marker/1": opened(1)})

    cli.cmd_tick(argv_namespace(dry_run=False), inst)

    printed = re.search(
        r"\[(\d\d:\d\d:\d\d)\] add-marker/1: said by add-marker/1", capsys.readouterr().out
    )
    (path,) = run_logs()
    written = re.search(r"\[(\d\d:\d\d:\d\d)\] said by add-marker/1", path.read_text())
    assert printed
    assert written
    assert written[1] == printed[1]


def test_a_log_that_could_not_be_created_is_not_named_on_the_record(
    healthy, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([stored()])
    speaking(monkeypatch, {"add-marker/1": opened(1)})
    _unusable_log_dir()

    cli.cmd_tick(argv_namespace(dry_run=False), inst)

    assert store.get("add-marker/1").run_log == ""
