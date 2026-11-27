"""The planner pass: an LLM proposes the graph, we verify it.

Each round, a `claude -p` call reads every change in flight and returns the
whole unit graph as JSON (docs/architecture.md). Nothing is
cached — the graph is re-derived rather than kept as a file that drifts.

That makes validation the load-bearing part. The planner's output schedules
real work in real repos, so anything malformed stops the round instead of
being repaired into something plausible: a guessed repo would build in the
wrong place, and a dropped dependency would build against work that doesn't
exist yet.
"""

import json

import pytest

from agent_build_kit.config import active, ceilings_in_effect
from agent_build_kit.pipeline.planner import (
    GroupTooLarge,
    PlannerError,
    build_prompt,
    in_flight_item,
    parse_graph,
    plan_round,
)
from agent_build_kit.pipeline.units import FAILED
from agent_build_kit.pipeline.work_graph import TaskGroup
from tests.factories import activate_with, groups_at, stored_unit
from tests.project_workspace import tasks_editing

GOOD = {
    "units": [
        {
            "id": "add-marker/1",
            "change": "add-marker",
            "title": "Register the marker",
            "repo": "platform",
            "tier": "unit-test",
            "depends_on": [],
            "estimated_lines": 120,
            "groups": [1],
        },
        {
            "id": "add-marker/2",
            "change": "add-marker",
            "title": "Register it in app",
            "repo": "app",
            "tier": "unit-test",
            "depends_on": ["add-marker/1"],
            "estimated_lines": 140,
            "groups": [2],
        },
    ]
}


def test_a_well_formed_graph_parses() -> None:
    units = parse_graph(json.dumps(GOOD))

    assert [u.id for u in units] == ["add-marker/1", "add-marker/2"]
    assert units[1].depends_on == ("add-marker/1",)
    assert units[0].repo == "platform"


def test_json_wrapped_in_prose_is_still_read() -> None:
    """Models narrate. The JSON is what matters, not the sentence around it."""
    units = parse_graph(f"Here is the plan:\n```json\n{json.dumps(GOOD)}\n```\nDone.")

    assert len(units) == 2


@pytest.mark.parametrize(
    "broken",
    [
        "not json at all",
        "{}",
        '{"units": "lots"}',
        '{"units": [{"id": "x"}]}',
    ],
)
def test_malformed_output_stops_the_round(broken: str) -> None:
    with pytest.raises(PlannerError):
        parse_graph(broken)


def test_an_unknown_repo_is_refused() -> None:
    """A guessed repo would build the work in the wrong place."""
    bad = json.loads(json.dumps(GOOD))
    bad["units"][0]["repo"] = "app-agent"

    with pytest.raises(PlannerError, match="repo"):
        parse_graph(json.dumps(bad))


def test_an_unknown_tier_is_refused() -> None:
    bad = json.loads(json.dumps(GOOD))
    bad["units"][1]["tier"] = "tier3"

    with pytest.raises(PlannerError, match="tier"):
        parse_graph(json.dumps(bad))


def test_a_dependency_on_a_unit_that_does_not_exist_is_refused() -> None:
    """Otherwise the unit waits forever on something nobody will build."""
    bad = json.loads(json.dumps(GOOD))
    bad["units"][1]["depends_on"] = ["add-marker/99"]

    with pytest.raises(PlannerError, match="unknown dependency"):
        parse_graph(json.dumps(bad))


def test_duplicate_ids_are_refused() -> None:
    bad = json.loads(json.dumps(GOOD))
    bad["units"][1]["id"] = "add-marker/1"

    with pytest.raises(PlannerError, match="duplicate"):
        parse_graph(json.dumps(bad))


def test_a_dependency_cycle_is_refused() -> None:
    """A cycle schedules nothing and looks like a stalled pipeline."""
    bad = json.loads(json.dumps(GOOD))
    bad["units"][0]["depends_on"] = ["add-marker/2"]

    with pytest.raises(PlannerError, match="cycle"):
        parse_graph(json.dumps(bad))


def test_a_unit_depending_on_itself_is_refused() -> None:
    bad = json.loads(json.dumps(GOOD))
    bad["units"][0]["depends_on"] = ["add-marker/1"]

    with pytest.raises(PlannerError, match="cycle"):
        parse_graph(json.dumps(bad))


def test_the_prompt_carries_the_changes_and_the_work_in_flight() -> None:
    """The planner can't place new work sensibly without seeing what is
    already open — that is how a new change ends up stacking on it rather than
    conflicting with it."""
    captured: dict = {}

    def fake_claude(prompt: str) -> str:
        captured["prompt"] = prompt
        return json.dumps(GOOD)

    plan_round(
        changes={"add-marker": "## 1. [platform] [unit-test] Register the marker\n"},
        in_flight=[
            {"id": "other/1", "repo": "app", "branch": "spec/other/1", "state": "in_review"}
        ],
        run_claude=fake_claude,
    )

    assert "add-marker" in captured["prompt"]
    assert "Register the marker" in captured["prompt"]
    assert "spec/other/1" in captured["prompt"]


def test_the_prompt_states_the_rules_the_graph_must_satisfy() -> None:
    """The validator refuses a bad graph, but the prompt is what makes a good
    one likely — a refusal costs a whole round."""
    captured: dict = {}

    plan_round(
        changes={"add-marker": "## 1. [app] [unit-test] x\n"},
        in_flight=[],
        run_claude=lambda prompt: captured.setdefault("prompt", prompt) and json.dumps(GOOD),
    )

    prompt = captured["prompt"]
    assert "never spans repos" in prompt
    assert "cross-repo" in prompt
    assert "estimated_lines" in prompt


def test_an_empty_plan_is_allowed() -> None:
    """Nothing ready is a normal answer, not a failure: every change may be
    waiting on review."""
    plan = plan_round(changes={}, in_flight=[], run_claude=lambda prompt: json.dumps({"units": []}))

    assert plan.units == ()


GROUPS = [
    TaskGroup(number=1, repo="platform", tier="unit-test", title="A", line=3, task_count=2),
    TaskGroup(number=2, repo="app", tier="unit-test", title="B", line=9, task_count=2),
    TaskGroup(number=3, repo="app", tier="unit-test", title="C", line=15, task_count=1),
]


def graph_json(units: list[dict]) -> str:
    return json.dumps({"units": units})


def planned(**overrides) -> dict:
    return {
        "id": "c/1",
        "change": "c",
        "title": "A unit",
        "repo": "app",
        "tier": "unit-test",
        "groups": [2],
        **overrides,
    }


def test_a_unit_cannot_claim_a_group_from_another_repo() -> None:
    """Caught on the first real planning run: a platform unit was given a
    group tagged [app], so it would have been built in the wrong checkout
    and edited files that are not there."""
    output = graph_json([planned(id="c/1", repo="platform", groups=[1, 3])])

    with pytest.raises(PlannerError, match="group 3"):
        parse_graph(output, groups=GROUPS)


def test_a_group_cannot_be_built_twice() -> None:
    """Two units both claiming a group means the same tasks are implemented
    twice, on two branches, and the second one conflicts with the first."""
    output = graph_json([planned(id="c/1", groups=[2, 3]), planned(id="c/2", groups=[3])])

    with pytest.raises(PlannerError, match="group 3"):
        parse_graph(output, groups=GROUPS)


def test_every_group_has_to_land_somewhere() -> None:
    """A group nobody builds is work silently dropped from the change, and the
    archive step would later fold the spec in as though it were done."""
    output = graph_json([planned(id="c/1", groups=[2, 3])])

    with pytest.raises(PlannerError, match=r"group\(s\) 1"):
        parse_graph(output, groups=GROUPS)


def test_a_unit_cannot_claim_a_group_that_does_not_exist() -> None:
    output = graph_json(
        [
            planned(id="c/1", repo="platform", groups=[1]),
            planned(id="c/2", groups=[2, 3, 9]),
        ]
    )

    with pytest.raises(PlannerError, match="group 9"):
        parse_graph(output, groups=GROUPS)


def test_a_correct_split_passes() -> None:
    output = graph_json(
        [
            planned(id="c/1", repo="platform", groups=[1]),
            planned(id="c/2", repo="app", groups=[2, 3]),
        ]
    )

    assert [u.id for u in parse_graph(output, groups=GROUPS)] == ["c/1", "c/2"]


def test_without_the_groups_the_check_is_skipped() -> None:
    """`groups` is optional so existing callers and tests that only care about
    the shape of a graph don't have to construct a task list."""
    assert parse_graph(graph_json([planned()]))[0].id == "c/2"


def test_a_group_already_built_need_not_be_claimed_again() -> None:
    """After one unit of a change merges, a re-plan covers only what is left.
    Insisting every group appear made the change unplannable the moment part
    of it landed — which is exactly when a re-plan is most likely."""
    output = graph_json([planned(id="c/2", groups=[2, 3])])

    units = parse_graph(output, groups=GROUPS, built={1})

    assert [u.id for u in units] == ["c/2"]


def test_a_group_neither_built_nor_planned_is_still_caught() -> None:
    """The check still has to mean something: work that no unit builds and no
    merge covers would vanish while its spec is archived as done."""
    output = graph_json([planned(id="c/2", groups=[2])])

    with pytest.raises(PlannerError, match=r"group\(s\) 3"):
        parse_graph(output, groups=GROUPS, built={1})


def test_a_built_group_cannot_be_silently_rebuilt() -> None:
    """Claiming a group that already merged would redo work that is in main,
    on a branch based on a main that already contains it."""
    output = graph_json([planned(id="c/2", repo="platform", groups=[1])])

    with pytest.raises(PlannerError, match="already") as refused:
        parse_graph(output, groups=GROUPS, built={1})

    assert refused.value.units == ("c/2",)


def test_a_dependency_on_an_in_flight_unit_is_not_unknown() -> None:
    """Once part of a change is in flight the planner stops proposing it, but
    the units behind it still depend on it. Requiring every dependency to be in
    the returned graph made the change unplannable the moment its first unit
    opened — the same wrong assumption as demanding every group be claimed."""
    output = graph_json([planned(id="c/2", groups=[2, 3], depends_on=["c/1"])])

    units = parse_graph(output, groups=GROUPS, built={1}, known={"c/1"})

    assert units[0].depends_on == ("c/1",)


def test_a_dependency_on_nothing_at_all_is_still_caught() -> None:
    """The check has to keep meaning something: a unit waiting on work that
    neither exists nor is planned would wait forever."""
    output = graph_json([planned(id="c/2", groups=[2, 3], depends_on=["c/99"])])

    with pytest.raises(PlannerError, match="c/99"):
        parse_graph(output, groups=GROUPS, built={1}, known={"c/1"})


# --- the acceptance group (docs/architecture.md) ---

ACCEPTING = [
    TaskGroup(number=1, repo="platform", tier="unit-test", title="A", line=3, task_count=2),
    TaskGroup(number=2, repo="platform", tier="unit-test", title="B", line=9, task_count=2),
    TaskGroup(
        number=3,
        repo="platform",
        tier="e2e-test",
        title="Drive it",
        line=15,
        task_count=1,
        flag="acceptance",
    ),
]


def si(**overrides) -> dict:
    return planned(repo="platform", **overrides)


def test_the_acceptance_group_is_a_unit_of_its_own() -> None:
    """It exercises what the rest built; folded into an implementation unit,
    it would be written and reviewed against a surface that is half there."""
    output = graph_json(
        [si(id="c/1", groups=[1, 2]), si(id="c/2", groups=[3], tier="e2e-test", depends_on=["c/1"])]
    )
    assert [u.id for u in parse_graph(output, groups=ACCEPTING)] == ["c/1", "c/3"]

    folded = graph_json([si(id="c/1", groups=[1]), si(id="c/2", groups=[2, 3], tier="e2e-test")])
    with pytest.raises(PlannerError, match="unit of its own"):
        parse_graph(folded, groups=ACCEPTING)


def test_the_acceptance_unit_waits_for_every_unit_it_exercises() -> None:
    output = graph_json(
        [
            si(id="c/1", groups=[1]),
            si(id="c/2", groups=[2], depends_on=["c/1"]),
            si(id="c/3", groups=[3], tier="e2e-test", depends_on=["c/1"]),
        ]
    )

    with pytest.raises(PlannerError, match="c/2"):
        parse_graph(output, groups=ACCEPTING)


def test_waiting_through_another_unit_is_enough() -> None:
    output = graph_json(
        [
            si(id="c/1", groups=[1]),
            si(id="c/2", groups=[2], depends_on=["c/1"]),
            si(id="c/3", groups=[3], tier="e2e-test", depends_on=["c/2"]),
        ]
    )

    assert [u.id for u in parse_graph(output, groups=ACCEPTING)] == ["c/1", "c/2", "c/3"]


def test_groups_already_merged_need_no_edge() -> None:
    output = graph_json([si(id="c/3", groups=[3], tier="e2e-test")])

    assert parse_graph(output, groups=ACCEPTING, built={1, 2})[0].id == "c/3"


def test_the_prompt_says_how_to_place_the_acceptance_group() -> None:
    captured: dict = {}

    plan_round(
        changes={"add-marker": "## 1. [app] [unit-test] x\n"},
        in_flight=[],
        run_claude=lambda prompt: captured.setdefault("prompt", prompt) and json.dumps(GOOD),
    )

    assert "[acceptance]" in captured["prompt"]


# --- the independent group ---

INDEPENDENT = [
    TaskGroup(number=1, repo="app", tier="unit-test", title="A", line=3, task_count=2),
    TaskGroup(number=2, repo="app", tier="unit-test", title="B", line=9, task_count=2),
    TaskGroup(
        number=3,
        repo="app",
        tier="unit-test",
        title="Receiver",
        line=15,
        task_count=1,
        independent=True,
    ),
]


def test_an_independent_group_does_not_wait_for_its_changes_other_units() -> None:
    output = graph_json(
        [
            planned(id="c/1", groups=[1]),
            planned(id="c/2", groups=[2], depends_on=["c/1"]),
            planned(id="c/3", groups=[3]),
        ]
    )

    assert [u.id for u in parse_graph(output, groups=INDEPENDENT)] == ["c/1", "c/2", "c/3"]


def test_an_independent_groups_unit_cannot_depend_on_its_changes_units() -> None:
    output = graph_json(
        [
            planned(id="c/1", groups=[1]),
            planned(id="c/2", groups=[2], depends_on=["c/1"]),
            planned(id="c/3", groups=[3], depends_on=["c/2"]),
        ]
    )

    with pytest.raises(PlannerError, match="Independent"):
        parse_graph(output, groups=INDEPENDENT)


def test_an_independent_group_is_not_combined_with_another() -> None:
    output = graph_json([planned(id="c/1", groups=[1]), planned(id="c/2", groups=[2, 3])])

    with pytest.raises(PlannerError, match="Independent"):
        parse_graph(output, groups=INDEPENDENT)


NARROWING = [
    TaskGroup(
        number=1, repo="app", tier="unit-test", title="A", line=3, task_count=2, flag="contract"
    ),
    TaskGroup(number=2, repo="app", tier="unit-test", title="B", line=9, task_count=2),
    TaskGroup(
        number=3, repo="app", tier="unit-test", title="C", line=15, task_count=1, independent=True
    ),
    TaskGroup(
        number=4, repo="app", tier="unit-test", title="D", line=21, task_count=1, flag="narrow"
    ),
]


def narrowing_plan(narrow_depends_on: list[str]) -> str:
    return graph_json(
        [
            planned(id="c/1", groups=[1]),
            planned(id="c/2", groups=[2], depends_on=["c/1"]),
            planned(id="c/3", groups=[3]),
            planned(id="c/4", groups=[4], depends_on=narrow_depends_on),
        ]
    )


def test_a_narrowing_unit_waits_for_the_independent_groups_unit() -> None:
    with pytest.raises(PlannerError, match="c/3"):
        parse_graph(narrowing_plan(["c/2"]), groups=NARROWING)

    units = parse_graph(narrowing_plan(["c/2", "c/3"]), groups=NARROWING)
    assert [u.id for u in units] == ["c/1", "c/2", "c/3", "c/4"]


def test_a_narrowing_unit_need_not_wait_for_an_independent_group_already_merged() -> None:
    output = graph_json(
        [
            planned(id="c/1", groups=[1]),
            planned(id="c/2", groups=[2], depends_on=["c/1"]),
            planned(id="c/4", groups=[4], depends_on=["c/2"]),
        ]
    )

    assert parse_graph(output, groups=NARROWING, built={3})[-1].id == "c/4"


ACCEPTING_INDEPENDENT = [
    TaskGroup(number=1, repo="app", tier="unit-test", title="A", line=3, task_count=2),
    TaskGroup(
        number=2, repo="app", tier="unit-test", title="B", line=9, task_count=2, independent=True
    ),
    TaskGroup(number=3, repo="app", tier="unit-test", title="C", line=15, task_count=1),
    TaskGroup(
        number=4,
        repo="app",
        tier="e2e-test",
        title="Drive it",
        line=21,
        task_count=1,
        flag="acceptance",
    ),
]


def accepting_plan(acceptance_depends_on: list[str]) -> str:
    return graph_json(
        [
            planned(id="c/1", groups=[1]),
            planned(id="c/2", groups=[2]),
            planned(id="c/3", groups=[3], depends_on=["c/1"]),
            planned(id="c/4", groups=[4], tier="e2e-test", depends_on=acceptance_depends_on),
        ]
    )


def test_an_acceptance_unit_waits_for_the_independent_groups_unit_as_well() -> None:
    with pytest.raises(PlannerError, match="does not wait for c/2"):
        parse_graph(accepting_plan(["c/3"]), groups=ACCEPTING_INDEPENDENT)

    units = parse_graph(accepting_plan(["c/2", "c/3"]), groups=ACCEPTING_INDEPENDENT)
    assert [u.id for u in units] == ["c/1", "c/2", "c/3", "c/4"]


def test_the_prompt_says_how_to_place_an_independent_group() -> None:
    captured: dict = {}

    plan_round(
        changes={"add-marker": "## 1. [app] [unit-test] x\n"},
        in_flight=[],
        run_claude=lambda prompt: captured.setdefault("prompt", prompt) and json.dumps(GOOD),
    )

    assert "Independent:" in captured["prompt"]


# --- the ceiling on a unit's size ---


def test_the_prompt_tells_the_planner_the_ceiling() -> None:
    """The packer and the planner must say the same thing: a ceiling only the
    validator knows about spends a round on every plan that misses it."""
    activate_with(
        global_limits={"min_unit_lines": 300},
        review={"ceilings": {"auto": 1234, "light": 1234, "full": 1234}},
    )
    captured: dict = {}

    plan_round(
        changes={"add-marker": "## 1. [app] [unit-test] x\n"},
        in_flight=[],
        run_claude=lambda prompt: captured.setdefault("prompt", prompt) and json.dumps(GOOD),
    )

    assert "1234" in captured["prompt"]


def prompt_for_defaults() -> str:
    captured: dict = {}
    plan_round(
        changes={"add-marker": "## 1. [app] [unit-test] x\n"},
        in_flight=[],
        run_claude=lambda prompt: captured.setdefault("prompt", prompt) and json.dumps(GOOD),
    )
    return " ".join(captured["prompt"].split())


def test_the_prompt_carries_the_default_floor_and_ceiling() -> None:
    prompt = prompt_for_defaults()

    assert "about 400 changed lines" in prompt
    assert "over the ceiling of its review tier (`auto` 750, `light` 750, `full` 750" in prompt


def test_the_prompt_defines_what_an_estimate_counts() -> None:
    """The estimate is the only measure a plan has, so the planner is told what
    it counts: every file, deletions for code a group removes, no generated
    files, and high when unsure."""
    prompt = prompt_for_defaults()

    assert "additions plus deletions" in prompt
    assert "every file" in prompt
    for counted in ("tests", "docs", "fixtures", "changelog"):
        assert counted in prompt
    assert "excluding generated files" in prompt
    assert "removes or rewrites" in prompt
    assert "removed lines" in prompt
    assert "estimate high" in prompt


def test_a_unit_combining_groups_past_the_ceiling_is_rejected() -> None:
    """Groups 2 and 3 could have been two units; putting them in one past the
    ceiling is a planning mistake, rejected with that reason so it is re-asked."""
    output = graph_json(
        [
            planned(id="c/1", repo="platform", groups=[1], estimated_lines=100),
            planned(id="c/2", repo="app", groups=[2, 3], estimated_lines=1400),
        ]
    )

    with pytest.raises(PlannerError, match="ceiling") as rejected:
        parse_graph(output, groups=GROUPS)

    assert "c/2" in str(rejected.value)
    assert not isinstance(rejected.value, GroupTooLarge)


def test_the_ceiling_is_the_configured_one() -> None:
    activate_with(
        global_limits={"min_unit_lines": 200},
        review={"ceilings": {"auto": 600, "light": 600, "full": 600}},
    )
    output = graph_json(
        [
            planned(id="c/1", repo="platform", groups=[1], estimated_lines=100),
            planned(id="c/2", repo="app", groups=[2, 3], estimated_lines=700),
        ]
    )

    with pytest.raises(PlannerError, match="ceiling"):
        parse_graph(output, groups=GROUPS)


def test_one_group_over_the_ceiling_says_the_tasks_need_splitting() -> None:
    """No grouping can fix a single group that is too large on its own — the
    change was authored too coarsely, and the message says where."""
    output = graph_json(
        [
            planned(id="c/1", repo="platform", groups=[1], estimated_lines=1500),
            planned(id="c/2", repo="app", groups=[2, 3], estimated_lines=300),
        ]
    )

    with pytest.raises(GroupTooLarge) as rejected:
        parse_graph(output, groups=GROUPS)

    message = str(rejected.value)
    assert "group 1" in message
    assert "split" in message


LAYOUT_TEST = "tests/test_project_root.py"


def layout_tasks() -> str:
    """Fourteen `app` groups, of which groups 1, 3 and 14 each edit one test file."""
    sharing = {1, 3, 14}
    return tasks_editing(
        *[
            ("[app] [unit-test] Step", LAYOUT_TEST if n in sharing else f"src/step_{n}.py")
            for n in range(1, 15)
        ]
    )


def layout_plan(*members: list[int]) -> list:
    units = [
        planned(id=f"c/{index}", groups=numbers, estimated_lines=100)
        for index, numbers in enumerate(members, start=1)
    ]
    return parse_graph(graph_json(units), groups=groups_at(*[3] * 14), tasks=layout_tasks())


def test_the_prompt_lists_the_groups_that_name_one_test_file_as_groups_to_keep_in_a_unit() -> None:
    captured: dict = {}

    def fake_claude(prompt: str) -> str:
        captured["prompt"] = prompt
        return json.dumps({"units": []})

    plan_round(changes={"c": layout_tasks()}, in_flight=[], run_claude=fake_claude)

    paragraph = next(p for p in captured["prompt"].split("\n\n") if LAYOUT_TEST in p)
    assert "1, 3 and 14" in paragraph
    assert "share a unit" in paragraph


def test_a_split_of_a_shared_test_file_is_recorded_and_keeping_it_together_is_not() -> None:
    first, second = layout_plan(list(range(1, 14)), [14])
    (only,) = layout_plan(list(range(1, 15)))

    assert (first.id, second.id) == ("c/1", "c/14")
    assert first.split_test_files == {LAYOUT_TEST: ("c/14",)}
    assert second.split_test_files == {}
    assert only.split_test_files == {}


@pytest.mark.parametrize(
    ("tasks", "paths", "asked", "expected"),
    [
        (
            (
                "Test: a check runs with an ownership file covering all four classes: CODEOWNERS.",
                "Test: an ordinary check.",
            ),
            None,
            "light",
            "light",
        ),
        (("Test: it works. The check only reads `.github/workflows/ci.yml`.",), None, None, "auto"),
        (("Test: it works.\nReads: `CODEOWNERS`",), None, None, "auto"),
        (("Test: it works. Verify: red against `.github/workflows/ci.yml`.",), None, None, "auto"),
        (("Test: edit `CODEOWNERS` to cover it.",), ("src/app.py",), None, "auto"),
    ],
    ids=["bare-name", "only-reads", "reads-line", "verify-segment", "paths-line"],
)
def test_the_review_tier_floor_reads_what_a_group_changes(
    tasks: tuple[str, ...], paths: tuple[str, ...] | None, asked: str | None, expected: str
) -> None:
    activate_with(review={"enabled": True})
    text = "# Tasks\n\n"
    for n, task in enumerate(tasks, start=1):
        text += f"## {n}. [app] [unit-test] Group {n}\n\n- [ ] {n}.1 {task}\n\n"
    groups = groups_at(*[3] * len(tasks))
    if paths is not None:
        groups[0] = groups[0].model_copy(update={"paths": paths})
    unit = planned(id="feature/1", change="feature", groups=list(range(1, len(tasks) + 1)))
    if asked is not None:
        unit["review_tier"] = asked
    try:
        outcome = parse_graph(graph_json([unit]), groups=groups, tasks=text)[0].review_tier
    except PlannerError as error:
        outcome = f"refused: {error}"

    assert outcome == expected


FLOOR_MIGRATION = "db/migrations/0042_add_index.sql"


def floor_tasks(body: str) -> str:
    return f"# Tasks\n\n## 1. [app] [unit-test] Group 1\n\n- [ ] 1.1 {body}\n\n"


def floor_plan(flag: str, body: str, asked: str | None, **unit_fields) -> list:
    activate_with(review={"enabled": True})
    groups = [groups_at(3)[0].model_copy(update={"flag": flag})]
    unit = planned(id="feature/1", change="feature", groups=[1], **unit_fields)
    if asked is not None:
        unit["review_tier"] = asked
    return parse_graph(graph_json([unit]), groups=groups, tasks=floor_tasks(body))


@pytest.mark.parametrize(
    ("flag", "body", "asked", "tier", "reason_parts"),
    [
        ("contract", "Test: it behaves.", "full", "full", ("full", "group 1", "contract")),
        ("", "Test: it behaves.", "full", "full", ()),
        ("", f"Test: edit `{FLOOR_MIGRATION}` to add it.", None, "full", (FLOOR_MIGRATION,)),
        ("", "Test: it behaves.", None, "auto", ()),
    ],
    ids=["flagged-asks-full", "unflagged-asks-full", "protected-path", "unflagged-asks-nothing"],
)
def test_a_unit_records_its_tier_and_the_reason_of_its_floor(
    flag: str, body: str, asked: str | None, tier: str, reason_parts: tuple[str, ...]
) -> None:
    try:
        (unit,) = floor_plan(flag, body, asked)
    except PlannerError as refused:
        raise AssertionError(f"refused: {refused}") from refused

    assert unit.review_tier == tier
    assert unit.raised_from == ""
    assert bool(unit.floor_reason) == bool(reason_parts)
    for part in reason_parts:
        assert part in unit.floor_reason


def test_a_tier_below_the_floor_is_raised_and_logged_in_one_line(
    capsys: pytest.CaptureFixture[str],
) -> None:
    try:
        (unit,) = floor_plan("contract", "Test: it behaves.", "light")
    except PlannerError as refused:
        raise AssertionError(f"refused: {refused}") from refused

    lines = [line for line in capsys.readouterr().out.splitlines() if "feature/1" in line]
    assert unit.review_tier == "full"
    assert unit.raised_from == "light"
    assert len(lines) == 1
    for part in ("light", "full", "contract"):
        assert part in lines[0]


def test_a_raised_unit_over_the_full_ceiling_is_refused_for_its_size() -> None:
    activate_with(review={"enabled": True})
    over = ceilings_in_effect(active().repos["app"], active()).full + 1

    with pytest.raises(PlannerError, match="ceiling"):
        floor_plan("contract", "Test: it behaves.", "light", estimated_lines=over)


def test_the_prompt_says_a_tier_below_the_floor_is_raised_not_refused() -> None:
    activate_with(review={"enabled": True})
    paragraph = next(
        p for p in build_prompt({}, []).split("\n\n") if p.lstrip().startswith("Review tier:")
    )

    assert "raised" in paragraph
    assert "refused" not in paragraph


def heading_of(prompt: str, number: int) -> str:
    return next(line for line in prompt.splitlines() if line.startswith(f"## {number}."))


@pytest.mark.parametrize(
    ("fields", "parts", "absent"),
    [
        ({"flag": "contract"}, ("full", "contract", "{full_ceiling}"), ()),
        ({"code_free": True}, ("no_code", "tests_and_code"), ()),
        ({"tier": "e2e-test"}, ("tests_only",), ()),
        ({}, ("auto", "tests_and_code"), (" — ",)),
        ({"declared_mode": "refactor"}, ("refactor", "fixed"), ()),
    ],
    ids=["contract", "code-free", "e2e", "unflagged", "declared"],
)
def test_the_heading_of_a_group_shows_its_floors(
    fields: dict, parts: tuple[str, ...], absent: tuple[str, ...]
) -> None:
    activate_with(review={"enabled": True})
    group = groups_at(3)[0].model_copy(update=fields)
    tasks = f"# Tasks\n\n## 1. [app] [{group.tier}] G1\n\n- [ ] 1.1 Test: it.\n"
    figure = str(ceilings_in_effect(None, active()).full)

    heading = heading_of(build_prompt({"feature": tasks}, [], groups=[group]), 1)

    assert "floors" in heading
    for part in parts:
        assert part.replace("{full_ceiling}", figure) in heading
    for part in absent:
        assert part not in heading


def test_the_heading_of_a_group_a_started_unit_builds_shows_who_builds_it_not_floors() -> None:
    activate_with(review={"enabled": True})
    tasks = (
        "# Tasks\n\n## 1. [app] [unit-test] G1\n\n- [ ] 1.1 Test: it.\n\n"
        "## 2. [app] [unit-test] G2\n\n- [ ] 2.1 Test: it.\n"
    )
    unit = stored_unit("feature/1", change="feature", groups=(1,), state=FAILED)

    prompt = build_prompt(
        {"feature": tasks}, [in_flight_item(unit, [unit])], groups=groups_at(3, 3)
    )

    built, open_group = heading_of(prompt, 1), heading_of(prompt, 2)
    assert "(built by" in built
    assert "floors" not in built
    assert "floors" in open_group


def test_the_group_modes_paragraph_says_each_heading_shows_its_floors() -> None:
    activate_with(review={"enabled": True})
    paragraph = next(
        p for p in build_prompt({}, []).split("\n\n") if p.lstrip().startswith("Group modes:")
    )

    for word in ("heading", "floors", "allowed"):
        assert word in paragraph


REFUSED_PATHS = ("docs/guide.md", "docs/setup.md", "tests/test_feature.py")


@pytest.mark.parametrize(
    ("fields", "asked", "parts"),
    [
        (
            {"test_code": True, "paths": REFUSED_PATHS},
            "tests_and_code",
            (
                "unit feature/1",
                "group 1",
                "tests_only",
                *REFUSED_PATHS,
                "Tests: required",
                "tasks.md",
            ),
        ),
        ({"code_free": True}, "tests_only", ("no_code", "tests_and_code")),
        ({}, "no_code", ("tests_and_code", "refactor", "Paths:")),
        (
            {"code_free": True, "tests_required": True},
            "no_code",
            ("tests_and_code", "Tests: required"),
        ),
        ({"tier": "e2e-test"}, "tests_and_code", ("tests_only",)),
    ],
    ids=["test-file-and-documents", "documents-only", "ordinary", "tests-required", "e2e"],
)
def test_a_refused_mode_says_the_floor_the_cause_and_the_fix(
    fields: dict, asked: str, parts: tuple[str, ...]
) -> None:
    activate_with(review={"enabled": True})
    group = groups_at(3)[0].model_copy(update=fields)
    unit = planned(id="feature/1", change="feature", groups=[1], group_modes={"1": asked})

    try:
        parse_graph(graph_json([unit]), groups=[group], tasks=floor_tasks("Test: it behaves."))
    except PlannerError as refused:
        message = str(refused)
    else:
        raise AssertionError("the mode was accepted")

    assert f"asks for mode {asked!r} for group 1" in message
    for part in ("feature", group.title, *parts):
        assert part in message
