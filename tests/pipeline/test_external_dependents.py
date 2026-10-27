"""A unit that needs a held unit waits for its merge (spec: external-work)."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.pipeline.external_file import DONE, add_hold, write_holds
from agent_build_kit.pipeline.units import MERGED
from agent_build_kit.pipeline.vocabulary import WaitReason
from tests.external_support import SINCE, hold, waits_of, world_of
from tests.factories import stored_unit


def test_a_plain_needs_on_a_held_unit_waits_naming_it_and_may_start_once_the_hold_is_done(
    tmp_path: Path,
) -> None:
    inst, store, folder = world_of(
        tmp_path,
        stored_unit("feature/1", change="feature"),
        stored_unit("feature/2", change="feature", depends_on=("feature/1",)),
    )
    add_hold(folder, hold((1,)))

    wait = waits_of(inst, store)["feature/2"]

    assert wait.reason is WaitReason.BLOCKED
    assert wait.waits_on == ("feature/1",)
    assert "held" in wait.detail and "Sam Example" in wait.detail

    write_holds(folder, [hold((1,), status=DONE, merged_by="17", done_at=SINCE)])
    store.set_state("feature/1", MERGED)

    assert waits_of(inst, store)["feature/2"].reason is WaitReason.READY
