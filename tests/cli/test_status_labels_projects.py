"""The status names a unit's project beside its repo where the repo has several (spec:
unit-scheduling)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.pipeline.unit_store import Cause, UnitStore
from agent_build_kit.pipeline.units import FAILED, HELD, IN_REVIEW, PLANNED, RUNNING
from tests.conftest import status_lines
from tests.factories import new_unit
from tests.project_workspace import repos_declaring

# A unit of `app/web`, one of `app`'s root and one of `platform`, which declares one project:
# the id prefix, the unit's fields and the label its lines carry.
KINDS = (
    ("web", {"project": "web"}, "app/web"),
    ("root", {}, "app"),
    ("plat", {"repo": "platform"}, "platform"),
)


def record(store: UnitStore) -> None:
    for prefix, fields, _label in KINDS:
        parent, other = f"{prefix}parent/1", f"{prefix}other/1"
        store.upsert(
            [
                new_unit(f"{prefix}ready/1", **fields),
                new_unit(f"{prefix}fail/1", **fields),
                new_unit(f"{prefix}failwait/1", depends_on=(f"{prefix}fail/1",), **fields),
                new_unit(f"{prefix}parked/1", **fields),
                new_unit(f"{prefix}env/1", **fields),
                new_unit(parent, **fields),
                new_unit(other, **fields),
                new_unit(f"{prefix}run/1", **fields),
                new_unit(f"{prefix}blocked/1", depends_on=(f"{prefix}run/1",), **fields),
                new_unit(f"{prefix}second/1", depends_on=(parent, other), **fields),
            ]
        )
        store.set_state(f"{prefix}fail/1", FAILED, note="broke", branch=f"spec/{prefix}fail/1")
        store.set_state(f"{prefix}failwait/1", PLANNED, branch=f"spec/{prefix}failwait/1")
        store.set_state(f"{prefix}parked/1", HELD, note="dirty", cause=Cause.DIRTY_WORKTREE)
        store.set_state(f"{prefix}env/1", FAILED, note="down", cause=Cause.ENVIRONMENT)
        store.set_state(parent, IN_REVIEW, pr=1, branch=f"spec/{prefix}parent/1")
        store.set_state(other, IN_REVIEW, pr=2, branch=f"spec/{prefix}other/1")
        store.set_state(f"{prefix}run/1", RUNNING, branch=f"spec/{prefix}run/1")
        store.set_state(f"{prefix}blocked/1", PLANNED, branch=f"spec/{prefix}blocked/1")


@pytest.mark.parametrize(
    ("before", "name"),
    [
        ("", "ready"),
        ("failed: ", "fail"),
        ("blocked: ", "blocked"),
        ("waiting for the environment: ", "env"),
        ("", "second"),
        ("parked: ", "parked"),
    ],
    ids=["ready-queue", "failed", "blocked", "environment", "second-parent", "parked"],
)
def test_a_line_names_app_web_for_a_web_unit_and_the_repo_for_the_others(
    before: str,
    name: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    lines = status_lines(
        tmp_path,
        monkeypatch,
        capsys,
        record=record,
        repos=repos_declaring(tmp_path, "app", ("web",)),
        limit=20,
    )

    for prefix, _fields, label in KINDS:
        wanted = f"{before}{prefix}{name}/1 ({label})"
        assert any(wanted in line for line in lines), f"{wanted!r} not in {lines}"


def test_what_a_failed_unit_holds_up_is_named_by_the_same_label(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lines = status_lines(
        tmp_path,
        monkeypatch,
        capsys,
        record=record,
        repos=repos_declaring(tmp_path, "app", ("web",)),
        limit=20,
    )

    for prefix, _fields, label in KINDS:
        wanted = f"{prefix}fail/1 ({label}) has 1 unit waiting on it"
        assert any(wanted in line for line in lines), f"{wanted!r} not in {lines}"
