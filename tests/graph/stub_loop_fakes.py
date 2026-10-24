"""The stand-ins the stub check-and-fix loop's tests drive a stubbed build with: the static
checks the runner binds, the working tree's state, and a test agent that fixes what they
name, over the runner fakes of the other build-path tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.config import RepoConfig
from agent_build_kit.pipeline.unit_store import FeedbackSource, UnitStore
from tests.factories import activate_with, unit
from tests.runner_fakes import Killed, Recorder


def stubbed_build() -> None:
    """The setting on, with the Python profile of the default repo, which supports stubs; the
    suite's autouse fixture puts the config back."""
    activate_with(builders={"stubbed_tdd_commits": True})


class StubLoop(Recorder):
    """A recorder whose static checks answer from `checks` in order (the last answer once
    they run out), and whose test agent, asked to fix an output, changes the tree unless
    `fixes_change` is false."""

    def __init__(
        self,
        store: UnitStore,
        *,
        checks: list[tuple[bool, str]] | None = None,
        fixes_change: bool = True,
        kill_in_fix: int = 0,
        **options: Any,
    ) -> None:
        super().__init__(store, **options)
        self.checks = checks or [(True, "")]
        self.fixes_change = fixes_change
        self.kill_in_fix = kill_in_fix  # the run dies, once, in this fix call (1-based)
        self.tree = "tree-0"
        self.asked = 0  # static checks run
        self.fix_prompts: list[str] = []

    def run_stub_checks(self, *, cwd: Path) -> tuple[bool, str]:
        self.events.append("stub-checks")
        answer = self.checks[min(self.asked, len(self.checks) - 1)]
        self.asked += 1
        return answer

    def tree_state(self, cwd: Path) -> str:
        return self.tree

    def claude(self, prompt: str, **kwargs: Any) -> str:
        outputs = [output for ok, output in self.checks if not ok and output]
        if any(output in prompt for output in outputs):
            self.prompts.append(prompt)
            self.fix_prompts.append(prompt)
            self.events.append("claude:fix_stub")
            if self.kill_in_fix == len(self.fix_prompts):
                self.kill_in_fix = 0
                raise Killed("claude:fix_stub")
            if self.fixes_change:
                self.tree = f"tree-{len(self.fix_prompts)}"
            return "done"
        return super().claude(prompt, **kwargs)

    def overrides(self, tmp_path: Path) -> dict[str, Any]:
        """The callables and the repo a stubbed build is made over."""
        return dict(
            run_stub_checks=self.run_stub_checks,
            tree_state=self.tree_state,
            repo_config=RepoConfig(path=tmp_path / "checkouts" / "app", slug="example/app"),
        )


def with_three_groups(tmp_path: Path, **options: Any) -> StubLoop:
    """A recorder over a store holding a unit of groups 1, 2 and 3."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit(groups=(1, 2, 3))])
    return StubLoop(store, **options)


def feedback_writes(
    recorder: Recorder, monkeypatch: pytest.MonkeyPatch
) -> list[tuple[str, FeedbackSource]]:
    """Wrap the recorder store's `set_feedback`; the list gains (feedback, source) per write."""
    saved: list[tuple[str, FeedbackSource]] = []
    original = recorder.store.set_feedback

    def record(unit_id: str, feedback: str, **kwargs: Any) -> None:
        saved.append((feedback, kwargs.get("source", FeedbackSource.NONE)))
        original(unit_id, feedback, **kwargs)

    monkeypatch.setattr(recorder.store, "set_feedback", record)
    return saved
