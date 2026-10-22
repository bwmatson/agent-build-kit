"""The stand-ins the tests of the fixers in a build are driven with: a recorder whose tree is
a few files with a content, whose agents leave a file unformatted, whose fixers format every
file that is not, and whose checks pass only on a formatted tree."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_build_kit.pipeline.stack_runner import FixResult
from agent_build_kit.pipeline.unit_store import UnitStore
from tests.graph.stub_loop_fakes import StubLoop

UNFORMATTED = "x = 1  \n"
FORMATTED = "x = 1\n"
UNFORMATTED_LINT = "src/x.py:1:6: W291 trailing whitespace"
FIXERS = "fixers"  # the event the fake fixers record


def formatted(text: str) -> str:
    return text.rstrip() + "\n" if text.strip() else text


class Formatting(StubLoop):
    """A stub-loop recorder with a tree of files. `leaves` maps an agent event (`claude:tests`,
    `claude:impl`, `claude:fix_checks`) to the file that agent leaves unformatted. The fixers
    (`run_fixers`) format every file and report the ones they changed, unless `fixers_change`
    is false; `surprises` maps an agent event to a file that turns up unformatted when the fixers
    run right after it, as one an agent never touched; every commit records the files it held,
    and every check (static or unit-test) records whether the tree was formatted when it ran."""

    def __init__(
        self,
        store: UnitStore,
        *,
        leaves: dict[str, str] | None = None,
        fixers_change: bool = True,
        surprises: dict[str, str] | None = None,
        **options: Any,
    ) -> None:
        super().__init__(store, **options)
        self.leaves = leaves or {}
        self.fixers_change = fixers_change
        self.surprises = surprises or {}
        self.files: dict[str, str] = {}
        self.held: list[tuple[str, dict[str, str]]] = []  # (subject, files) per commit
        self.formatted_at_check: list[bool] = []

    def clean(self) -> bool:
        return all(text == formatted(text) for text in self.files.values())

    def run_fixers(self, *, cwd: Path) -> FixResult:
        if (name := self.surprises.get(self.events[-1])) is not None:
            self.files[name] = UNFORMATTED
        self.events.append(FIXERS)
        if not self.fixers_change:
            return FixResult()
        changed = tuple(name for name, text in self.files.items() if text != formatted(text))
        self.files = {name: formatted(text) for name, text in self.files.items()}
        return FixResult(changed=changed)

    def run_stub_checks(self, *, cwd: Path) -> tuple[bool, str]:
        self.formatted_at_check.append(self.clean())
        if not self.clean():
            self.events.append("stub-checks")
            return False, UNFORMATTED_LINT
        return super().run_stub_checks(cwd=cwd)

    def unit_test(self, **kwargs: Any) -> tuple[bool, str]:
        self.formatted_at_check.append(self.clean())
        return super().unit_test(**kwargs)

    def tree_state(self, cwd: Path) -> str:
        return f"{self.tree}|{sorted(self.files.items())}"

    def claude(self, prompt: str, **kwargs: Any) -> str:
        answer = super().claude(prompt, **kwargs)
        if (name := self.leaves.get(self.events[-1])) is not None:
            self.files[name] = UNFORMATTED
        return answer

    def commit(self, message: str, *, cwd: Path, base: str = "") -> int:
        self.held.append((message.split("\n", 1)[0], dict(self.files)))
        return super().commit(message, cwd=cwd, base=base)

    def overrides(self, tmp_path: Path) -> dict[str, Any]:
        return {**super().overrides(tmp_path), "run_fixers": self.run_fixers}

    def held_by(self, prefix: str) -> dict[str, str]:
        """The files the first commit whose subject starts with `prefix` held."""
        return next(files for subject, files in self.held if subject.startswith(prefix))

    def fixer_lines(self) -> list[str]:
        return [line for line in self.logged if line.startswith("fixers")]
