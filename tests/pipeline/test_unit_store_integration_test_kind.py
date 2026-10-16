"""A stored unit of the `integration-test` kind is written and read back as it is."""

from __future__ import annotations

import json
from pathlib import Path

from agent_build_kit.model import TestTier
from agent_build_kit.pipeline.unit_store import UnitStore
from tests.factories import unit


def test_a_unit_of_the_integration_test_kind_is_written_and_read_back(tmp_path: Path) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit("feature/1", change="feature", tier="integration-test")])

    assert json.loads(store.path.read_text())["units"][0]["tier"] == "integration-test"
    assert UnitStore(store.path).get("feature/1").tier is TestTier("integration-test")
