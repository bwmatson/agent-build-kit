"""A revert of an auto-landed unit demotes its class; a person's merge that is reverted does not."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.pipeline import demotion_record
from tests.demotion_triggers_support import NOW, evaluate, merged_unit, record


def test_a_reverted_auto_landed_unit_demotes_its_class_with_the_trigger_and_the_unit(
    tmp_path: Path,
) -> None:
    said: list[str] = []

    demoted = evaluate(
        tmp_path,
        [merged_unit("feature/1", auto=True)],
        {"feature/1": record("reverted", auto=True)},
        said=said,
    )

    assert said == ["docs: demoted by revert on feature/1"]
    assert list(demoted) == ["docs"]
    assert [(t["trigger"], t["unit"]) for t in demoted["docs"]["triggers"]] == [
        ("revert", "feature/1")
    ]


def test_a_reverted_unit_a_person_merged_demotes_nothing(tmp_path: Path) -> None:
    demoted = evaluate(
        tmp_path, [merged_unit("feature/1")], {"feature/1": record("reverted", auto=False)}
    )

    assert demoted == {}


def test_an_auto_landed_unit_not_reverted_demotes_nothing(tmp_path: Path) -> None:
    demoted = evaluate(
        tmp_path, [merged_unit("feature/1", auto=True)], {"feature/1": record("clean", auto=True)}
    )

    assert demoted == {}


def test_evaluating_again_once_demoted_adds_no_second_demotion(tmp_path: Path) -> None:
    units = [merged_unit("feature/1", auto=True)]
    records = {"feature/1": record("reverted", auto=True)}
    evaluate(tmp_path, units, records)

    demoted = evaluate(tmp_path, units, records)

    assert list(demoted) == ["docs"]
    assert len(demoted["docs"]["triggers"]) == 1


def test_a_lift_is_not_undone_by_the_revert_it_was_made_over(tmp_path: Path) -> None:
    units = [merged_unit("feature/1", auto=True)]
    records = {"feature/1": record("reverted", auto=True)}
    evaluate(tmp_path, units, records)
    demotion_record.lift(tmp_path / demotion_record.DEMOTIONS, unit_class="docs", at=NOW)

    demoted = evaluate(tmp_path, units, records)

    assert demoted["docs"]["lifted"] == NOW.isoformat()
    assert len(demoted["docs"]["triggers"]) == 1
