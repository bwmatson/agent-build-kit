"""A clean move before a push carries the base it left to tier 1, which says whether it ran
scoped or in full (spec: a-moved-base-is-checked-by-what-it-can-affect).

`verify_base` and the `tier1` node are driven over the recorder's fakes; the runner's own
log line is read from the real tier 1 runner over a real repository whose commands are faked.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from agent_build_kit.config import RestackCheck
from agent_build_kit.pipeline.wiring import build_tier1
from agent_build_kit.profiles.python_uv import PythonUvProfile
from tests.conftest import make_installation
from tests.graph.test_build_path import build, restacked
from tests.graph.test_fresh_base_builds import RESOLVED, Moving
from tests.graph.test_remaining_paths import fresh
from tests.pipeline.test_moved_base_scope import moved

OLD_BASE = "old-base-sha"
LINE = "moved base:"


def test_a_clean_move_passes_the_base_it_left_to_tier_1(tmp_path: Path) -> None:
    recorder = fresh(tmp_path)
    moving = Moving(recorder, restacked(old_base=OLD_BASE))

    outcome = build(tmp_path, recorder, **moving.overrides())

    assert outcome.status == "open"
    assert recorder.tier1_moved_from == ["", OLD_BASE], "the first check is not a moved base"


def test_a_resolved_move_goes_to_rebase_and_its_tier_1_is_not_a_moved_base_check(
    tmp_path: Path,
) -> None:
    recorder = fresh(tmp_path)
    moving = Moving(
        recorder, restacked(old_base=OLD_BASE), RESOLVED.model_copy(update={"old_base": "stale"})
    )

    build(tmp_path, recorder, **moving.overrides())

    assert recorder.tier1_moved_from == ["", OLD_BASE]


def test_a_conflicting_move_goes_to_rebase_and_its_old_base_never_reaches_tier_1(
    tmp_path: Path,
) -> None:
    recorder = fresh(tmp_path)
    conflict = restacked(old_base="stale", conflict="CONFLICT in a.py")
    moving = Moving(recorder, restacked(old_base=OLD_BASE), conflict)

    build(tmp_path, recorder, **moving.overrides())

    assert recorder.tier1_moved_from == ["", OLD_BASE]


def test_a_tier_two_unit_still_runs_tier_2_after_its_scoped_tier_1(tmp_path: Path) -> None:
    recorder = fresh(tmp_path, tier="tier2")
    moving = Moving(recorder, restacked(old_base=OLD_BASE))

    outcome = build(tmp_path, recorder, **moving.overrides())

    assert outcome.status == "open"
    assert recorder.tier1_moved_from[-1] == OLD_BASE
    after = recorder.events[recorder.events.index("moved") :]
    assert after.index("tier1") < after.index("tier2") < after.index("push")


class Profile(PythonUvProfile):
    """The python-uv profile running one lint command and one test command."""

    def lint_command(self, base: str) -> list[str]:
        return ["lint"]

    def test_commands(
        self, repo: Path, changed: list[str], *, root_extras: list[str]
    ) -> list[list[str]]:
        return [["tests"]]


def passing(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(command, 0, "5 passed\n", "")


def lines_logged(
    tmp_path: Path,
    *,
    own: dict[str, str],
    incoming: dict[str, str],
    old_base: str | None = None,
    setting: RestackCheck = RestackCheck.AFFECTED,
) -> list[str]:
    """What the real tier 1 runner logs for a unit moved onto a base that gained `incoming`."""
    limits: dict[str, Any] = {"tier1_repeat_runs": 0}
    if setting is RestackCheck.FULL:
        limits["restack_check"] = setting.value
    make_installation(tmp_path / "planning", limits=limits)
    repo, left = moved(tmp_path, own=own, incoming=incoming)
    logged: list[str] = []
    tier1 = build_tier1(profile=Profile(), run=passing, log=logged.append)
    ok, _ = tier1(cwd=repo, base="main", moved_from=left if old_base is None else old_base)
    assert ok
    return [line for line in logged if LINE in line]


def test_a_move_over_disjoint_files_logs_one_moved_base_line(tmp_path: Path) -> None:
    found = lines_logged(tmp_path, own={"a.py": "a = 2\n"}, incoming={"b.py": "b = 2\n"})

    assert len(found) == 1
    assert "full suite" not in found[0]


def test_a_file_the_unit_changes_is_logged_as_the_reason_for_the_full_suite(
    tmp_path: Path,
) -> None:
    found = lines_logged(
        tmp_path, own={"a.py": "a = 1\nx = 2\n"}, incoming={"a.py": "w = 0\na = 1\n"}
    )

    assert len(found) == 1
    assert "full suite" in found[0] and "a.py" in found[0]


def test_the_full_setting_is_logged_as_the_reason_for_the_full_suite(tmp_path: Path) -> None:
    found = lines_logged(
        tmp_path,
        own={"a.py": "a = 2\n"},
        incoming={"b.py": "b = 2\n"},
        setting=RestackCheck.FULL,
    )

    assert len(found) == 1
    assert "full suite" in found[0] and "restack_check" in found[0]


def test_a_move_with_no_old_base_is_logged_as_the_reason_for_the_full_suite(
    tmp_path: Path,
) -> None:
    found = lines_logged(
        tmp_path, own={"a.py": "a = 2\n"}, incoming={"b.py": "b = 2\n"}, old_base=""
    )

    assert len(found) == 1
    assert "full suite" in found[0] and "old base" in found[0]
