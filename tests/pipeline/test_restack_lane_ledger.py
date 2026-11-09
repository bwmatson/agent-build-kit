"""The lane's agent calls are `restack` rows for the unit moved, with its change and repository,
each asked of the guard first; a clean move in the lane writes no row and asks nothing.

Two units are moved by the lane `abk tick` builds, one that conflicts with `main` and one that
applies cleanly, over the usage ledger the pipeline writes.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.pipeline.usage_ledger import UsageRecord, read_ledger
from tests.restack_lane_fakes import tracked_rig
from tests.restack_turn_fakes import Rig
from tests.usage_host import Host

CLEAN = "spec/c/3"


@pytest.fixture
def rig(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, host: Host) -> Rig:
    return tracked_rig(tmp_path, monkeypatch, host)


def restack_rows(rig: Rig) -> list[UsageRecord]:
    ledger = rig.installation.state_dir / "usage-ledger.jsonl"
    return [row for row in read_ledger(ledger) if row.node == "restack"]
