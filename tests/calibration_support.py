"""What the calibration tests share: units that merged at a known ratio, the limits a
test configured, and a planning project whose planner answers in the raw shape a model sends."""

from __future__ import annotations

import itertools
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from agent_build_kit import runtimes
from agent_build_kit.pipeline.unit_store import StoredUnit, UnitStore
from agent_build_kit.pipeline.units import MERGED, PLANNED
from tests.conftest import make_installation
from tests.factories import activate_with, stored_unit
from tests.runtimes.stand_in import StandInRuntime

EPOCH = datetime(2026, 1, 1, tzinfo=UTC)
_ids = itertools.count(1)


def sample(
    ratio: float,
    *,
    at: int,
    repo: str = "app",
    tier: str = "tier1",
    flag: str = "",
    estimate: int = 100,
    actual: int | None = None,
    state: str = MERGED,
    uid: str | None = None,
    **extra: Any,
) -> StoredUnit:
    """A unit that landed at `ratio` times its estimate, merged `at` minutes in."""
    landed = round(estimate * ratio) if actual is None else actual
    when = (EPOCH + timedelta(minutes=at)).isoformat()
    return stored_unit(
        uid or f"s{next(_ids)}/1",
        **extra,
        repo=repo,
        tier=tier,
        flag=flag,
        estimated_lines=estimate,
        actual_lines=landed,
        state=state,
        history=({"state": PLANNED, "at": EPOCH.isoformat()}, {"state": state, "at": when}),
    )


def run_of(ratios: list[float], **kw: Any) -> list[StoredUnit]:
    """Samples merged one after another, the first oldest."""
    return [sample(ratio, at=at, **kw) for at, ratio in enumerate(ratios)]


# What the test configured, which an installation made afterwards must be given again.
CONFIGURED: dict[str, Any] = {}


def limits(**overrides: Any) -> None:
    CONFIGURED.clear()
    CONFIGURED.update(overrides)
    activate_with(global_limits=overrides)


OPT_OUT = "Acceptance: none — a fixture about planning, not about the acceptance group\n"


def tasks_md(*flags: str) -> str:
    text = f"# Tasks\n\n{OPT_OUT}\n"
    for number, flag in enumerate(flags, start=1):
        tag = f" [{flag}]" if flag else ""
        text += f"## {number}. [app] [tier1]{tag} Group {number}\n\n"
        text += f"- [ ] {number}.1 Test: it.\n- [ ] {number}.2 Do it.\n\n"
    return text


def write_store(root: Path, units: list[StoredUnit], **extra: dict[str, Any]) -> UnitStore:
    """The units file as an earlier or later tick left it, with `extra` fields by unit id."""
    records = [{**u.model_dump(mode="json"), **extra.get(u.id, {})} for u in units]
    (root / "units.json").write_text(json.dumps({"units": records}))
    return UnitStore(root / "units.json")


def planner(monkeypatch: pytest.MonkeyPatch, *answers: dict) -> StandInRuntime:
    queue = ["Here is the plan.\n\n" + json.dumps(answer) + "\n" for answer in answers]

    def next_answer(request: Any) -> None:
        runtime.answer = queue.pop(0) if len(queue) > 1 else queue[0]

    runtime = StandInRuntime(act=next_answer)
    monkeypatch.setattr(runtimes, "active", lambda: runtime)
    return runtime


def new_unit(uid: str, groups: list[int], estimate: int, **extra: Any) -> dict:
    return {
        "id": uid,
        "change": "feature",
        "title": "A unit",
        "repo": "app",
        "tier": "tier1",
        "depends_on": [],
        "estimated_lines": estimate,
        "groups": groups,
        **extra,
    }


def project(tmp_path: Path, tasks: str, units: list[StoredUnit], **extra: dict):
    inst = make_installation(
        tmp_path,
        planning={"state_dir": ".", "worktree_root": str(tmp_path.parent / "trees")},
        limits=CONFIGURED,
    )
    path = inst.changes_dir / "feature"
    path.mkdir(parents=True)
    (path / "tasks.md").write_text(tasks)
    return inst, write_store(tmp_path, units, **extra)
