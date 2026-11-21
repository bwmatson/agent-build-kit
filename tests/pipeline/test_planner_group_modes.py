"""The planner gives a build mode for each group, never below the group's floor
(spec: group-build-modes)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_build_kit.model import TestTier
from agent_build_kit.pipeline.group_mode import GroupMode
from agent_build_kit.pipeline.joins import JoinContext
from agent_build_kit.pipeline.planner import (
    Plan,
    PlannerError,
    parse_graph,
    parse_plan,
    plan_round,
    reconcile_group_modes,
)
from agent_build_kit.pipeline.shell import git_out as git
from agent_build_kit.pipeline.units import Unit, UnitState
from agent_build_kit.pipeline.work_graph import TaskGroup
from tests.cli.replan_driver import Replan, answer, planned
from tests.factories import commit_files, groups_at, init_repo, stored_unit, unit

CODE_TASK = "Edit `src/pkg/foo.py` to add it."
DOC_TASK = "Update `docs/guide.md` and `CHANGELOG.md`."


def groups(*free: bool) -> list[TaskGroup]:
    """One group per entry; `free` marks the groups that name only documents."""
    return [
        group.model_copy(update={"code_free": code_free})
        for group, code_free in zip(groups_at(*[3] * len(free)), free, strict=True)
    ]


def tasks_text(*bodies: str) -> str:
    text = "# Tasks\n\n"
    for number, body in enumerate(bodies, start=1):
        text += f"## {number}. [app] [unit-test] Group {number}\n\n- [ ] {number}.1 {body}\n\n"
    return text


def reply(modes: dict[str, str] | None, *numbers: int) -> str:
    record: dict = {
        "id": "feature/1",
        "change": "feature",
        "title": "t",
        "repo": "app",
        "tier": "unit-test",
        "groups": list(numbers),
    }
    if modes is not None:
        record["group_modes"] = modes
    return json.dumps({"units": [record]})


def plan(modes: dict[str, str] | None, *free: bool) -> Unit:
    bodies = tuple(DOC_TASK if is_free else CODE_TASK for is_free in free)
    return parse_graph(
        reply(modes, *range(1, len(free) + 1)), groups=groups(*free), tasks=tasks_text(*bodies)
    )[0]


def prompt() -> str:
    captured: dict[str, str] = {}

    def ask(text: str) -> str:
        captured["prompt"] = text
        return '{"units": []}'

    plan_round(changes={"c": "## 1. [app] [unit-test] x\n"}, in_flight=[], run_claude=ask)
    return captured["prompt"]


def test_the_prompt_asks_for_a_mode_per_group_and_reserves_no_code_for_groups_without_code() -> (
    None
):
    text = prompt()

    for word in ("group_modes", "`tests_and_code`", "`no_code`", "`tests_only`"):
        assert word in text
    assert "touches no code" in text


def test_a_no_code_reply_for_a_group_that_may_be_no_code_is_stored_by_change_and_group() -> None:
    unit = plan({"1": "no_code"}, True)

    assert unit.group_modes == {"feature/1": "no_code"}


def test_a_mode_below_the_floor_is_refused_naming_the_unit_and_group() -> None:
    with pytest.raises(PlannerError) as refused:
        plan({"1": "no_code"}, False)

    message = str(refused.value)
    assert "feature/1" in message
    assert "group 1" in message
    assert "tests_and_code" in message


def test_a_reply_may_raise_a_group_that_may_be_no_code_to_tests_and_code() -> None:
    assert plan({"1": "tests_and_code"}, True).group_modes == {"feature/1": "tests_and_code"}


def test_the_prompt_names_refactor_for_a_reorganization() -> None:
    text = prompt()

    assert "`refactor`" in text
    assert "reorganization" in text


def test_refactor_is_accepted_for_a_group_that_names_source_files() -> None:
    try:
        outcome: object = plan({"1": "refactor"}, False).group_modes
    except PlannerError as refused:
        outcome = f"refused: {refused}"

    assert outcome == {"feature/1": "refactor"}


def test_a_join_of_a_source_naming_group_may_be_refactor() -> None:
    try:
        outcome: object = join_plan({"2": "refactor"}).joins[0].group_modes
    except PlannerError as refused:
        outcome = f"refused: {refused}"

    assert outcome == {"feature/2": "refactor"}


def test_an_unknown_mode_is_refused() -> None:
    with pytest.raises(PlannerError, match="no_cod"):
        plan({"1": "no_cod"}, True)


def test_a_reply_with_no_mode_takes_the_floor_of_each_group() -> None:
    unit = plan(None, True, False)

    assert unit.group_modes == {"feature/1": "no_code", "feature/2": "tests_and_code"}


def test_a_reply_naming_a_mode_for_one_group_gives_the_other_its_floor() -> None:
    unit = plan({"1": "tests_and_code"}, True, False)

    assert unit.group_modes == {"feature/1": "tests_and_code", "feature/2": "tests_and_code"}


def replan_modes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *,
    stored: dict[str, str],
    asked: str,
) -> str:
    """What `abk replan feature` prints for an unstarted `feature/1` stored with `stored` modes
    when the planner gives its documents group `asked`."""
    tasks = (
        "# Tasks\n\nAcceptance: none — a fixture\n\n## 1. [app] [unit-test] Group 1\n\n"
        "- [ ] 1.1 Test: it reads.\n- [ ] 1.2 Update `docs/guide.md`.\n"
    )
    run = Replan(tmp_path, monkeypatch, feature=tasks)
    run.store.upsert([stored_unit("feature/1", change="feature", groups=(1,), group_modes=stored)])
    run.record("feature")
    unit = {**planned("feature/1", (1,)), "group_modes": {"1": asked}}

    code, out = run.run(capsys, "feature", reply=answer(unit))

    assert code == 0, out
    return out


@pytest.mark.parametrize("planner_asked", [False, True], ids=["every group taken", "planner asked"])
def test_replan_of_a_started_unit_stores_the_floor_for_an_unbuilt_group_and_keeps_a_built_one(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    planner_asked: bool,
) -> None:
    """With every group taken by the started unit no planner is asked; with a third group not
    yet taken the planner is asked and the plan goes through the store's upsert."""
    tasks = (
        "# Tasks\n\nAcceptance: none — a fixture\n\n"
        "## 1. [app] [unit-test] Group 1\n\n- [ ] 1.1 Edit `tests/test_x.py` to cover it.\n\n"
        "## 2. [app] [unit-test] Group 2\n\n- [ ] 2.1 Edit `tests/test_y.py` to cover it.\n"
    )
    if planner_asked:
        tasks += (
            "\n## 3. [app] [unit-test] Group 3\n\n- [ ] 3.1 Edit `tests/test_z.py` to cover it.\n"
        )
    # The planner may not hand back the started `feature/1`: it plans only the group not taken.
    reply = answer(planned("feature/2", (3,))) if planner_asked else ""
    run = Replan(tmp_path, monkeypatch, feature=tasks)
    repo = init_repo(run.inst.checkouts["app"])
    commit_files(repo, "initial", {"README.md": "x"})
    git(repo, "switch", "-q", "-c", "spec/feature/1")
    commit_files(repo, "test: Group 1", {"tests/test_x.py": "x"})
    commit_files(repo, "feat: Group 1", {"src/x.py": "x"})
    run.store.upsert(
        [stored_unit("feature/1", change="feature", groups=(1, 2), group_modes=STORED)]
    )
    run.store.set_state("feature/1", UnitState.RUNNING, branch="spec/feature/1")
    run.record("feature")

    code, out = run.run(capsys, "feature", reply=reply)

    assert code == 0, out
    assert ("nothing was asked of the planner" in out) is not planner_asked, out
    assert run.store.get("feature/1").group_modes == {
        "feature/1": "tests_and_code",
        "feature/2": "tests_only",
    }, out


def test_replan_prints_a_changed_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    out = replan_modes(
        tmp_path,
        monkeypatch,
        capsys,
        stored={"feature/1": "tests_and_code"},
        asked="no_code",
    )

    line = next(ln for ln in out.splitlines() if "mode of group feature/1" in ln)
    assert "tests_and_code" in line and "no_code" in line


def test_replan_prints_the_first_mode_of_a_unit_planned_before_modes_when_it_is_no_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    out = replan_modes(tmp_path, monkeypatch, capsys, stored={}, asked="no_code")

    line = next(ln for ln in out.splitlines() if "mode of group feature/1" in ln)
    assert "tests_and_code" in line and "no_code" in line


def test_replan_prints_no_mode_line_when_a_unit_planned_before_modes_stays_tests_and_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    out = replan_modes(tmp_path, monkeypatch, capsys, stored={}, asked="tests_and_code")

    assert "mode of group" not in out


@pytest.mark.parametrize(
    ("floor_group", "asked"),
    [
        ({"tier": TestTier.E2E_TEST}, "tests_and_code"),
        ({"test_code": True}, "tests_and_code"),
        ({"code_free": True}, "tests_only"),
        ({}, "tests_only"),
    ],
    ids=["e2e", "test-paths", "documents", "code"],
)
def test_a_mode_the_floor_does_not_allow_is_refused(floor_group: dict, asked: str) -> None:
    group = groups_at(3)[0].model_copy(update=floor_group)

    with pytest.raises(PlannerError, match=r"feature/1.*group 1"):
        parse_graph(reply({"1": asked}, 1), groups=[group], tasks=tasks_text(CODE_TASK))


@pytest.mark.parametrize("modes", ["no_code", {"1": None}, {"1": 3}])
def test_a_malformed_group_modes_is_a_planner_error(modes: object) -> None:
    with pytest.raises(PlannerError, match="group_modes"):
        plan(modes, True)  # pyrefly: ignore[bad-argument-type]


def test_an_unknown_mode_is_refused_even_without_groups() -> None:
    with pytest.raises(PlannerError, match="no_cod"):
        parse_graph(reply({"1": "no_cod"}, 1))


def test_the_reply_shape_names_group_modes() -> None:
    shape = prompt().split("Respond with exactly this shape", 1)[1]

    assert '"group_modes"' in shape


def join_plan(modes: dict[str, str] | None, update: dict | None = None) -> Plan:
    """A plan whose unit builds group 1 of `feature` and whose join brings group 2 onto `base/1`."""
    first, second = groups_at(3, 3)
    second = second.model_copy(update=update or {})
    join: dict = {"onto": "base/1", "change": "feature", "groups": [2], "estimated_lines": 40}
    if modes is not None:
        join["group_modes"] = modes
    record = json.loads(reply(None, 1))
    record["joins"] = [join]
    onto = stored_unit(
        "base/1", change="base", groups=(1,), estimated_lines=100, review_tier="auto"
    )
    return parse_plan(
        json.dumps(record),
        groups=[first, second],
        change="feature",
        context=JoinContext(stored=(onto,), catalog={"base": (groups_at(3)[0],)}),
        tasks=tasks_text(CODE_TASK, DOC_TASK),
    )


def test_a_join_of_a_change_stores_the_floor_of_its_groups_when_the_reply_gives_none() -> None:
    plan_ = join_plan(None, {"test_code": True})

    assert plan_.joins[0].group_modes == {"feature/2": "tests_only"}


def test_a_join_of_a_change_stores_the_planners_mode() -> None:
    plan_ = join_plan({"2": "no_code"}, {"code_free": True})

    assert plan_.joins[0].group_modes == {"feature/2": "no_code"}


def test_a_join_below_the_floor_is_refused() -> None:
    with pytest.raises(PlannerError, match=r"join onto base/1.*group 2"):
        join_plan({"2": "no_code"})


def branch_with(tmp_path: Path, *subjects: str) -> Path:
    """A repository whose `main` has one commit and whose `spec/feature/1` has one commit for each
    of `subjects` beyond it."""
    repo = init_repo(tmp_path / "code")
    commit_files(repo, "initial", {"README.md": "x"})
    git(repo, "switch", "-q", "-c", "spec/feature/1")
    for number, subject in enumerate(subjects):
        commit_files(repo, subject, {f"f{number}.txt": subject})
    return repo


STORED = {"feature/1": "tests_and_code", "feature/2": "tests_and_code"}
FLOORS = {"feature/1": "tests_only", "feature/2": "tests_only"}


def replanned_modes(
    repo: Path, planned_modes: dict[str, str], ref: str = "spec/feature/1"
) -> dict[str, str]:
    """The modes a replan stores for a started `feature/1` of two groups stored `tests_and_code`
    whose tasks now name only test files."""
    kept = stored_unit("feature/1", change="feature", groups=(1, 2), group_modes=STORED)
    fresh = unit("feature/1", change="feature", groups=(1, 2), group_modes=planned_modes)
    named = [group.model_copy(update={"test_code": True}) for group in groups_at(3, 3)]
    return reconcile_group_modes(kept, fresh, named, repo=repo, base="main", ref=ref)


def test_a_replan_gives_an_unbuilt_group_its_floor_and_a_built_group_keeps_its_stored_mode(
    tmp_path: Path,
) -> None:
    repo = branch_with(tmp_path, "test: G1", "feat: G1")

    modes = replanned_modes(repo, FLOORS)

    assert modes == {"feature/1": "tests_and_code", "feature/2": "tests_only"}


def test_a_replan_over_a_branch_with_no_commits_gives_every_group_its_current_mode(
    tmp_path: Path,
) -> None:
    repo = branch_with(tmp_path)

    assert replanned_modes(repo, FLOORS) == FLOORS


def test_a_replan_refuses_a_mode_below_the_floor_of_an_unbuilt_group(tmp_path: Path) -> None:
    repo = branch_with(tmp_path, "test: G1", "feat: G1")
    below = {"feature/1": "tests_only", "feature/2": "no_code"}

    with pytest.raises(PlannerError, match=r"group 2"):
        replanned_modes(repo, below)


def test_a_replan_over_a_branch_that_cannot_be_read_keeps_every_stored_mode_and_logs_why(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = branch_with(tmp_path, "test: G1", "feat: G1")
    capsys.readouterr()

    modes = replanned_modes(repo, FLOORS, ref="spec/feature/gone")

    assert modes == STORED
    assert "feature/1" in capsys.readouterr().out


def declared(*numbers: int) -> list[TaskGroup]:
    """One source-naming group per number, each declaring `Mode: refactor`."""
    return [
        group.model_copy(
            update={"declared_mode": GroupMode.REFACTOR, "declared_reason": "moves only"}
        )
        for group in groups_at(*[3] * len(numbers))
    ]


def test_a_declared_group_stores_refactor_whatever_the_planner_replied() -> None:
    unit = parse_graph(
        reply({"1": "tests_and_code"}, 1), groups=declared(1), tasks=tasks_text(CODE_TASK)
    )[0]

    assert unit.group_modes == {"feature/1": "refactor"}


def test_a_declared_group_stores_refactor_when_the_planner_gave_no_mode() -> None:
    unit = parse_graph(reply(None, 1), groups=declared(1), tasks=tasks_text(CODE_TASK))[0]

    assert unit.group_modes == {"feature/1": "refactor"}


def test_the_prompt_names_a_group_that_declares_its_mode_as_fixed() -> None:
    text = prompt()

    assert "declares a mode" in text
    assert "keeps it" in text


def test_a_replan_gives_an_unbuilt_declared_group_refactor_and_a_built_group_its_stored_mode(
    tmp_path: Path,
) -> None:
    repo = branch_with(tmp_path, "test: G1", "feat: G1")
    kept = stored_unit("feature/1", change="feature", groups=(1, 2), group_modes=STORED)
    fresh = unit("feature/1", change="feature", groups=(1, 2), group_modes=STORED)

    modes = reconcile_group_modes(
        kept, fresh, declared(1, 2), repo=repo, base="main", ref="spec/feature/1"
    )

    assert modes == {"feature/1": "tests_and_code", "feature/2": "refactor"}


@pytest.mark.parametrize("replans", [1, 2], ids=["first replan", "second replan"])
def test_a_declared_reorganization_of_two_renamed_scripts_stays_refactor_on_every_replan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    replans: int,
) -> None:
    """A group that only renames two scripts and follows the move in one test file, with no
    `Test:` task, was left `tests_and_code` by the planner on each replan."""
    tasks = (
        "# Tasks\n\nAcceptance: none — a fixture\n\n## 1. [app] [unit-test] Rename the scripts\n\n"
        "Mode: refactor — renames two scripts and follows the move in one test file\n\n"
        "- [ ] 1.1 Rename `scripts/build_a.py` to `scripts/make_a.py` and `scripts/build_b.py` "
        "to `scripts/make_b.py`.\n"
        "- [ ] 1.2 Update the paths in `tests/test_scripts.py`.\n"
    )
    run = Replan(tmp_path, monkeypatch, feature=tasks)
    run.store.upsert(
        [
            stored_unit(
                "feature/1",
                change="feature",
                groups=(1,),
                group_modes={"feature/1": "tests_and_code"},
            )
        ]
    )
    run.record("feature")
    unit_ = {**planned("feature/1", (1,)), "group_modes": {"1": "tests_and_code"}}

    for _ in range(replans):
        code, out = run.run(capsys, "feature", reply=answer(unit_))
        assert code == 0, out

    assert run.store.get("feature/1").group_modes == {"feature/1": "refactor"}
