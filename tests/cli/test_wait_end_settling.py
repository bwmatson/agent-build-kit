"""A failed unit parked on a product-defect fix that is settling is requeued, and its note names
that state (spec: merged-waits-for-ci). The fix is a review-edge parent, the one case a failed
unit does not wait for the merge."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.pipeline.units import PLANNED, SETTLING
from tests.wait_end_support import CHILD, pipeline

FIX = "fix-product-defect-x/1"


def test_a_settling_parent_ends_the_wait_and_the_note_names_its_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pipe = pipeline(tmp_path, monkeypatch, threads=False)
    pipe.waiting_failed(FIX)
    pipe.pass_()

    pipe.store.set_state(FIX, SETTLING, pr=1)
    pipe.pass_()

    [note] = pipe.wait_ended_notes()
    assert "merged, its checks still running" in note
    assert pipe.store.get(CHILD).state == PLANNED
