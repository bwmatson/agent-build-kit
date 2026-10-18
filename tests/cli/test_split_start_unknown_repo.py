"""A planned unit whose repo the configuration no longer has is not gated, and does not stop
the round from deciding about the others (spec: split-start-gate)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.vocabulary import WaitReason
from tests.split_start_support import fresh, gate_round, installation, store_of

pytestmark = pytest.mark.usefixtures("scripted_engine")


def test_a_unit_of_a_repo_the_configuration_lacks_is_not_gated_and_the_wait_reasons_are_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gate_round(monkeypatch)
    inst = installation(tmp_path, acp=True)
    store = store_of(inst)
    fresh(store, "gone/1", "acp", repo="removed")
    fresh(store, "gated/1", "acp")

    waits = cli.wait_reasons(
        inst, store.all(), started=set(), building=set(), only=frozenset(), usage_paused=False
    )

    assert waits["gated/1"].reason is WaitReason.SPLIT
    assert waits["gone/1"].reason is not WaitReason.SPLIT
