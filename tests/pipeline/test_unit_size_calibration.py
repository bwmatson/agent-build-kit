"""Estimates are corrected by what units of the same kind landed at.

The ratio is a pure function of the stored units; the rest runs through the
planner's check, `plan_all`, the unit store and `abk status` with the planner's
runtime answering in the raw shape a model sends.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.config import WorkspaceConfig
from agent_build_kit.pipeline.planner import GroupTooLarge, PlannerError, parse_plan, plan_round
from agent_build_kit.pipeline.unit_size import (
    Calibration,
    Kind,
    calibration,
    calibrations,
    kind_of,
    sample_count,
)
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import IN_REVIEW
from agent_build_kit.pipeline.work_graph import TaskGroup
from tests.calibration_support import (
    CONFIGURED,
    limits,
    new_unit,
    planner,
    project,
    run_of,
    sample,
    tasks_md,
    write_store,
)
from tests.conftest import make_installation
from tests.factories import stored_unit

APP = Kind(repo="app", tier="unit-test")
# --- the ratio ---------------------------------------------------------------


def test_the_ratio_is_the_median_and_units_with_nothing_to_compare_are_not_samples() -> None:
    limits(calibration_shrink=0)
    units = [
        *run_of([1.2, 1.4, 1.6, 1.8, 2.0]),
        sample(9.0, at=50, estimate=0, actual=900),
        sample(9.0, at=51).model_copy(update={"actual_lines": None}),
        sample(9.0, at=52, state=IN_REVIEW),
    ]

    assert sample_count(units, APP) == 5
    assert calibration(units, APP) == pytest.approx(1.6)


def test_five_samples_at_these_ratios_carry_half_the_gap_at_the_default_shrink() -> None:
    limits()

    assert calibration(run_of([1.2, 1.4, 1.6, 1.8, 2.0]), APP) == pytest.approx(1.3)


def test_the_newest_merged_units_up_to_the_window_are_the_samples() -> None:
    limits(calibration_window=3, calibration_min=3, calibration_shrink=0)
    # Listed newest first, to show the order is the time each merged.
    newest = [sample(2.0, at=at) for at in (30, 20, 10)]
    older = [sample(1.0, at=at) for at in (5, 4, 3, 2, 1)]

    assert sample_count([*newest, *older], APP) == 3
    assert calibration([*newest, *older], APP) == pytest.approx(2.0)


def test_a_single_extreme_sample_is_read_at_the_top_of_the_clamp() -> None:
    limits(calibration_shrink=0, calibration_max=10.0)
    # Sorted, the middle two are 2.0 and 8.66; clamped to 4.0 they average 3.0, not 5.33.
    units = run_of([1.0, 2.0, 8.66, 8.66])

    assert calibration(units, APP) == pytest.approx(3.0)


def test_one_of_eleven_at_8_66_is_counted_as_4_0() -> None:
    limits(calibration_shrink=0, calibration_max=10.0)
    units = run_of([4.0] * 6 + [8.66] + [1.0] * 4)

    assert calibration(units, APP) == pytest.approx(4.0)


def test_a_sample_at_a_tenth_of_its_estimate_is_read_at_the_bottom_of_the_clamp() -> None:
    limits(calibration_shrink=0, calibration_max=10.0)
    # The middle two are 0.1 and 3.0: clamped to 0.5 they average 1.75, not 1.55.
    units = run_of([0.1, 0.1, 3.0, 3.0])

    assert calibration(units, APP) == pytest.approx(1.75)


@pytest.mark.parametrize(("count", "expected"), [(5, 1.5), (20, 1.8)])
def test_the_gap_from_one_is_carried_by_n_over_n_plus_shrink(count: int, expected: float) -> None:
    limits(calibration_max=3.0)

    assert calibration(run_of([2.0] * count), APP) == pytest.approx(expected)


def test_a_shrink_of_zero_uses_the_median_whole() -> None:
    limits(calibration_shrink=0)

    assert calibration(run_of([2.0] * 5), APP) == pytest.approx(2.0)


def test_fewer_samples_than_the_minimum_give_exactly_one() -> None:
    limits(calibration_shrink=0)

    assert calibration(run_of([2.0, 2.0]), APP) == 1.0


def test_units_that_landed_under_their_estimates_are_never_a_ratio_below_one() -> None:
    limits(calibration_shrink=0)

    assert calibration(run_of([0.62] * 5), APP) == 1.0


def test_the_ratio_never_passes_the_configured_maximum() -> None:
    limits(calibration_shrink=0, calibration_max=2.5)

    assert calibration(run_of([4.0] * 5), APP) == 2.5


def test_kinds_get_their_ratios_from_their_own_samples() -> None:
    limits(calibration_shrink=0)
    units = [
        *run_of([2.0] * 3),
        *run_of([3.0] * 3, tier="e2e-test"),
        *run_of([1.5] * 3, repo="platform"),
        *run_of([2.5] * 3, flag="contract"),
    ]

    assert calibration(units, APP) == pytest.approx(2.0)
    assert calibration(units, Kind(repo="app", tier="e2e-test")) == pytest.approx(3.0)
    assert calibration(units, Kind(repo="platform", tier="unit-test")) == pytest.approx(1.5)
    assert calibration(units, Kind(repo="app", tier="unit-test", flag="contract")) == pytest.approx(
        2.5
    )
    assert calibration(units, Kind(repo="app", tier="unit-test", flag="narrow")) == 1.0


def test_a_units_kind_is_its_repo_tier_and_flag() -> None:
    unit = stored_unit("feature/1", repo="platform", tier="e2e-test", flag="narrow")

    assert kind_of(unit) == Kind(repo="platform", tier="e2e-test", flag="narrow")
    assert kind_of(stored_unit("feature/2")) == Kind(repo="app", tier="unit-test", flag="")


def test_calibrations_lists_each_kind_with_its_ratio_and_sample_count() -> None:
    limits(calibration_shrink=0)
    units = [*run_of([2.0] * 4), *run_of([3.0] * 3, tier="e2e-test")]

    found = calibrations(units)

    assert found[APP].ratio == pytest.approx(2.0)
    assert found[APP].samples == 4
    assert found[Kind(repo="app", tier="e2e-test")].samples == 3


# The twenty newest unit-test samples of the design's worked example, estimate then landed size,
# oldest first, and the e2e-test pair.
UNIT_TEST = [
    (600, 1115), (700, 1175), (450, 853), (550, 551), (450, 719),
    (600, 641), (500, 776), (600, 5198), (600, 1000), (400, 386),
    (350, 424), (300, 715), (250, 176), (650, 2053), (450, 510),
    (450, 712), (600, 1222), (450, 1016), (550, 791), (700, 1906),
]  # fmt: skip
E2E = [(650, 479), (250, 116)]


def test_the_worked_example_gives_1_51_at_unit_test_and_one_at_e2e() -> None:
    limits()
    older = [sample(1.0, at=at) for at in range(-11, 0)]
    newest = [
        sample(0, at=at, estimate=estimate, actual=landed)
        for at, (estimate, landed) in enumerate(UNIT_TEST)
    ]
    e2e = [
        sample(0, at=at, tier="e2e-test", estimate=estimate, actual=landed)
        for at, (estimate, landed) in enumerate(E2E)
    ]

    units = [*older, *newest, *e2e]

    assert sample_count(units, APP) == 20
    assert calibration(units, APP) == pytest.approx(1.5058, abs=2e-3)
    assert calibration(units, Kind(repo="app", tier="e2e-test")) == 1.0


def test_with_calibration_off_every_ratio_is_one() -> None:
    limits(calibrate_estimates=False, calibration_shrink=0)
    units = run_of([2.0] * 5)

    assert calibration(units, APP) == 1.0


# --- the plan check ----------------------------------------------------------

GROUPS = [
    TaskGroup(number=1, repo="app", tier="unit-test", title="A", line=3, task_count=2),
    TaskGroup(number=2, repo="app", tier="unit-test", title="B", line=9, task_count=2),
]
RATIO_1_5 = {APP: Calibration(ratio=1.5, samples=20)}


def graph(*units: dict) -> str:
    body = [
        {"change": "c", "title": "A unit", "repo": "app", "tier": "unit-test", **unit}
        for unit in units
    ]
    return json.dumps({"units": body})


def test_a_unit_over_the_ceiling_only_after_calibration_is_rejected_naming_the_figures() -> None:
    limits(max_unit_lines=750)
    output = graph({"id": "c/1", "groups": [1, 2], "estimated_lines": 600})

    with pytest.raises(PlannerError, match="ceiling") as rejected:
        parse_plan(output, groups=GROUPS, calibrations=RATIO_1_5)

    message = str(rejected.value)
    assert not isinstance(rejected.value, GroupTooLarge)
    for named in ("c/1", "600", "900", "1.5", "20"):
        assert named in message


def test_a_unit_under_the_ceiling_after_calibration_is_accepted() -> None:
    limits(max_unit_lines=750)
    output = graph({"id": "c/1", "groups": [1, 2], "estimated_lines": 480})

    plan = parse_plan(output, groups=GROUPS, calibrations=RATIO_1_5)

    assert [u.id for u in plan.units] == ["c/1"]


def test_a_single_group_over_the_ceiling_only_after_calibration_is_too_large() -> None:
    limits(max_unit_lines=750)
    output = graph(
        {"id": "c/1", "groups": [1], "estimated_lines": 600},
        {"id": "c/2", "groups": [2], "estimated_lines": 100, "depends_on": ["c/1"]},
    )

    with pytest.raises(GroupTooLarge) as rejected:
        parse_plan(output, groups=GROUPS, calibrations=RATIO_1_5)

    assert "group 1" in str(rejected.value)
    assert "split" in str(rejected.value)


def test_another_kinds_ratio_does_not_apply() -> None:
    limits(max_unit_lines=750)
    output = graph({"id": "c/1", "groups": [1, 2], "estimated_lines": 600})
    other = {Kind(repo="app", tier="e2e-test"): Calibration(ratio=1.5, samples=20)}

    assert parse_plan(output, groups=GROUPS, calibrations=other).units


def test_with_calibration_off_the_raw_estimate_is_checked() -> None:
    limits(max_unit_lines=750, calibrate_estimates=False)
    output = graph({"id": "c/1", "groups": [1, 2], "estimated_lines": 600})

    assert parse_plan(output, groups=GROUPS, calibrations=RATIO_1_5).units


# --- the planning prompt -----------------------------------------------------


def prompt_with(found: dict[Kind, Calibration] | None) -> str:
    captured: dict = {}
    plan_round(
        changes={"c": "## 1. [app] [unit-test] x\n"},
        in_flight=[],
        calibrations=found,
        run_claude=lambda prompt: captured.setdefault("prompt", prompt) and '{"units": []}',
    )
    return " ".join(captured["prompt"].split())


def test_the_prompt_lists_each_kind_above_one_with_its_ratio_and_samples() -> None:
    limits()
    found = {
        APP: Calibration(ratio=1.51, samples=20),
        Kind(repo="app", tier="e2e-test"): Calibration(ratio=1.0, samples=2),
        Kind(repo="platform", tier="unit-test", flag="contract"): Calibration(ratio=2.2, samples=6),
    }

    prompt = prompt_with(found)

    assert "1.51" in prompt and "20 samples" in prompt
    assert "2.2" in prompt and "contract" in prompt
    assert "raw" in prompt
    assert "multipl" in prompt
    assert "e2e-test" not in prompt.split("raw", 1)[1].split("Changes ready", 1)[0]


def test_the_prompt_carries_no_ratios_when_none_is_above_one_or_calibration_is_off() -> None:
    limits()
    nothing = prompt_with({APP: Calibration(ratio=1.0, samples=2)})
    limits(calibrate_estimates=False)
    off = prompt_with({APP: Calibration(ratio=1.51, samples=20)})

    for prompt in (nothing, off):
        assert "1.51" not in prompt
        assert "multipl" not in prompt
        assert "raw" not in prompt


# --- through planning --------------------------------------------------------


def test_a_plan_over_the_ceiling_after_calibration_is_re_asked_within_the_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    limits(calibration_shrink=0)
    inst, store = project(tmp_path, tasks_md("", ""), run_of([1.5] * 20))
    runtime = planner(
        monkeypatch,
        {"units": [new_unit("feature/1", [1, 2], 600)]},
        {
            "units": [
                new_unit("feature/1", [1], 300),
                new_unit("feature/2", [2], 300, depends_on=["feature/1"]),
            ]
        },
    )

    cli.plan_all(inst, store=store)
    first = capsys.readouterr().out
    cli.plan_all(inst, store=store)

    assert "1.5" in first and "20" in first and "900" in first
    assert len(runtime.requests) == 2
    assert {u.id for u in store.all() if u.change == "feature"} == {"feature/1", "feature/2"}


def test_a_first_stored_unit_keeps_its_flag_and_both_figures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    limits(calibration_shrink=0)
    samples = [*run_of([2.0] * 3, flag="contract"), *run_of([1.0] * 3)]
    inst, store = project(tmp_path, tasks_md("contract", "narrow"), samples)
    planner(
        monkeypatch,
        {
            "units": [
                new_unit("feature/1", [1], 100),
                new_unit("feature/2", [2], 100, depends_on=["feature/1"]),
            ]
        },
    )

    cli.plan_all(inst, store=store)

    unit = store.get("feature/1")
    assert unit.flag == "contract"
    assert unit.estimated_lines == 100
    assert unit.calibrated_lines == 200


def test_a_unit_carrying_an_unflagged_group_first_takes_the_flag_of_its_flagged_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    limits(calibration_shrink=0)
    samples = [*run_of([2.0] * 3, flag="contract"), *run_of([1.0] * 3)]
    inst, store = project(tmp_path, tasks_md("", "contract", "narrow"), samples)
    planner(
        monkeypatch,
        {
            "units": [
                new_unit("feature/1", [1, 2], 100),
                new_unit("feature/2", [3], 100, depends_on=["feature/1"]),
            ]
        },
    )

    cli.plan_all(inst, store=store)

    unit = store.get("feature/1")
    assert unit.flag == "contract"
    assert unit.calibrated_lines == 200


def test_the_plan_check_uses_the_ratio_of_the_first_flagged_group_a_unit_carries() -> None:
    limits(max_unit_lines=750)
    groups = [
        TaskGroup(number=1, repo="app", tier="unit-test", title="A", line=3, task_count=2),
        TaskGroup(
            number=2, repo="app", tier="unit-test", title="B", line=9, task_count=2, flag="contract"
        ),
        TaskGroup(
            number=3, repo="app", tier="unit-test", title="C", line=15, task_count=2, flag="narrow"
        ),
    ]
    output = graph(
        {"id": "c/1", "groups": [1, 2], "estimated_lines": 400},
        {"id": "c/2", "groups": [3], "estimated_lines": 100, "depends_on": ["c/1"]},
    )
    contract = {
        Kind(repo="app", tier="unit-test", flag="contract"): Calibration(ratio=2.0, samples=9)
    }
    plain = {APP: Calibration(ratio=2.0, samples=9)}

    with pytest.raises(PlannerError, match="ceiling"):
        parse_plan(output, groups=groups, calibrations=contract)
    assert parse_plan(output, groups=groups, calibrations=plain).units


def test_a_unit_with_no_flagged_group_has_the_empty_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    limits(calibration_shrink=0)
    inst, store = project(tmp_path, tasks_md(""), run_of([2.0] * 3))
    planner(monkeypatch, {"units": [new_unit("feature/1", [1], 100)]})

    cli.plan_all(inst, store=store)

    unit = store.get("feature/1")
    assert unit.flag == ""
    assert unit.calibrated_lines == 200


def test_with_calibration_off_nothing_is_stored_and_the_prompt_carries_no_ratios(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    limits(calibrate_estimates=False, calibration_shrink=0)
    inst, store = project(tmp_path, tasks_md("", ""), run_of([1.5] * 20))
    runtime = planner(monkeypatch, {"units": [new_unit("feature/1", [1, 2], 600)]})

    cli.plan_all(inst, store=store)

    unit = store.get("feature/1")
    assert unit.calibrated_lines is None
    assert unit.estimated_lines == 600
    assert "multipl" not in " ".join(runtime.requests[0].prompt.split())


def test_the_prompt_a_round_sends_gives_the_ratio_and_samples(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    limits(calibration_shrink=0)
    inst, store = project(tmp_path, tasks_md(""), run_of([1.5] * 20))
    runtime = planner(monkeypatch, {"units": [new_unit("feature/1", [1], 100)]})

    cli.plan_all(inst, store=store)

    prompt = " ".join(runtime.requests[0].prompt.split())
    assert "1.5" in prompt and "20 samples" in prompt


def onto_base(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **config: Any) -> UnitStore:
    limits(calibration_shrink=0, **config)
    base = stored_unit("base/1", change="base", groups=(1,), estimated_lines=300)
    inst, store = project(tmp_path, tasks_md(""), [base, *run_of([2.0] * 20)])
    base_dir = inst.changes_dir / "base"
    base_dir.mkdir(parents=True)
    (base_dir / "tasks.md").write_text(tasks_md(""))
    # `base` is planned as it stands, so only `feature` is planned and joined.
    digest = hashlib.sha256(cli.specification(base_dir / "tasks.md").encode()).hexdigest()
    (tmp_path / "planned.json").write_text(
        json.dumps({"base": {"hash": digest, "attempts": 0, "ok": True}})
    )
    planned = {"units": [], "joins": [
        {"onto": "base/1", "change": "feature", "groups": [1], "estimated_lines": 200}
    ]}  # fmt: skip
    planner(monkeypatch, planned)
    return store


def test_a_join_whose_calibrated_sum_passes_the_ceiling_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    store = onto_base(tmp_path, monkeypatch)

    cli.plan_all(make_installation_of(tmp_path), store=store)

    assert store.get("base/1").estimated_lines == 300
    assert "ceiling" in capsys.readouterr().out


def test_the_same_join_is_made_when_calibration_is_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = onto_base(tmp_path, monkeypatch, calibrate_estimates=False)

    cli.plan_all(make_installation_of(tmp_path), store=store)

    assert store.get("base/1").estimated_lines == 500


def make_installation_of(root: Path):
    return make_installation(
        root,
        planning={"state_dir": ".", "worktree_root": str(root.parent / "trees")},
        limits=CONFIGURED,
    )


# --- the stored unit ---------------------------------------------------------


def test_a_started_unit_keeps_its_calibrated_figure_where_an_unstarted_one_is_set(
    tmp_path: Path,
) -> None:
    limits(calibration_shrink=0)
    running = stored_unit("feature/1", change="feature", estimated_lines=600)
    waiting = stored_unit("feature/2", change="feature", estimated_lines=600, groups=(2,))
    store = write_store(
        tmp_path,
        [running, waiting, *run_of([3.0] * 5)],
        **{
            "feature/1": {"calibrated_lines": 903, "state": "running", "branch": "spec/feature/1"},
            "feature/2": {"calibrated_lines": 903},
        },
    )

    store.set_calibration("feature/1", "", 1800)
    store.set_calibration("feature/2", "", 1800)
    store.upsert([running], change="feature")
    store.set_state("feature/1", IN_REVIEW, pr=1, branch="spec/feature/1")

    assert store.get("feature/1").calibrated_lines == 903
    assert store.get("feature/1").estimated_lines == 600
    assert store.get("feature/2").calibrated_lines == 1800


def test_a_round_that_plans_other_groups_leaves_a_started_units_figure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    limits(calibration_shrink=0)
    running = stored_unit("feature/1", change="feature", estimated_lines=600, groups=(1,))
    inst, store = project(
        tmp_path,
        tasks_md("", ""),
        [running, *run_of([3.0] * 5)],
        **{"feature/1": {"calibrated_lines": 903, "state": "running", "branch": "spec/feature/1"}},
    )
    planner(monkeypatch, {"units": [new_unit("feature/2", [2], 200, depends_on=["feature/1"])]})

    cli.plan_all(inst, store=store)

    assert store.get("feature/1").calibrated_lines == 903
    assert store.get("feature/2").calibrated_lines == 600


def test_a_sample_uses_the_planners_estimate_not_the_calibrated_figure(tmp_path: Path) -> None:
    limits(calibration_shrink=0)
    units = run_of([2.0] * 3)
    extra = {u.id: {"calibrated_lines": 150} for u in units}
    store = write_store(tmp_path, units, **extra)

    assert calibration(store.all(), APP) == pytest.approx(2.0)


def test_a_store_written_before_the_fields_existed_loads_without_them(tmp_path: Path) -> None:
    store = write_store(tmp_path, [stored_unit("feature/1")])

    unit = store.get("feature/1")

    assert unit.flag == ""
    assert unit.calibrated_lines is None
    assert kind_of(unit) == Kind(repo="app", tier="unit-test", flag="")


@pytest.mark.parametrize("bad", [0, -5, 1.5, "903"])
def test_a_calibrated_figure_that_is_not_a_positive_whole_number_fails_the_load(
    tmp_path: Path, bad: Any
) -> None:
    store = write_store(
        tmp_path, [stored_unit("feature/1")], **{"feature/1": {"calibrated_lines": bad}}
    )

    with pytest.raises(ValueError, match="calibrated_lines"):
        store.all()


def test_a_flag_that_is_not_one_of_the_three_fails_the_load(tmp_path: Path) -> None:
    store = write_store(tmp_path, [stored_unit("feature/1")], **{"feature/1": {"flag": "bogus"}})

    with pytest.raises(ValueError, match="flag"):
        store.all()


# --- the status command ------------------------------------------------------


def status_output(tmp_path: Path, capsys: pytest.CaptureFixture[str], **extra: dict) -> list[str]:
    inst = make_installation(
        tmp_path, planning={"state_dir": ".", "worktree_root": str(tmp_path.parent / "trees")}
    )
    write_store(
        tmp_path,
        [
            stored_unit("a/1", change="a", estimated_lines=600),
            stored_unit("b/1", change="b", estimated_lines=300),
        ],
        **extra,
    )
    capsys.readouterr()
    cli.cmd_status(argparse.Namespace(), inst)
    output = capsys.readouterr()
    return (output.out + output.err).splitlines()


def test_status_lists_the_estimate_and_the_calibrated_figure_of_a_unit_that_has_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    lines = status_output(tmp_path, capsys, **{"a/1": {"calibrated_lines": 903}})

    mine = [line for line in lines if "a/1" in line and "calibrated" in line]
    assert len(mine) == 1
    assert "estimated 600 (calibrated 903)" in mine[0]
    assert not [line for line in lines if "b/1" in line and "calibrated" in line]


def test_status_is_unchanged_for_units_with_no_calibrated_figure(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    lines = status_output(tmp_path, capsys)

    assert not [line for line in lines if "calibrated" in line]


# --- configuration -----------------------------------------------------------


def limits_config(**overrides: Any):
    return WorkspaceConfig.model_validate({"global_limits": overrides}).global_limits


def test_the_six_keys_have_their_defaults() -> None:
    config = limits_config()

    assert config.calibrate_estimates is True
    assert config.calibration_window == 20
    assert config.calibration_min == 3
    assert config.calibration_shrink == 5
    assert tuple(config.calibration_sample_clamp) == (0.5, 4.0)
    assert config.calibration_max == 3.0


@pytest.mark.parametrize(
    ("key", "overrides"),
    [
        ("calibration_min", {"calibration_window": 5, "calibration_min": 6}),
        ("calibration_sample_clamp", {"calibration_sample_clamp": [1.5, 4.0]}),
        ("calibration_sample_clamp", {"calibration_sample_clamp": [0.5, 0.8]}),
        ("calibration_max", {"calibration_max": 0.9}),
        ("calibration_shrink", {"calibration_shrink": -1}),
    ],
)
def test_a_bad_value_fails_to_load_naming_the_key(key: str, overrides: dict) -> None:
    with pytest.raises(ValidationError, match=key):
        limits_config(**overrides)
