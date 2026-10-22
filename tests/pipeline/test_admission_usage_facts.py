# ruff: noqa: F811 — the imported fixture is requested by name
"""An admission record carries the usage facts the real guard decided on: the reading's source and
age, the threshold and ramp value, and whether the start was made on an estimate (spec:
capacity-checks, admission leaves a record that explains it).

The guard is not replaced: a round runs `run_round` through `decide_start` and `may_start_unit`,
and the reading is a cached usage payload kept in the state directory, as in the usage tests.
"""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.admission_record import (
    ADMISSIONS_NAME,
    AdmissionRecord,
    read_admissions,
)
from agent_build_kit.pipeline.unit_store import UnitStore
from tests.cli.test_admission_asks_own_account import isolated, round_of, unit  # noqa: F401
from tests.conftest import make_installation
from tests.usage_host import Host, payload, refused

MINUTE = timedelta(minutes=1)


def workspace(
    tmp_path: Path, host: Host, *, session: dict, weekly: dict
) -> tuple[Installation, UnitStore]:
    """One unit of `app`, with the given limits, and the usage cache in its state directory."""
    inst = make_installation(
        tmp_path / "planning",
        planning={"state_dir": ".", "worktree_root": str(tmp_path / "trees")},
        repos={"app": {"path": str(tmp_path / "app"), "slug": "example/app"}},
        runtimes={"claude_code": {"limits": {"session": session, "weekly": weekly}}},
    )
    inst.state_dir.mkdir(parents=True, exist_ok=True)
    host.keep_in(inst.state_dir)
    store = UnitStore(inst.state_dir / "units.json")
    store.upsert([unit("one/1", "app")])
    return inst, store


def only_record(inst: Installation) -> AdmissionRecord:
    [record] = read_admissions(inst.state_dir / ADMISSIONS_NAME)
    return record


def test_a_record_carries_the_source_age_threshold_and_ramp_of_the_guards_own_decision(
    tmp_path: Path, host: Host
) -> None:
    inst, store = workspace(
        tmp_path,
        host,
        session={"usage_pause_pct": 92, "usage_pause_ceiling_pct": 96},
        weekly={"usage_pause_pct": 80},
    )
    host.keep_reading(MINUTE, payload(session=40.0, weekly=6.0))

    assert round_of(inst, store) == ["one/1"]

    usage = only_record(inst).usage
    assert usage.may_start is True
    assert usage.source
    assert usage.age_seconds is not None
    assert 30 <= usage.age_seconds <= 300
    # The session window is the nearest to its threshold; it ramps to its ceiling near the reset.
    assert (usage.threshold, usage.ramp) == (92, 96)
    assert (usage.estimate, usage.estimate_starts) == (False, 0)


def test_a_window_that_does_not_ramp_records_no_ramp_value(tmp_path: Path, host: Host) -> None:
    inst, store = workspace(
        tmp_path, host, session={"usage_pause_pct": 92}, weekly={"usage_pause_pct": 80}
    )
    host.keep_reading(MINUTE, payload(session=40.0, weekly=6.0))

    round_of(inst, store)

    usage = only_record(inst).usage
    assert (usage.threshold, usage.ramp) == (92, None)


def test_a_start_on_an_estimate_records_the_estimate_and_the_starts_made_on_it(
    tmp_path: Path, host: Host
) -> None:
    inst, store = workspace(
        tmp_path, host, session={"usage_pause_pct": 92}, weekly={"usage_pause_pct": 80}
    )
    host.keep_reading(180 * MINUTE, payload(session=70.0, weekly=6.0))
    refused(host, cooling=3 * MINUTE)
    kept = json.loads(host.cache.read_text())
    host.cache.write_text(json.dumps({**kept, "estimate_units": ["feature/1"]}))

    assert round_of(inst, store) == ["one/1"]

    usage = only_record(inst).usage
    assert usage.may_start is True
    assert usage.estimate is True
    assert usage.estimate_starts == 1
    assert usage.source
    assert usage.age_seconds is not None
    assert usage.age_seconds >= 170 * 60
    assert usage.threshold == 92
