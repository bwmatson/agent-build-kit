"""What `abk init`'s guided policy step is driven with: a runtime whose check reads the
spellings still open from a policy file, fix commands that are small real scripts which
patch that file, and the person at the terminal answering in order."""

from __future__ import annotations

import stat
from collections.abc import Sequence
from pathlib import Path

import pytest
import yaml

from agent_build_kit.cli import init as init_cmd
from agent_build_kit.cli import main
from agent_build_kit.pipeline.command_spellings import SpellingName, probe_rows
from agent_build_kit.runtimes import AgentRuntime, PolicyReport
from tests.cli.test_init import init_args
from tests.factories import recognised_planning
from tests.runtimes.selectable import (
    AMEND,
    OPEN_SPELLING,
    SelectableRuntime,
    select,
    spelling_report,
)
from tests.spelling_rows import PUSH

AMEND_ROW = (AMEND, OPEN_SPELLING)
PUSH_ROW = (PUSH, OPEN_SPELLING)
MOST_ASKS = 20


class PolicyFileRuntime(SelectableRuntime):
    """A runtime whose check reports as unrefused the rows listed in its policy file, one
    `class|spelling` per line: what a fix patches, as an agent's own configuration is."""

    def __init__(self, name: str, policy_file: Path, *, log: list[str]) -> None:
        super().__init__(name, log=log)
        self.policy_file = policy_file

    def check_policy(self, cwd: Path) -> PolicyReport:
        self.checked.append(cwd)
        self.log.append("check")
        lines = self.policy_file.read_text().splitlines()
        rows = {(label, SpellingName(spelling)) for label, spelling in map(_row, lines)}
        return spelling_report(open_rows=rows)


def _row(line: str) -> tuple[str, str]:
    label, spelling = line.split("|")
    return label, spelling


def policy_file(path: Path, *rows: tuple[str, SpellingName]) -> Path:
    """A policy file leaving `rows` unrefused."""
    path.write_text("".join(f"{label}|{spelling.value}\n" for label, spelling in rows))
    return path


def command_of(label: str, spelling: SpellingName) -> str:
    """The command the probe attempts for `label` in `spelling`."""
    return next(s.command for lbl, s in probe_rows() if lbl == label and s.name == spelling)


def script(path: Path, body: str) -> list[str]:
    """An executable shell script at `path`, as the argv that runs it."""
    path.write_text(f"#!/bin/sh\n{body}")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return [str(path)]


# What every fix says first: that it ran, on both streams, and whether its output is being
# captured (a pipe) rather than reaching the person's terminal.
FIX_HEAD = (
    'echo "patching the agent policy"\n'
    'echo "a note on stderr" >&2\n'
    'if [ -p /dev/stdout ]; then echo "stdout was captured"; fi\n'
)


def patching(directory: Path, name: str, *, exits: int = 0, closing: str = AMEND) -> list[str]:
    """A fix that closes `closing`'s rows in the policy file it is given, then exits `exits`."""
    return script(directory / name, FIX_HEAD + f"sed -i '/^{closing}|/d' \"$1\"\nexit {exits}\n")


def changing_nothing(directory: Path, name: str = "noop.sh") -> list[str]:
    return script(directory / name, FIX_HEAD + "exit 0\n")


class Operator:
    """The person at the terminal: each question is answered by the next of `answers`, then
    by `otherwise`. Everything printed since the last question is kept with it, in `screens`,
    so a test reads what the person was shown when asked. A question asked over and over is
    a test failure, not a hang."""

    def __init__(
        self,
        capfd: pytest.CaptureFixture[str],
        *answers: str,
        otherwise: str = "y",
        log: list[str] | None = None,
    ) -> None:
        self.capfd = capfd
        self.answers = list(answers)
        self.otherwise = otherwise
        self.log = log if log is not None else []
        self.screens: list[str] = []

    def __call__(self, prompt: str) -> str:
        if len(self.screens) > MOST_ASKS:
            pytest.fail(f"asked {len(self.screens)} questions; the last was {prompt!r}")
        shown = self.capfd.readouterr()
        self.screens.append(shown.out + shown.err + prompt)
        self.log.append("ask")
        return self.answers.pop(0) if self.answers else self.otherwise


def configured(
    tmp_path: Path,
    app: Path,
    monkeypatch: pytest.MonkeyPatch,
    runtime: AgentRuntime,
    *,
    command: Sequence[str] | None = None,
    policy_fix: Sequence[str] | None = None,
    marker: str | None = None,
) -> Path:
    """A laid-out planning repo whose abk.yaml names `runtime`, registered for the test."""
    planning = recognised_planning(tmp_path / "planning")
    assert main([*init_args(planning, app), "--yes"]) == 0
    path = planning / "abk.yaml"
    raw = yaml.safe_load(path.read_text())
    entry: dict[str, object] = {}
    if command:
        entry["command"] = list(command)
    if policy_fix:
        entry["policy_fix"] = list(policy_fix)
    if marker:
        entry["policy"] = marker
    raw["runtime"] = runtime.name
    raw["runtimes"] = {**raw.get("runtimes", {}), runtime.name: entry}
    path.write_text(yaml.safe_dump(raw))
    select(monkeypatch, runtime)
    return planning


def real_fixes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Let the fix command run for real, so its output goes where a person would see it."""
    monkeypatch.setattr(init_cmd, "run_fix", None)


def recorded(planning: Path, runtime: str) -> dict[str, object]:
    """What abk.yaml holds under `runtimes.<runtime>`."""
    raw = yaml.safe_load((planning / "abk.yaml").read_text())
    return raw.get("runtimes", {}).get(runtime) or {}
