"""A second `abk scrub-store --apply` finds nothing and writes nothing, and what the first
left passes the leak test's home-path pattern (spec: stored-text-scrub)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from agent_build_kit.installation import Installation
from tests.installation_leaks import leaks
from tests.scrub_store_support import UNIT, pause, planning_installation, run, seed

STORE = "runs/units.json"


@pytest.fixture
def inst(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Installation:
    return planning_installation(tmp_path, monkeypatch)


def store_leaks(inst: Installation) -> list[str]:
    return [found for found in leaks(inst.root) if found.startswith(STORE)]


def test_a_second_apply_reports_nothing_and_writes_nothing(
    inst: Installation, capsys: pytest.CaptureFixture[str]
) -> None:
    path = seed(inst)
    original = path.read_bytes()
    pause(inst)
    assert run(inst, "scrub-store", "--apply") == 0
    capsys.readouterr()
    copy = inst.state_dir / "units.json.pre-redact"
    os.utime(path, ns=(10**18, 10**18))
    scrubbed = (path.read_bytes(), path.stat().st_mtime_ns)

    assert run(inst, "scrub-store", "--apply") == 0

    out = capsys.readouterr()
    assert UNIT not in out.out + out.err
    assert (path.read_bytes(), path.stat().st_mtime_ns) == scrubbed
    assert copy.read_bytes() == original


def test_the_scrubbed_store_passes_the_structural_home_path_pattern(inst: Installation) -> None:
    seed(inst)
    assert store_leaks(inst)
    pause(inst)

    assert run(inst, "scrub-store", "--apply") == 0

    assert store_leaks(inst) == []
