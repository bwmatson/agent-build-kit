"""`abk status` and `abk explain` name a unit sent on over its ceiling as over it and not split,
with the reason (spec: unsplittable-size)."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from agent_build_kit.cli.explain_cmd import cmd_explain
from agent_build_kit.pipeline.unit_store import StoredSplitRequest, UnitStore
from tests.conftest import make_installation, status_lines
from tests.factories import stored_unit

REASON = "it holds one group"


def record_unsplit(store: UnitStore) -> None:
    store.upsert([stored_unit("feature/1", change="feature")])
    store.set_split_request("feature/1", StoredSplitRequest(earned="full", lines=1010, ceiling=750))
    store.set_unsplit_reason("feature/1", REASON)


def test_status_names_the_unit_as_over_its_ceiling_and_not_split_with_the_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def record(store: UnitStore) -> None:
        record_unsplit(store)
        store.upsert([stored_unit("plain/1", change="plain")])

    lines = status_lines(tmp_path, monkeypatch, capsys, record=record)

    [named] = [line for line in lines if "feature/1" in line and "not split" in line]
    assert "over its ceiling" in named
    assert REASON in named
    assert not any("plain/1" in line and "not split" in line for line in lines)


def test_explain_names_the_unit_as_over_its_ceiling_and_not_split_with_the_reason(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = make_installation(
        tmp_path, planning=dict(state_dir=".", worktree_root=str(tmp_path.parent / "trees"))
    )
    record_unsplit(UnitStore(tmp_path / "units.json"))
    capsys.readouterr()

    assert cmd_explain(argparse.Namespace(unit="feature/1", at=None), inst) == 0

    out = capsys.readouterr().out
    assert "over its ceiling" in out
    assert "not split" in out
    assert REASON in out
