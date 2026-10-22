"""`link_needs` records which `Needs:` targets wait for a merge (spec: needs-can-wait-for-a-merge).

A target is a merge target when its line says `merged` after the group number, or when it is a
group of another repository. `merge_needs` is a subset of `needs`, recomputed on every call.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.unit_store import UnitStore
from tests.cli.replan_driver import Replan, needs_md, tasks_md
from tests.factories import unit

pytestmark = pytest.mark.usefixtures("scripted_engine")


def linked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *lines: str, edges: bool = False
) -> Replan:
    """A change `feature` with `lines` as its `Needs:` lines, and a unit each for `base` and
    `other` (repo `app`) and `shared` (repo `platform`). With `edges`, `base/2` depends on
    `base/1` and `feature/1` on `base/2`."""
    run = Replan(tmp_path, monkeypatch, feature=needs_md(*lines))
    run.store.upsert(
        [
            unit("feature/1", change="feature", groups=(1,)),
            unit("base/1", change="base", groups=(1,)),
            unit("other/1", change="other", groups=(1,)),
            unit("shared/1", change="shared", groups=(1,), repo="platform"),
        ]
    )
    if edges:
        run.store.upsert(
            [
                unit("base/2", change="base", groups=(2,), depends_on=("base/1",)),
            ]
        )
        run.store.set_dependencies("feature/1", ("base/2",))
    cli.link_needs(run.inst, store=run.store)
    return run


def feature(run: Replan):
    return run.store.get("feature/1")


def test_a_merged_line_is_a_merge_target_and_a_plain_same_repo_line_is_not(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = linked(tmp_path, monkeypatch, "base group 1 merged", "other group 1")

    assert feature(run).needs == ("base/1", "other/1")
    assert feature(run).merge_needs == ("base/1",)


def test_a_plain_line_to_another_repository_is_a_merge_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = linked(tmp_path, monkeypatch, "shared group 1", "other group 1")

    assert feature(run).needs == ("shared/1", "other/1")
    assert feature(run).merge_needs == ("shared/1",)


def test_a_plain_and_a_merge_line_on_one_target_make_it_a_merge_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = linked(tmp_path, monkeypatch, "base group 1", "base group 1 merged")

    assert feature(run).needs == ("base/1",)
    assert feature(run).merge_needs == ("base/1",)


def test_an_implied_target_is_recorded_without_adding_a_dependency(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = linked(tmp_path, monkeypatch, "base group 1 merged", edges=True)

    assert feature(run).depends_on == ("base/2",)
    assert feature(run).needs == ("base/1",)
    assert feature(run).merge_needs == ("base/1",)


def test_removing_the_word_clears_the_mark_on_the_next_call_but_a_cross_repo_one_stays(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = linked(tmp_path, monkeypatch, "base group 1 merged", "shared group 1 merged")
    assert feature(run).merge_needs == ("base/1", "shared/1")

    run.write("feature", needs_md("base group 1", "shared group 1"))
    cli.link_needs(run.inst, store=run.store)

    assert feature(run).needs == ("base/1", "shared/1")
    assert feature(run).merge_needs == ("shared/1",)


def test_removing_the_line_clears_the_marks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = linked(tmp_path, monkeypatch, "base group 1 merged")

    run.write("feature", tasks_md(1))
    cli.link_needs(run.inst, store=run.store)

    assert (feature(run).needs, feature(run).merge_needs) == ((), ())


def test_a_store_written_without_the_field_loads_with_it_empty_and_the_next_call_fills_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = linked(tmp_path, monkeypatch, "base group 1 merged")
    raw = json.loads(run.store.path.read_text())
    for record in raw["units"]:
        record.pop("merge_needs")
    run.store.path.write_text(json.dumps(raw))
    assert UnitStore(run.store.path).get("feature/1").merge_needs == ()

    cli.link_needs(run.inst, store=run.store)

    assert feature(run).merge_needs == ("base/1",)
