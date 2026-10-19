"""The stand-ins the stub check-and-fix loop's tests drive a stubbed build with: the static
checks the runner binds, the working tree's state, and a test agent that fixes what they
name, over the runner fakes of the other build-path tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_build_kit.config import RepoConfig
from agent_build_kit.pipeline.unit_store import UnitStore
from tests.factories import activate_with
from tests.runner_fakes import Recorder


def stubbed_build() -> None:
    """The setting on, with the Python profile of the default repo, which supports stubs; the
    suite's autouse fixture puts the config back."""
    activate_with(builders={"per_group_commits": True})


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
        **options: Any,
    ) -> None:
        super().__init__(store, **options)
        self.checks = checks or [(True, "")]
        self.fixes_change = fixes_change
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
