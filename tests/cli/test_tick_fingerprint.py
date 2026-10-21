"""A tick prints the fingerprint of the configuration it runs on when it starts, and each decision
it records carries it (spec: capacity-checks, admission leaves a record that explains it)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.pipeline.admission_record import ADMISSIONS_NAME, config_fingerprint, read_admissions
from tests.tick_pass import (
    Builder,
    install_builder,
    isolate,
    stored,
    tick,
    warm_unit_graphs,
    workspace,
)

pytestmark = pytest.mark.usefixtures("scripted_engine")


@pytest.fixture(autouse=True)
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    warm_unit_graphs(tmp_path)
    isolate(monkeypatch)


@pytest.fixture
def builder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Builder:
    return install_builder(tmp_path, monkeypatch)


def test_a_tick_prints_its_fingerprint_and_the_decisions_it_records_carry_it(
    builder: Builder, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = workspace(tmp_path)
    builder.store.upsert([stored("one/1")])

    assert tick(inst) == 0

    fingerprint = config_fingerprint(inst)
    assert fingerprint in capsys.readouterr().out
    records = read_admissions(inst.state_dir / ADMISSIONS_NAME)
    assert [each.unit for each in records] == ["one/1"]
    assert records[0].fingerprint == fingerprint
