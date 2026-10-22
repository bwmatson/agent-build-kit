"""An `[e2e-test]` unit whose branch changes product code is stopped at `checks`, before any
unit-test run, with feedback of its own; what a group declares with `Support:` is read from the
plan and not from the branch (spec: e2e-group-scope)."""

from __future__ import annotations

from collections.abc import Collection
from pathlib import Path
from typing import Any

from agent_build_kit.pipeline.shell import changed_files
from agent_build_kit.pipeline.unit_store import FeedbackSource, UnitStore
from tests.e2e_scope_fakes import CHANGED, NEW, OLD, branch
from tests.factories import git, unit
from tests.graph.test_build_path import build
from tests.runner_fakes import Recorder, rejecting

UNIT = unit().id
TEST = "tests/e2e/test_route.py"
PRODUCT = "src/app/route.py"
SCRIPT = "scripts/seed-stack.sh"
PRODUCT_BASE = {PRODUCT: "def route():\n    return 1\n", TEST: OLD}
PRODUCT_CHANGED = {PRODUCT: "def route():\n    return 2\n", TEST: NEW}


def group(number: int, *, support: Collection[str] = (), tier: str = "e2e-test") -> str:
    lines = [f"## {number}. [app] [{tier}] Group {number}", ""]
    if support:
        paths = ", ".join(f"`{path}`" for path in support)
        lines += [f"Support: {paths} — the live tests start the stack with it", ""]
    lines += [f"- [ ] {number}.1 Test: `{TEST}` covers the route", ""]
    return "\n".join(lines)


def plan(tmp_path: Path, *groups: str) -> None:
    """The change's tasks in the planning repo, where the build reads its groups from."""
    path = tmp_path / "meta" / "openspec" / "changes" / "add-marker" / "tasks.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# Tasks\n\n" + "\n".join(groups))


def real_diff(cwd: Path, base: str) -> tuple[tuple[str, ...], int]:
    return tuple(changed_files(cwd, base)), 0


class Scoped:
    """An e2e unit over a real branch holding `changed` on top of `base_files`, planned as
    `groups`, built over the runner fakes."""

    def __init__(
        self,
        tmp_path: Path,
        changed: dict[str, str],
        *,
        base_files: dict[str, str] | None = None,
        groups: tuple[str, ...] | None = None,
        tier: str = "e2e-test",
        numbers: tuple[int, ...] = (1,),
        **options: Any,
    ) -> None:
        self.tmp_path = tmp_path
        self.repo, self.base = branch(tmp_path, changed, base_files=base_files)
        # The build diffs against `origin/<base>`, the remote's trunk.
        git(self.repo, "update-ref", f"refs/remotes/origin/{self.base}", self.base)
        plan(tmp_path, *(groups or (group(1),)))
        store = UnitStore(tmp_path / "units.json")
        store.upsert([unit(tier=tier, groups=numbers)])
        self.recorder = Recorder(store, **options)
        self.overrides: dict[str, Any] = {
            "worktree": lambda *args, **kwargs: self.repo,
            "branch_diff": real_diff,
        }

    def build(self, **overrides: Any):
        return build(
            self.tmp_path,
            self.recorder,
            base=self.base,
            **{**self.overrides, **overrides},
        )

    @property
    def stored(self):
        return self.recorder.store.get(UNIT)

    def commit_all(self, message: str) -> None:
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", message)


def test_an_e2e_unit_changing_product_code_is_stopped_before_any_unit_test_run(
    tmp_path: Path,
) -> None:
    scoped = Scoped(tmp_path, PRODUCT_CHANGED, base_files=PRODUCT_BASE)

    outcome = scoped.build()

    assert outcome.status == "failed", outcome
    assert PRODUCT in outcome.detail
    assert TEST not in outcome.detail, "the test is not what stopped it"
    assert "unit-test" not in scoped.recorder.events
    assert "review" not in scoped.recorder.events
    stored = scoped.stored
    assert stored.feedback_source == FeedbackSource.SCOPE
    assert PRODUCT in stored.feedback
    feedback = stored.feedback.lower()
    assert "restore" in feedback
    assert "tests and test support" in feedback
    assert "product-defect" in feedback or "product defect" in feedback


def test_tests_docs_and_the_changelog_go_on(tmp_path: Path) -> None:
    changed = {
        "tests/e2e/conftest.py": "import pytest\n",
        "docs/e2e.md": "# e2e\n",
        "CHANGELOG.md": "## Unreleased\n",
    }
    scoped = Scoped(tmp_path, changed)

    scoped.build()

    assert "unit-test" in scoped.recorder.events
    assert scoped.stored.feedback_source != FeedbackSource.SCOPE


def test_a_file_the_plan_declares_as_support_goes_on(tmp_path: Path) -> None:
    scoped = Scoped(
        tmp_path, {SCRIPT: "#!/bin/sh\n", TEST: NEW}, groups=(group(1, support=[SCRIPT]),)
    )

    scoped.build()

    assert "unit-test" in scoped.recorder.events
    assert scoped.stored.feedback_source != FeedbackSource.SCOPE


def test_a_support_line_added_on_the_branch_allows_nothing(tmp_path: Path) -> None:
    on_branch = "openspec/changes/add-marker/tasks.md"
    scoped = Scoped(
        tmp_path,
        {SCRIPT: "#!/bin/sh\n", on_branch: group(1, support=[SCRIPT])},
    )

    outcome = scoped.build()

    assert outcome.status == "failed", outcome
    assert SCRIPT in outcome.detail
    assert "unit-test" not in scoped.recorder.events
    assert scoped.stored.feedback_source == FeedbackSource.SCOPE


def test_a_unit_test_unit_changing_product_code_is_not_checked(tmp_path: Path) -> None:
    scoped = Scoped(
        tmp_path,
        PRODUCT_CHANGED,
        base_files=PRODUCT_BASE,
        groups=(group(1, tier="unit-test"),),
        tier="unit-test",
    )

    scoped.build()

    assert "unit-test" in scoped.recorder.events
    assert scoped.stored.feedback_source != FeedbackSource.SCOPE


def test_a_stopped_unit_is_reworked_with_the_feedback_and_goes_on_once_the_file_is_restored(
    tmp_path: Path,
) -> None:
    scoped = Scoped(tmp_path, PRODUCT_CHANGED, base_files=PRODUCT_BASE)
    scoped.build()
    saved = scoped.stored.feedback
    assert scoped.stored.feedback_source == FeedbackSource.SCOPE
    recorder = scoped.recorder
    recorder.events.clear()
    recorder.prompts.clear()

    def restoring(prompt: str, **kwargs: Any) -> str:
        answer = recorder.claude(prompt, **kwargs)
        git(scoped.repo, "restore", "--source", scoped.base, "--", PRODUCT)
        scoped.commit_all("restore the product file")
        return answer

    scoped.build(run=restoring)

    assert len(recorder.prompts) == 1, "one agent call, a rework and not a fresh build"
    assert saved in recorder.prompts[0]
    assert "claude:tests" not in recorder.events
    assert "unit-test" in recorder.events
    assert scoped.stored.feedback_source != FeedbackSource.SCOPE


def test_a_rework_commit_that_adds_a_product_file_is_stopped(tmp_path: Path) -> None:
    scoped = Scoped(tmp_path, {TEST: NEW}, base_files={TEST: OLD})
    recorder = scoped.recorder
    recorder.verdicts = [rejecting("handle the empty route")]

    def adds_product(prompt: str, **kwargs: Any) -> str:
        answer = recorder.claude(prompt, **kwargs)
        if recorder.events[-1] == "claude:rework":
            (scoped.repo / PRODUCT).parent.mkdir(parents=True, exist_ok=True)
            (scoped.repo / PRODUCT).write_text("def route():\n    return 3\n")
            scoped.commit_all("fix: handle the empty route")
        return answer

    outcome = scoped.build(run=adds_product)

    assert outcome.status == "failed", outcome
    assert PRODUCT in outcome.detail
    assert recorder.events.count("unit-test") == 1, "only the first checks ran"
    assert scoped.stored.feedback_source == FeedbackSource.SCOPE


def test_a_resumed_unit_whose_branch_holds_a_product_file_is_stopped(tmp_path: Path) -> None:
    scoped = Scoped(
        tmp_path, {TEST: CHANGED, PRODUCT: "x = 1\n"}, base_files={TEST: OLD}, commits_from_impl=0
    )
    scoped.recorder.made = 2

    outcome = scoped.build()

    assert outcome.status == "failed", outcome
    assert PRODUCT in outcome.detail
    assert scoped.recorder.prompts == [], "no agent was asked"
    assert "unit-test" not in scoped.recorder.events


def test_a_unit_of_two_e2e_groups_is_judged_against_the_support_of_both(tmp_path: Path) -> None:
    other = "compose.e2e.yml"
    groups = (group(1, support=[SCRIPT]), group(2, support=[other]))
    both = Scoped(
        tmp_path / "both",
        {SCRIPT: "#!/bin/sh\n", other: "services: {}\n"},
        groups=groups,
        numbers=(1, 2),
        commits_from_impl=0,
    )
    both.recorder.made = 2
    both.build()
    assert "unit-test" in both.recorder.events
    assert both.stored.feedback_source != FeedbackSource.SCOPE

    neither = Scoped(
        tmp_path / "neither",
        {SCRIPT: "#!/bin/sh\n", "scripts/other.sh": "#!/bin/sh\n"},
        groups=groups,
        numbers=(1, 2),
        commits_from_impl=0,
    )
    neither.recorder.made = 2
    outcome = neither.build()

    assert outcome.status == "failed", outcome
    assert "scripts/other.sh" in outcome.detail
    assert SCRIPT not in outcome.detail, "the first group's support is allowed"
