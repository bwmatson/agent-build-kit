"""No status stands for tests that did not run: the posting refuses a result with a parked
split, and a unit parked before its push has no commit on the host to carry one
(spec: tier2-split-runs)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.config import Tier2UnitScope
from agent_build_kit.pipeline.tier2 import post_status
from agent_build_kit.pipeline.unit_store import Cause
from tests.forges.stand_in import StandInForge
from tests.graph_driver import fresh, tick
from tests.pipeline.test_tier2_split_groups import FILES, SOURCE, Groups
from tests.tier2_park_fakes import Parking, Step, holds_of
from tests.tier2_scope_fakes import branch, session


def test_the_posting_refuses_a_result_with_a_parked_split_and_sends_nothing(
    tmp_path: Path,
) -> None:
    repo, base = branch(tmp_path, SOURCE, base_files=FILES)
    gate = session(tmp_path, Groups(), scope=Tier2UnitScope.FULL, held=["acp"])
    gate.run(cwd=repo, base=base)
    assert gate.result is not None and gate.result.parked == ["acp"]
    forge = StandInForge()

    with pytest.raises(ValueError, match="acp"):
        post_status(forge, forge.repo_id(), gate.result)

    assert forge.statuses == []


def test_a_unit_parked_before_its_push_has_no_commit_on_the_host_to_carry_a_status(
    tmp_path: Path,
) -> None:
    recorder = fresh(tmp_path)
    parking = Parking(recorder.events, Step(parked=("acp",)))

    tick(
        tmp_path,
        recorder,
        tier="tier2",
        run_tier2=parking.run,
        tier2_result=parking.result,
        tier2_holds=lambda: holds_of(acp="down"),
    )

    assert recorder.store.get("add-marker/1").cause is Cause.SPLIT_HELD
    assert recorder.remote == [], "nothing was pushed"
    assert "status" not in recorder.events


def test_the_status_of_a_run_limited_to_one_group_says_it_covers_that_group_only(
    tmp_path: Path,
) -> None:
    repo, base = branch(tmp_path, SOURCE, base_files=FILES)
    gate = session(tmp_path, Groups(), scope=Tier2UnitScope.FULL, only="claude_code")
    gate.run(cwd=repo, base=base)
    assert gate.result is not None
    forge = StandInForge()

    post_status(forge, forge.repo_id(), gate.result)

    [posted] = forge.statuses
    assert "claude_code" in posted["description"]
