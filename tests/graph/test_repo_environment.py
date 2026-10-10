"""A code repository's environment in the unit's worktree (spec: pipeline-environment).

The worktree is a real git worktree of a real checkout, so the inputs are compared with
the base branch's by git; `sync` and `check` are real child processes
(`tests/environment_fakes.py`) and the agent and tier 1 are faked where the runner binds
them, as in the other graph tests. Every step lands in the environment's call log, which
orders the commands among the agent's runs.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.config import RepoConfig
from agent_build_kit.graph.state import EventKind, ResumeEvent
from agent_build_kit.pipeline.stack_runner import RunStatus
from agent_build_kit.pipeline.unit_store import Cause, RequeueReason
from agent_build_kit.pipeline.units import FAILED, IN_REVIEW
from tests.conftest import make_installation, workspace_config
from tests.environment_fakes import SYNC_FAILED_OUTPUT, FakeEnvironment
from tests.factories import git, init_repo
from tests.graph_driver import fresh, tick
from tests.runner_fakes import Recorder

UNIT = "add-marker/1"
MANIFEST = "manifest.toml"
RESUME = ResumeEvent(
    kind=EventKind.REQUEUE, requeue=RequeueReason.RESUME, reason="environment restored"
)


class Habitat:
    """A checkout of `app` with a manifest on `main` and a worktree of it for the unit."""

    def __init__(
        self,
        tmp_path: Path,
        env: FakeEnvironment | None,
        *,
        platform: FakeEnvironment | None = None,
    ) -> None:
        self.env = env
        self.root = tmp_path / "meta"
        checkout = self.root / "checkouts" / "app"
        init_repo(checkout)
        (checkout / MANIFEST).write_text('widget = "1"\n')
        git(checkout, "add", "-A")
        git(checkout, "commit", "-q", "-m", "base")
        self.tree = tmp_path / "tree"
        git(checkout, "worktree", "add", "-q", "-b", f"spec/{UNIT}", str(self.tree), "main")
        repos = {
            name: repo.model_dump(mode="json")
            for name, repo in workspace_config(self.root).repos.items()
        }
        if env is not None:
            repos["app"]["environment"] = env.config()
        if platform is not None:
            repos["platform"]["environment"] = platform.config()
        make_installation(self.root, repos=repos)

    def repo(self) -> RepoConfig:
        """The configuration the runner is handed for the repository being built."""
        return RepoConfig.model_validate(
            workspace_config(self.root).repos["app"].model_dump(mode="json")
            | ({"environment": self.env.config()} if self.env else {})
        )

    def edit_manifest(self) -> None:
        """What the unit's agent does: change the manifest and commit it to the branch."""
        (self.tree / MANIFEST).write_text('widget = "9"\n')
        git(self.tree, "add", "-A")
        git(self.tree, "commit", "-q", "-m", "edit the manifest")


def drive(
    tmp_path: Path,
    habitat: Habitat,
    recorder: Recorder,
    *,
    agent_edits: dict[str, Callable[[], None]] | None = None,
    event: ResumeEvent | None = None,
):
    """One tick over `recorder`, with the repository's configuration on the runner and
    the agent's runs and tier 1 entered in the environment's call log."""
    note = habitat.env.note if habitat.env else (lambda name: None)
    edits = agent_edits or {}

    def run(prompt: str, **kwargs: Any) -> str:
        reply = recorder.claude(prompt, **kwargs)
        kind = recorder.events[-1]
        note(kind)
        if kind in edits:
            edits[kind]()
        return reply

    def tier1(**kwargs: Any) -> tuple[bool, str]:
        note("tier1")
        return recorder.tier1(**kwargs)

    return tick(
        tmp_path, recorder, event=event, run=run, run_tier1=tier1, repo_config=habitat.repo()
    )


def sequence(env: FakeEnvironment) -> list[str]:
    """What happened, in order, without the health checks, which the pipeline may repeat."""
    return [call for call in env.calls() if call != "check"]


def test_a_unit_that_edits_a_manifest_has_sync_run_before_its_next_tier_1(tmp_path: Path) -> None:
    env = FakeEnvironment(tmp_path / "control", inputs=(MANIFEST,))
    habitat = Habitat(tmp_path, env)
    recorder = fresh(tmp_path)

    outcome = drive(tmp_path, habitat, recorder, agent_edits={"claude:impl": habitat.edit_manifest})

    assert outcome.status == "open"
    assert sequence(env) == ["sync", "claude:tests", "claude:impl", "sync", "tier1"]
    calls = env.calls()
    assert calls[calls.index("tier1") - 1] == "check", "the check came after sync, before tier 1"


def test_unchanged_inputs_run_no_sync_before_a_later_tier_1(tmp_path: Path) -> None:
    env = FakeEnvironment(tmp_path / "control", inputs=(MANIFEST,))
    habitat = Habitat(tmp_path, env)
    recorder = fresh(tmp_path)
    recorder.tier1_results = [(False, "E assert 1 == 2"), (True, "")]

    outcome = drive(tmp_path, habitat, recorder)

    assert outcome.status == "open"
    assert "claude:fix_checks" in recorder.events
    assert sequence(env).count("tier1") == 2
    assert sequence(env).count("sync") == 1, "synced once, for the fresh worktree"


def test_a_fresh_worktree_runs_sync_and_check_before_the_tests_node(tmp_path: Path) -> None:
    env = FakeEnvironment(tmp_path / "control", inputs=(MANIFEST,))
    habitat = Habitat(tmp_path, env)
    recorder = fresh(tmp_path)

    drive(tmp_path, habitat, recorder)

    assert env.calls()[:3] == ["sync", "check", "claude:tests"]


@pytest.mark.parametrize("breakage", ["check", "sync"])
def test_a_broken_environment_with_the_bases_inputs_fails_the_unit_with_the_environment_cause(
    tmp_path: Path, breakage: str
) -> None:
    env = FakeEnvironment(tmp_path / "control", inputs=(MANIFEST,))
    habitat = Habitat(tmp_path, env)
    recorder = fresh(tmp_path)
    if breakage == "check":
        env.break_it()
    else:
        env.fail_sync()

    outcome = drive(tmp_path, habitat, recorder)

    assert outcome.status == RunStatus.FAILED
    stored = recorder.store.get(UNIT)
    assert (stored.state, stored.cause) == (FAILED, Cause.ENVIRONMENT)
    assert stored.feedback == "", "nothing for an agent to fix is saved"
    assert recorder.prompts == [], "no agent round was spent"
    assert "tier1" not in env.calls()


def test_such_a_unit_resumes_when_a_later_check_passes(tmp_path: Path) -> None:
    env = FakeEnvironment(tmp_path / "control", inputs=(MANIFEST,))
    habitat = Habitat(tmp_path, env)
    recorder = fresh(tmp_path)
    env.break_it()
    drive(tmp_path, habitat, recorder)
    assert (recorder.store.get(UNIT).state, recorder.store.get(UNIT).cause) == (
        FAILED,
        Cause.ENVIRONMENT,
    )

    env.mend()
    drive(tmp_path, habitat, recorder, event=RESUME)
    outcome = drive(tmp_path, habitat, recorder)

    assert outcome.status == "open"
    assert recorder.store.get(UNIT).state == IN_REVIEW
    assert "claude:fix_checks" not in recorder.events


def test_a_failing_sync_after_the_units_own_manifest_change_goes_to_the_fix_round(
    tmp_path: Path,
) -> None:
    env = FakeEnvironment(tmp_path / "control", inputs=(MANIFEST,))
    habitat = Habitat(tmp_path, env)
    recorder = fresh(tmp_path)

    def unsatisfiable() -> None:
        habitat.edit_manifest()
        env.fail_sync()

    def satisfiable() -> None:
        env.fail_sync(failing=False)

    outcome = drive(
        tmp_path,
        habitat,
        recorder,
        agent_edits={"claude:impl": unsatisfiable, "claude:fix_checks": satisfiable},
    )

    assert outcome.status == "open"
    stored = recorder.store.get(UNIT)
    assert (stored.state, stored.cause) != (FAILED, Cause.ENVIRONMENT)
    order = env.calls()
    assert "claude:fix_checks" in order, "the failure went to the fix round"
    assert order.index("claude:fix_checks") < order.index("tier1"), "tier 1 waited for the fix"
    fix_prompt = next(prompt for prompt in recorder.prompts if "checks (lint" in prompt)
    assert SYNC_FAILED_OUTPUT in fix_prompt, "the sync output is the feedback"


def test_a_repository_without_the_section_syncs_and_checks_nothing(tmp_path: Path) -> None:
    other = FakeEnvironment(tmp_path / "control", inputs=(MANIFEST,))
    habitat = Habitat(tmp_path, None, platform=other)
    recorder = fresh(tmp_path)

    outcome = drive(tmp_path, habitat, recorder)

    assert outcome.status == "open"
    assert other.calls() == []
    assert "tier1" in recorder.events
