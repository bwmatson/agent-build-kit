"""Changes with groups and holds on them, shared by the hand-off tests (spec: external-work)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from agent_build_kit.cli.pipeline import wait_reasons
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.external_file import Hold
from agent_build_kit.pipeline.unit_store import StoredUnit, UnitStore
from agent_build_kit.pipeline.wait_log import Wait
from tests.conftest import make_installation

SINCE = datetime(2026, 10, 26, 9, 30, tzinfo=UTC)
GROUP = "## {n}. [app] [unit-test] Group {n}\n\n- [ ] {n}.1 Test: it\n"


def tasks_with(groups: int) -> str:
    return "# Tasks\n\n" + "\n".join(GROUP.format(n=n) for n in range(1, groups + 1))


def change_in(changes: Path, groups: int = 3) -> Path:
    """The change `feature` under `changes`, with `groups` groups; none writes no `tasks.md`."""
    folder = changes / "feature"
    folder.mkdir(parents=True)
    (folder / "proposal.md").write_text("# feature\n")
    if groups:
        (folder / "tasks.md").write_text(tasks_with(groups))
    return folder


def change_with(tmp_path: Path, groups: int = 3) -> Path:
    return change_in(tmp_path / "openspec" / "changes", groups)


def hold(scope: object = (2, 3), **fields: object) -> Hold:
    base: dict[str, object] = {
        "scope": scope,
        "holder": "Sam Example",
        "link": "https://boards.example/items/42",
        "since": SINCE,
    }
    return Hold.model_validate({**base, **fields})


def waits_of(inst: Installation, store: UnitStore) -> dict[str, Wait]:
    """Why each unit of `store` is not running, as the tick reads it."""
    return wait_reasons(
        inst,
        store.all(),
        started=set(),
        building=set(),
        only=frozenset(),
    )


def world_of(
    tmp_path: Path, *units: StoredUnit, places: int = 50
) -> tuple[Installation, UnitStore, Path]:
    """An installation with `places` build places whose change `feature` has three groups, and
    a store of `units`."""
    inst = make_installation(
        tmp_path / "planning",
        planning=dict(state_dir="."),
        project_limits=dict(max_units_in_progress=places),
    )
    store = UnitStore(inst.state_dir / "units.json")
    store.upsert(list(units))
    return inst, store, change_in(inst.changes_dir)
