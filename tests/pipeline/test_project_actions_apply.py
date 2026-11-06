"""The kit applies a change's `Project:` lines to abk.yaml, records them and commits the file alone
(spec: project-lines).

Driven over a real planning repository: its abk.yaml is edited by the real editors and committed
with real git; the unit store is the only stand-in."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest
import yaml

from agent_build_kit import config as config_module
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.project_actions import (
    ActionReport,
    apply_project_actions,
    commit_project_file,
    failed_lines,
    status_lines,
)
from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.pipeline.units import Member
from tests.factories import commit_files, git, init_repo, stored_unit
from tests.project_workspace import OPT_OUT

CHANGE = "feature"
CONFIG = """# The workspace.
planning:
  state_dir: {state}
repos:
  app:
    path: {app}
    slug: example/app
    projects:
      - path: old
        profile: python-uv
"""


class Planning:
    """A planning repository: abk.yaml committed, and a change's `tasks.md` beside it."""

    def __init__(self, root: Path) -> None:
        self.root = init_repo(root)
        (root.parent / "app").mkdir(exist_ok=True)
        self.original = CONFIG.format(app=root.parent / "app", state=root.parent / "state")
        commit_files(root, "start", {"abk.yaml": self.original})
        self.config = root / "abk.yaml"
        self.logged: list[str] = []
        self.published: list[tuple[str, int]] = []

    @property
    def inst(self) -> Installation:
        installation = Installation(config_module.load(self.config), self.root)
        installation.activate()
        return installation

    def tasks(self, *groups: tuple[str, ...], change: str = CHANGE) -> None:
        """Write the change's `tasks.md`: each group is the `Project:` lines it carries."""
        text = f"# Tasks\n\n{OPT_OUT}\n"
        for number, lines in enumerate(groups, start=1):
            body = "".join(f"{line}\n" for line in lines)
            text += f"## {number}. [app] [unit-test] Group {number}\n\n{body}\n"
            text += f"- [ ] {number}.1 Test: it.\n- [ ] {number}.2 Do it.\n\n"
        folder = self.inst.changes_dir / change
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "tasks.md").write_text(text)

    def run(
        self, units: list[StoredUnit] | None = None, *, planning: tuple[str, ...] = ()
    ) -> ActionReport:
        def publish(change: str, group: int) -> None:
            self.published.append((change, group))

        return apply_project_actions(
            self.inst,
            units or [],
            planning=planning,
            publish=publish,
            log=self.logged.append,
        )

    def listed(self) -> dict[str, str]:
        raw = yaml.safe_load(self.config.read_text())
        return {p["path"]: p["profile"] for p in raw["repos"]["app"].get("projects", [])}


@pytest.fixture
def planning(tmp_path: Path) -> Planning:
    return Planning(tmp_path / "planning")


def carrier(state: str = "merged", **overrides) -> StoredUnit:
    return stored_unit(f"{CHANGE}/1", change=CHANGE, groups=(1,), state=state, **overrides)


def test_an_add_is_applied_when_the_change_is_planned_and_a_replan_makes_no_second_edit(
    planning: Planning,
) -> None:
    planning.tasks(("Project: add conformance python-uv",))

    first = planning.run(planning=(CHANGE,))

    assert planning.listed() == {"old": "python-uv", "conformance": "python-uv"}
    assert len(first.applied) == 1
    written = planning.config.read_text()
    planning.published.clear()

    again = planning.run(planning=(CHANGE,))

    assert planning.config.read_text() == written
    assert again.applied == ()
    assert planning.published == []


def test_a_replace_adds_the_new_half_at_plan_time_and_drops_the_old_half_at_the_merge(
    planning: Planning,
) -> None:
    planning.tasks(("Project: replace old with new python-uv",))

    planning.run([carrier("in_review")], planning=(CHANGE,))

    assert set(planning.listed()) == {"old", "new"}

    planning.run([carrier("merged")])

    assert set(planning.listed()) == {"new"}


@pytest.mark.parametrize("state", ["in_review", "running"])
def test_a_remove_is_not_applied_before_the_carrying_unit_settles(
    planning: Planning, state: str
) -> None:
    planning.tasks(("Project: remove old",))

    planning.run([carrier(state)])

    assert "old" in planning.listed()


@pytest.mark.parametrize("state", ["settling", "merged"])
def test_a_remove_is_applied_once_the_carrying_unit_is_settling_or_merged(
    planning: Planning, state: str
) -> None:
    planning.tasks(("Project: remove old",))

    planning.run([carrier(state)])

    assert "old" not in planning.listed()
    assert planning.published == [(CHANGE, 1)]


def test_a_remove_is_applied_over_the_groups_a_joined_unit_carries(planning: Planning) -> None:
    planning.tasks((), ("Project: remove old",), change="carried")
    host = stored_unit(
        "host/1",
        change="host",
        groups=(1,),
        state="merged",
        joined=(Member(change="carried", groups=(2,)),),
    )

    planning.run([host])

    assert "old" not in planning.listed()


def test_a_remove_waits_while_an_unfinished_unit_is_stored_in_the_project(
    planning: Planning,
) -> None:
    planning.tasks(("Project: remove old",))
    other = stored_unit("other/1", change="other", repo="app", project="old", state="in_review")

    report = planning.run([carrier(), other])

    assert "old" in planning.listed()
    assert len(report.waiting) == 1
    shown = status_lines(planning.inst, [carrier(), other])
    assert any("old" in line and CHANGE in line for line in shown)

    finished = other.model_copy(update={"state": "merged"})
    planning.run([carrier(), finished])

    assert "old" not in planning.listed()
    assert status_lines(planning.inst, [carrier(), finished]) == []


def test_an_edit_written_but_not_recorded_is_repeated_as_a_no_op_and_then_recorded(
    planning: Planning,
) -> None:
    planning.tasks(("Project: add conformance python-uv",))
    # What a crash left: the edit is in the file and the ledger has no record of it.
    written = planning.original + "      - path: conformance\n        profile: python-uv\n"
    planning.config.write_text(written)

    planning.run(planning=(CHANGE,))

    assert planning.config.read_text() == written
    # Recorded: a person's later removal of the project is not undone by the next round.
    planning.config.write_text(planning.original)
    planning.run(planning=(CHANGE,))

    assert "conformance" not in planning.listed()


@pytest.mark.skipif(os.geteuid() == 0, reason="a root user can write a read-only folder")
def test_a_failing_edit_is_logged_leaves_the_file_is_retried_and_does_not_fail_the_tick(
    planning: Planning,
) -> None:
    planning.tasks(("Project: add conformance python-uv",))
    before = planning.config.read_bytes()
    planning.root.chmod(stat.S_IRUSR | stat.S_IXUSR)
    try:
        report = planning.run(planning=(CHANGE,))
        shown = failed_lines(planning.inst)
    finally:
        planning.root.chmod(stat.S_IRWXU)

    assert planning.config.read_bytes() == before
    assert len(report.failed) == 1
    assert planning.logged
    assert len(shown) == 1 and "conformance" in shown[0]

    retried = planning.run(planning=())

    assert planning.listed()["conformance"] == "python-uv"
    assert len(retried.applied) == 1
    assert failed_lines(planning.inst) == []


def test_the_edit_is_committed_alone_with_a_message_naming_the_change_and_group(
    planning: Planning,
) -> None:
    planning.tasks(("Project: add conformance python-uv",))
    (planning.root / "notes.md").write_text("a person's note\n")
    git(planning.root, "add", "notes.md")
    planning.run(planning=(CHANGE,))

    assert commit_project_file(planning.inst, CHANGE, 1, log=planning.logged.append) is True

    files = git(planning.root, "show", "--name-only", "--format=", "HEAD").splitlines()
    assert files == ["abk.yaml"]
    message = git(planning.root, "log", "-1", "--format=%B")
    assert CHANGE in message and "1" in message
    assert git(planning.root, "diff", "--cached", "--name-only") == "notes.md"


def test_a_refused_commit_is_logged_and_the_edit_stays(planning: Planning) -> None:
    planning.tasks(("Project: add conformance python-uv",))
    planning.run(planning=(CHANGE,))
    hook = planning.root / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\necho 'no commits today' >&2\nexit 1\n")
    hook.chmod(hook.stat().st_mode | stat.S_IXUSR)
    logged: list[str] = []

    assert commit_project_file(planning.inst, CHANGE, 1, log=logged.append) is False

    assert any("no commits today" in line for line in logged)
    assert "conformance" in planning.listed()


def test_the_step_reads_the_configuration_fresh_after_a_write(planning: Planning) -> None:
    planning.tasks(
        ("Project: add one python-uv",),
        ("Project: replace one with two python-uv",),
    )

    report = planning.run(planning=(CHANGE,))

    assert report.failed == ()
    assert set(planning.listed()) == {"old", "one", "two"}
