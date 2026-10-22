"""A replan whose plan joins another change's stored planned unit onto the unit it depends on
removes the joined unit from the store (plan-migration)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.cli.replan_driver import Replan, answer, planned, tasks_md
from tests.factories import stored_unit

pytestmark = pytest.mark.usefixtures("scripted_engine")


def test_a_unit_joined_onto_the_one_it_depends_on_is_gone_from_the_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch, feature=tasks_md(1), other=tasks_md(1), third=tasks_md(1))
    run.store.upsert(
        [
            stored_unit("feature/1", change="feature", groups=(1,)),
            stored_unit("other/1", change="other", groups=(1,)),
            stored_unit("third/1", change="third", groups=(1,), depends_on=("other/1",)),
        ]
    )
    run.record("feature")
    join = {"onto": "other/1", "unit": "third/1", "change": "third", "groups": [1]}

    code, out = run.run(capsys, "feature", reply=answer(planned("feature/1", (1,)), joins=[join]))

    assert code == 0, out
    assert {unit.id for unit in run.store.all()} == {"feature/1", "other/1"}
