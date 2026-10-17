"""A planning directory, a unit store and repos with schedules, for the scheduled e2e-test tests."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.config import REST_SPLIT
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.e2e_schedule import PREFIX, scheduled_name
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import Unit
from tests.conftest import make_installation
from tests.factories import stored_unit
from tests.fake_clock import FakeClock, install

TODAY = date(2026, 3, 10)


AT = datetime.combine(TODAY, time(9), tzinfo=UTC)


def on_today(monkeypatch: pytest.MonkeyPatch) -> FakeClock:
    """The clock the pipeline reads, standing at the morning of `TODAY`."""
    return install(monkeypatch, AT)


def ago(days: int) -> date:
    return TODAY - timedelta(days=days)


def planning(
    root: Path,
    schedules: dict[str, str | bool | None] | None = None,
    *,
    tests: dict[str, Any] | None = None,
    repo_splits: dict[str, dict[str, Any]] | None = None,
    project_limits: dict[str, Any] | None = None,
    **limits: Any,
) -> Installation:
    """A planning directory with one repo per key of `schedules`, each with that value as its
    own `tests.e2e_schedule` (None: unset); `app` alone when it is not given. `tests` is the
    top-level `tests` block and `repo_splits` gives repos their own `tests.e2e_splits`."""
    schedules = {"app": None} if schedules is None else schedules
    own = repo_splits or {}
    repos = {
        name: {
            "path": str(root / "checkouts" / name),
            "slug": f"example/{name}",
            "tests": {
                **({} if value is None else {"e2e_schedule": value}),
                **({"e2e_splits": own[name]} if name in own else {}),
            },
        }
        for name, value in schedules.items()
    }
    return make_installation(
        root,
        repos=repos,
        global_limits=limits,
        project_limits=project_limits or {},
        tests=tests or {},
    )


def store_of(inst: Installation, *e2e_repos: str, **others: str) -> UnitStore:
    """A store holding one e2e-test unit for each of `e2e_repos` and one unit-test unit for each
    of `others` (unit name = repo)."""
    store = UnitStore(inst.state_dir / "units.json")
    units: list[Unit] = [
        stored_unit(f"{repo}-work/1", change=f"{repo}-work", repo=repo, tier="e2e-test")
        for repo in e2e_repos
    ]
    units += [
        stored_unit(f"{repo}-work/1", change=f"{repo}-work", repo=repo, tier="unit-test")
        for repo in others
    ]
    store.upsert(units)
    return store


def archived(inst: Installation, repo: str, written: date, split: str = REST_SPLIT) -> str:
    """A scheduled change written on `written` and archived the same day; returns its name."""
    name = scheduled_name(repo, written, split)
    (inst.changes_dir / "archive" / f"{written.isoformat()}-{name}").mkdir(parents=True)
    return name


def open_change(inst: Installation, repo: str, written: date, split: str = REST_SPLIT) -> str:
    name = scheduled_name(repo, written, split)
    (inst.changes_dir / name).mkdir(parents=True)
    return name


def scheduled_changes(inst: Installation) -> list[str]:
    """The open scheduled changes, by name."""
    if not inst.changes_dir.is_dir():
        return []
    return sorted(p.name for p in inst.changes_dir.iterdir() if p.name.startswith(f"{PREFIX}-"))
