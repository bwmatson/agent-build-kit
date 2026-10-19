"""`abk retire` says what becomes of each group the unit carries, and a group nobody builds
needs a reason and is planned again (spec: a-started-unit-keeps-its-groups)."""

from __future__ import annotations

from tests.retire_scene import Scene, scene  # noqa: F401

UNIT = "feature/3"


def test_groups_built_in_a_merged_unit_need_no_reason(scene: Scene, capsys) -> None:  # noqa: F811
    scene.add(UNIT, groups=(1,))
    scene.built_elsewhere(UNIT, by="feature/2")

    code, out = scene.retire(capsys, UNIT)

    assert code == 0, out
    assert scene.unit(UNIT).state == "retired"
    assert "feature/2" in out and "merged" in out


def test_a_group_no_unit_builds_is_refused_without_a_reason(
    scene: Scene,  # noqa: F811
    capsys,
) -> None:
    scene.add(UNIT, groups=(2,))
    before = scene.snapshot()

    code, out = scene.retire(capsys, UNIT)

    assert code == 1
    assert "group 2" in out and "feature" in out and "--reason" in out
    assert scene.snapshot() == before


def test_a_reason_releases_the_group_and_forgets_the_change_s_plan(
    scene: Scene,  # noqa: F811
    capsys,
) -> None:
    scene.add(UNIT, groups=(2,))
    scene.record("feature")
    scene.record("other")

    code, out = scene.retire(capsys, UNIT, "--reason", "narrowed")

    assert code == 0
    assert scene.unit(UNIT).state == "retired"
    released = [line for line in out.splitlines() if "group 2" in line]
    assert released and "released" in released[0]
    assert "feature" not in scene.records, "the next tick plans the change"
    assert "other" in scene.records, "another change's plan is not forgotten"


def test_a_refused_plan_that_names_the_unit_is_forgotten_too(
    scene: Scene,  # noqa: F811
    capsys,
) -> None:
    scene.add(UNIT, groups=(1,))
    scene.built_elsewhere(UNIT)
    scene.record("feature")
    scene.record("other", ok=False, attempts=3, owned=[UNIT])

    code, _ = scene.retire(capsys, UNIT)

    assert code == 0
    assert "other" not in scene.records
    assert "feature" in scene.records, "no group was released, so its plan stands"


def test_the_dependents_that_stop_waiting_are_listed_with_their_states(
    scene: Scene,  # noqa: F811
    capsys,
) -> None:
    scene.add(UNIT, groups=(1,))
    scene.built_elsewhere(UNIT)
    scene.add("feature/4", branch=False, depends_on=(UNIT,))
    scene.add("feature/5", "failed", branch=False, depends_on=(UNIT,))

    code, out = scene.retire(capsys, UNIT)

    assert code == 0
    lines = out.splitlines()
    assert any("feature/4" in line and "planned" in line for line in lines)
    assert any("feature/5" in line and "failed" in line for line in lines)
