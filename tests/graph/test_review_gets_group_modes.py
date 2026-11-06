"""The review step hands the reviewer the mode of each group the unit builds, keyed by change and
group number, only when some group is not `tests_and_code` and the build is stubbed (spec:
group-build-modes, the review prompt follows the modes). The branch is real."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from agent_build_kit.pipeline.group_mode import GroupMode
from tests.graph.branch_fakes import key, prepared, titled
from tests.graph.test_build_path import build


def reviewed_with(
    tmp_path: Path, *, setting: bool = True, modes: Mapping[str, str] | None = None
) -> list[dict[str, GroupMode]]:
    recorder, _ = prepared(
        tmp_path, groups={"add-marker": titled(1, 2)}, setting=setting, modes=modes
    )
    outcome = build(tmp_path, recorder, **recorder.overrides(tmp_path))
    assert outcome.status == "open", outcome.detail
    return recorder.review_modes


def test_a_unit_mixing_modes_gives_the_review_each_groups_mode(tmp_path: Path) -> None:
    given = reviewed_with(tmp_path, modes={key(1): "no_code"})

    assert given == [{key(1): GroupMode.NO_CODE, key(2): GroupMode.TESTS_AND_CODE}]


def test_a_unit_of_only_tests_and_code_groups_gives_the_review_no_modes(tmp_path: Path) -> None:
    assert reviewed_with(tmp_path) == [{}]


def test_a_build_that_is_not_stubbed_gives_the_review_no_modes(tmp_path: Path) -> None:
    assert reviewed_with(tmp_path, setting=False, modes={key(1): "no_code"}) == [{}]
