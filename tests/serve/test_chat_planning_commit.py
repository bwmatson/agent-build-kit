"""Committing the planning checkout from a chat is gated by `abk check` and `abk tags` of the
change, with the agent given what they reject and the commit tried again, delivers nothing to a
unit, and answers with what the commit means for the units that have started.

    POST /api/units/{change}/{number}/commit   {"tab", "message", "checkouts": ["planning"]}
         200 {"commit": SHA, "state": STATE, "delivered": false,
              "consequences": [{"kind": "needs" | "replan" | "spec", "units": [ID, ...],
                                "message": str}]}
         409 the gate still rejected the commit after the bounded fix loop; the detail holds
             its output, and the changes are kept uncommitted

`abk check` runs the OpenSpec CLI, faked here at its process boundary: a script that prints the
JSON `openspec validate --all --strict --json` prints and exits non-zero while any file under the
changes holds the word BROKEN. `abk tags` is real, over a real tasks file. The agent is the
`claude` binary faked at its stream-json boundary.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from agent_build_kit import runtimes
from agent_build_kit.config import dump
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.lease import Leases, lease_dir
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import Member
from agent_build_kit.pipeline.wiring import COMMIT_FIX_ROUNDS
from agent_build_kit.runtimes.claude_code import ClaudeCodeRuntime
from tests.attach_driver import checked_out, head, leave_lease
from tests.chat_serving import prompt_of, record_session
from tests.conftest import make_installation
from tests.factories import git, init_repo
from tests.runtimes.claude_cli import FakeClaude, finished_build
from tests.serving import seed_pipeline

pytestmark = pytest.mark.serial

BUILD_SESSION = "0b7e1d52-9c3a-4f8e-b1d6-2a5c7e9f0d81"
UNIT = "feature/2"
COMMIT = f"/api/units/{UNIT}/commit"
BROKEN = "BROKEN requirement has no scenario"


def _report(*, valid: bool) -> str:
    """What `openspec validate --all --strict --json` prints for the one change."""
    issues = [{"level": "ERROR", "path": "specs/registry/spec.md", "message": BROKEN}]
    item = {"id": "feature", "type": "change", "valid": valid, "issues": [] if valid else issues}
    totals = {"items": 1, "passed": int(valid), "failed": int(not valid)}
    return json.dumps({"items": [item], "summary": {"totals": totals}})


OPENSPEC = f"""#!/bin/sh
if grep -rq BROKEN openspec/changes 2>/dev/null; then
  echo '{_report(valid=False)}'
  exit 1
fi
echo '{_report(valid=True)}'
"""

TASKS = (
    "# Tasks\n\n## 1. [app] [tier1] The base\n\n- [ ] 1.1 Test: the base works\n"
    "\n## 2. [app] [tier1] The middle\n\nNeeds: other group 1 — the base\n\n"
    "Acceptance: none — nothing to drive\n\n"
    "- [ ] 2.1 Test: the middle works\n"
)
SPEC = (
    "## ADDED Requirements\n\n### Requirement: The registry is journaled\n\n"
    "The system SHALL write the registry through its journal.\n\n"
    "#### Scenario: A restart\n\n- **WHEN** it restarts\n- **THEN** every session is found\n"
)

# What the agent writes to fix the rejected edit: valid, and not what is committed already.
FIXED_SPEC = SPEC.replace("through its journal", "through its journal first")
FIXED_TASKS = TASKS.replace("The base", "The base, reworded")


@pytest.fixture
def inst(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Installation:
    """The suite's installation, with its OpenSpec command the script above."""
    script = tmp_path / "fake-openspec"
    script.write_text(OPENSPEC)
    script.chmod(0o755)
    installation = make_installation(
        tmp_path / "planning",
        planning={"worktree_root": str(tmp_path / "worktrees")},
        openspec={"command": [str(script)]},
    )
    (installation.root / "abk.yaml").write_text(dump(installation.config))
    monkeypatch.chdir(installation.root)
    return installation


class Fixes(FakeClaude):
    """A `claude` that rewrites `files` (relative to its working directory) with what `fixed`
    says, once asked."""

    def __init__(self, stdout: str, fixed: Callable[[str], dict[str, str]]) -> None:
        super().__init__(stdout=stdout)
        self.fixed = fixed

    def __call__(self, argv, **kwargs):  # type: ignore[no-untyped-def]
        cwd = Path(kwargs["cwd"])
        for name, text in self.fixed(prompt_of(argv)).items():
            (cwd / name).write_text(text)
        return super().__call__(argv, **kwargs)


@pytest.fixture
def tree(inst: Installation) -> Path:
    seed_pipeline(inst)
    record_session(inst, UNIT, BUILD_SESSION, runtime="claude_code", model="opus")
    return checked_out(inst, UNIT)


@pytest.fixture
def planning(inst: Installation, tree: Path) -> Path:
    """The planning checkout, with the change committed and a chat attached to it."""
    repo = init_repo(inst.root)
    (repo / ".gitignore").write_text("runs/\nabk.yaml\n")
    change = inst.changes_dir / "feature"
    (change / "specs" / "registry").mkdir(parents=True)
    (change / "tasks.md").write_text(TASKS)
    (change / "specs" / "registry" / "spec.md").write_text(SPEC)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "plan")
    leave_lease(lease_dir(inst.state_dir), UNIT, files=1, checkouts=("planning",))
    return repo


def edit(inst: Installation, name: str, change: Callable[[str], str]) -> Path:
    path = inst.changes_dir / "feature" / name
    path.write_text(change(path.read_text()))
    return path


def agent(monkeypatch: pytest.MonkeyPatch, tree: Path, fixed: Callable[[str], dict[str, str]]):
    fake = Fixes(finished_build(tree, "Done."), fixed)
    runtimes.names()
    monkeypatch.setitem(runtimes._REGISTRY, "claude_code", ClaudeCodeRuntime(execute=fake))
    return fake


def commit(api: httpx.Client, message: str = "Plan it") -> httpx.Response:
    body = {"tab": "t1", "message": message, "checkouts": ["planning"]}
    return api.post(COMMIT, json=body)


# --- the gate -------------------------------------------------------------------------------------


def test_a_spec_edit_that_abk_check_rejects_is_given_to_the_agent_and_the_commit_tried_again(
    inst: Installation,
    tree: Path,
    planning: Path,
    api: httpx.Client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = "openspec/changes/feature/specs/registry/spec.md"
    edit(inst, "specs/registry/spec.md", lambda text: text + "\nBROKEN\n")
    fake = agent(monkeypatch, tree, lambda prompt: {spec: FIXED_SPEC})
    before = head(planning)

    answer = commit(api)

    assert answer.status_code == 200
    assert BROKEN in prompt_of(fake.calls[0][0]), "the gate's own output goes to the agent"
    assert Path(fake.calls[0][1] or "").resolve() == inst.root.resolve(), "in the planning checkout"
    assert head(planning) != before
    assert git(planning, "show", f"HEAD:{spec}") == FIXED_SPEC.rstrip("\n"), "the fixed file"
    assert git(planning, "log", "-1", "--format=%s").strip() == "Plan it"
    assert answer.json()["delivered"] is False


def test_a_task_file_that_abk_tags_rejects_is_given_to_the_agent_and_the_commit_tried_again(
    inst: Installation,
    tree: Path,
    planning: Path,
    api: httpx.Client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tasks = "openspec/changes/feature/tasks.md"
    edit(inst, "tasks.md", lambda text: text.replace("[app] [tier1] The base", "The base"))
    fake = agent(monkeypatch, tree, lambda prompt: {tasks: FIXED_TASKS})
    before = head(planning)

    answer = commit(api)

    assert answer.status_code == 200
    assert "tasks.md" in prompt_of(fake.calls[0][0]), "what `abk tags` printed"
    assert head(planning) != before
    assert git(planning, "show", f"HEAD:{tasks}") == FIXED_TASKS.rstrip("\n")


def test_a_commit_the_gate_still_rejects_after_the_bound_is_a_conflict_that_keeps_the_changes(
    inst: Installation,
    tree: Path,
    planning: Path,
    api: httpx.Client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    edit(inst, "specs/registry/spec.md", lambda text: text + "\nBROKEN\n")
    fake = agent(monkeypatch, tree, lambda prompt: {})
    before = head(planning)

    answer = commit(api)

    assert answer.status_code == 409
    assert BROKEN in answer.text, "the gate's output is shown"
    assert len(fake.calls) == COMMIT_FIX_ROUNDS, "the helper's bound"
    assert head(planning) == before
    assert git(planning, "status", "--porcelain").strip() != "", "the changes stay uncommitted"
    kept = Leases(lease_dir(inst.state_dir)).attachment(UNIT)
    assert kept is not None and kept.checkouts == ("planning",), "the attachment is kept"


# --- what the commit means for units that have started ------------------------------------------


def consequences_of(
    inst: Installation,
    tree: Path,
    planning: Path,
    api: httpx.Client,
    monkeypatch: pytest.MonkeyPatch,
) -> list[dict[str, object]]:
    """Commit the edit already made, with no agent needed, and read the consequences list; the
    units' store and the checkpointed threads are what they were."""
    store = inst.state_dir / "units.json"
    kept = store.read_bytes()
    agent(monkeypatch, tree, lambda prompt: {})

    answer = commit(api)

    assert answer.status_code == 200
    assert answer.json()["delivered"] is False
    assert store.read_bytes() == kept, "no unit is changed"
    listed = answer.json()["consequences"]
    for item in listed:
        assert "feature/4" not in item["units"], "a unit that has not started is not listed"
    return listed


def builds(inst: Installation, unit_id: str, **update: object) -> None:
    """Record which groups a seeded unit builds (and, perhaps, whose it is)."""
    store = UnitStore(inst.state_dir / "units.json")
    store.upsert([store.get(unit_id).model_copy(update=update)])


def test_a_needs_only_edit_is_listed_as_applied_on_the_next_tick(
    inst: Installation,
    tree: Path,
    planning: Path,
    api: httpx.Client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    builds(inst, UNIT, groups=(2,))
    edit(
        inst, "tasks.md", lambda text: text.replace("Needs: other group 1", "Needs: other group 2")
    )

    [item] = consequences_of(inst, tree, planning, api, monkeypatch)

    assert item["kind"] == "needs"
    assert "feature/2" in item["units"]  # type: ignore[operator]
    assert "next tick" in str(item["message"]).lower()


def test_a_needs_edit_lists_the_unit_that_builds_the_group_not_the_one_numbered_like_it(
    inst: Installation,
    tree: Path,
    planning: Path,
    api: httpx.Client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    builds(inst, UNIT, groups=(1,))
    builds(inst, "feature/7", groups=(1, 2))
    edit(
        inst, "tasks.md", lambda text: text.replace("Needs: other group 1", "Needs: other group 2")
    )

    [item] = consequences_of(inst, tree, planning, api, monkeypatch)

    assert item["kind"] == "needs"
    assert item["units"] == ["feature/7"]


def test_a_unit_of_another_change_that_joined_the_group_is_listed(
    inst: Installation,
    tree: Path,
    planning: Path,
    api: httpx.Client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    builds(inst, UNIT, groups=(1,))
    joined = (Member(change="feature", groups=(2,)),)
    builds(inst, "feature/7", change="other", groups=(1,), joined=joined)
    edit(
        inst, "tasks.md", lambda text: text.replace("Needs: other group 1", "Needs: other group 2")
    )

    [item] = consequences_of(inst, tree, planning, api, monkeypatch)

    assert item["units"] == ["feature/7"]


def test_ticking_a_checkbox_is_not_a_plan_change(
    inst: Installation,
    tree: Path,
    planning: Path,
    api: httpx.Client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    builds(inst, UNIT, groups=(2,))
    edit(inst, "tasks.md", lambda text: text.replace("- [ ] 2.1", "- [x] 2.1"))

    assert consequences_of(inst, tree, planning, api, monkeypatch) == []


def test_an_edit_above_the_first_group_is_a_plan_change(
    inst: Installation,
    tree: Path,
    planning: Path,
    api: httpx.Client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    edit(inst, "tasks.md", lambda text: text.replace("# Tasks\n", "# Tasks\n\nPriority: 2\n"))

    listed = consequences_of(inst, tree, planning, api, monkeypatch)

    assert [i["kind"] for i in listed] == ["replan"]


def test_a_plan_change_is_listed_as_replanned_with_built_units_keeping_their_state(
    inst: Installation,
    tree: Path,
    planning: Path,
    api: httpx.Client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    edit(
        inst,
        "tasks.md",
        lambda text: text + "\n## 3. [app] [tier1] A new group\n\n- [ ] 3.1 Test: x\n",
    )

    listed = consequences_of(inst, tree, planning, api, monkeypatch)

    [item] = [i for i in listed if i["kind"] == "replan"]
    assert "feature/2" in item["units"]  # type: ignore[operator]
    message = str(item["message"]).lower()
    assert "next tick" in message and "keep" in message


def test_a_changed_requirement_flags_a_started_unit_for_a_rework_or_a_requeue_and_changes_nothing(
    inst: Installation,
    tree: Path,
    planning: Path,
    api: httpx.Client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    edit(
        inst,
        "specs/registry/spec.md",
        lambda text: text.replace("through its journal", "directly, with no journal"),
    )

    listed = consequences_of(inst, tree, planning, api, monkeypatch)

    [item] = [i for i in listed if i["kind"] == "spec"]
    assert "feature/2" in item["units"]  # type: ignore[operator]
    message = str(item["message"]).lower()
    assert "rework" in message and "requeue" in message


# --- the lease and the checkouts a commit names -----------------------------------------------

FREE_SESSION = "6d2a8f14-3e5b-4c7a-9f0e-1b8d3c6a2e71"


def free_lease(inst: Installation, *, files: int) -> Leases:
    """A live lease of a free session on both checkouts, as its turn leaves it."""
    leases = Leases(lease_dir(inst.state_dir))
    leases.drop(UNIT)
    assert leases.take(
        UNIT,
        "tab:t1",
        checkouts=("worktree", "planning"),
        session=FREE_SESSION,
        runtime="claude_code",
        head="abc",
    )
    leases.mark_changes(UNIT, "tab:t1", files)
    return leases


def test_committing_the_only_dirty_checkout_leaves_a_lease_a_closing_page_frees(
    inst: Installation,
    tree: Path,
    planning: Path,
    api: httpx.Client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    leases = free_lease(inst, files=1)
    edit(inst, "tasks.md", lambda text: text.replace("The middle", "The middle, reworded"))
    agent(monkeypatch, tree, lambda prompt: {})

    assert commit(api).status_code == 200

    left = leases.attachment(UNIT)
    assert left is not None and left.checkouts == ("worktree",) and left.changed == 0
    leases.release_all("tab:t1")  # what closing the page does
    assert leases.attachment(UNIT) is None


def test_committing_the_planning_checkout_keeps_the_count_of_what_the_worktree_still_holds(
    inst: Installation,
    tree: Path,
    planning: Path,
    api: httpx.Client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    leases = free_lease(inst, files=2)
    (tree / "notes.py").write_text("NOTE = 1\n")
    edit(inst, "tasks.md", lambda text: text.replace("The middle", "The middle, reworded"))
    agent(monkeypatch, tree, lambda prompt: {})

    assert commit(api).status_code == 200

    left = leases.attachment(UNIT)
    assert left is not None and left.changed == 1


def test_a_commit_naming_both_checkouts_is_refused_and_commits_neither(
    inst: Installation, tree: Path, planning: Path, api: httpx.Client
) -> None:
    leases = free_lease(inst, files=2)
    (tree / "notes.py").write_text("NOTE = 1\n")
    edit(inst, "tasks.md", lambda text: text.replace("The middle", "The middle, reworded"))
    heads = (head(tree), head(planning))
    both = {"tab": "t1", "message": "Both", "checkouts": ["worktree", "planning"]}

    answer = api.post(COMMIT, json=both)

    assert answer.status_code == 422
    assert (head(tree), head(planning)) == heads
    kept = leases.attachment(UNIT)
    assert kept is not None and kept.changed == 2
