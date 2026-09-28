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

from agent_build_kit.pipeline.planner import PlannerError, parse_graph, plan_round
from agent_build_kit.pipeline.work_graph import TaskGroup

GOOD = {
    "units": [
        {
            "id": "add-marker/1",
            "change": "add-marker",
            "title": "Register the marker",
            "repo": "platform",
            "tier": "tier1",
            "depends_on": [],
            "estimated_lines": 120,
            "groups": [1],
        },
        {
            "id": "add-marker/2",
            "change": "add-marker",
            "title": "Register it in app",
            "repo": "app",
            "tier": "tier1",
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
        changes={"add-marker": "## 1. [platform] [tier1] Register the marker\n"},
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
        changes={"add-marker": "## 1. [app] [tier1] x\n"},
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
    units = plan_round(
        changes={}, in_flight=[], run_claude=lambda prompt: json.dumps({"units": []})
    )

    assert units == []


GROUPS = [
    TaskGroup(number=1, repo="platform", tier="tier1", title="A", line=3, task_count=2),
    TaskGroup(number=2, repo="app", tier="tier1", title="B", line=9, task_count=2),
    TaskGroup(number=3, repo="app", tier="tier1", title="C", line=15, task_count=1),
]


def graph_json(units: list[dict]) -> str:
    return json.dumps({"units": units})


def planned(**overrides) -> dict:
    return {
        "id": "c/1",
        "change": "c",
        "title": "A unit",
        "repo": "app",
        "tier": "tier1",
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
    assert parse_graph(graph_json([planned()]))[0].id == "c/1"


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

    with pytest.raises(PlannerError, match="already"):
        parse_graph(output, groups=GROUPS, built={1})


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
    TaskGroup(number=1, repo="platform", tier="tier1", title="A", line=3, task_count=2),
    TaskGroup(number=2, repo="platform", tier="tier1", title="B", line=9, task_count=2),
    TaskGroup(
        number=3,
        repo="platform",
        tier="tier2",
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
        [si(id="c/1", groups=[1, 2]), si(id="c/2", groups=[3], tier="tier2", depends_on=["c/1"])]
    )
    assert [u.id for u in parse_graph(output, groups=ACCEPTING)] == ["c/1", "c/2"]

    folded = graph_json([si(id="c/1", groups=[1]), si(id="c/2", groups=[2, 3], tier="tier2")])
    with pytest.raises(PlannerError, match="acceptance"):
        parse_graph(folded, groups=ACCEPTING)


def test_the_acceptance_unit_waits_for_every_unit_it_exercises() -> None:
    output = graph_json(
        [
            si(id="c/1", groups=[1]),
            si(id="c/2", groups=[2], depends_on=["c/1"]),
            si(id="c/3", groups=[3], tier="tier2", depends_on=["c/1"]),
        ]
    )

    with pytest.raises(PlannerError, match="c/2"):
        parse_graph(output, groups=ACCEPTING)


def test_waiting_through_another_unit_is_enough() -> None:
    output = graph_json(
        [
            si(id="c/1", groups=[1]),
            si(id="c/2", groups=[2], depends_on=["c/1"]),
            si(id="c/3", groups=[3], tier="tier2", depends_on=["c/2"]),
        ]
    )

    assert [u.id for u in parse_graph(output, groups=ACCEPTING)] == ["c/1", "c/2", "c/3"]


def test_groups_already_merged_need_no_edge() -> None:
    output = graph_json([si(id="c/3", groups=[3], tier="tier2")])

    assert parse_graph(output, groups=ACCEPTING, built={1, 2})[0].id == "c/3"


def test_the_prompt_says_how_to_place_the_acceptance_group() -> None:
    captured: dict = {}

    plan_round(
        changes={"add-marker": "## 1. [app] [tier1] x\n"},
        in_flight=[],
        run_claude=lambda prompt: captured.setdefault("prompt", prompt) and json.dumps(GOOD),
    )

    assert "[acceptance]" in captured["prompt"]
