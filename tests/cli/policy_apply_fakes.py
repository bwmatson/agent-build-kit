"""What `abk policy apply` and `abk policy show` are driven with: a scratch agent home holding a
configuration, an installation whose runtime names a known agent by its command, a recording
runtime that fails on a started agent, and the person at the terminal."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

from agent_build_kit.cli import main
from agent_build_kit.runtimes import known_agents
from agent_build_kit.runtimes.known_agents import (
    KNOWN_AGENTS,
    ApplyFormat,
    ApplyPolicy,
    KnownAgent,
    StartVariant,
    YamlVersion,
)
from tests.runtimes.selectable import SelectableRuntime, select

# The known agent whose row carries an applier, and one whose row does not.
AGENT = next(agent for agent in KNOWN_AGENTS if agent.apply is not None)
DESCRIPTOR: ApplyPolicy = AGENT.apply  # type: ignore[assignment]
BARE = next(agent for agent in KNOWN_AGENTS if agent.apply is None)
RUNTIME = "fake"

# A row whose descriptor has no toolset, added to the table for the tests that need one.
NEUTRAL = KnownAgent(
    name="Neutral Agent",
    program="neutral-agent",
    variants=(StartVariant(argv=("neutral-agent", "serve")),),
    verified="fixture",
    source="fixture",
    apply=ApplyPolicy(
        home_env="NEUTRAL_AGENT_HOME",
        home_default=".neutral-agent",
        file="settings.yml",
        format=ApplyFormat.YAML,
        deny_path=("tools", "deny"),
        yaml_version=YamlVersion.V1_2,
        verified="fixture",
    ),
)

CURRENT_TOOLSET = ["file", "web"]
OWN = ["mine *", "theirs *", "ours *"]


def nested(path: tuple[str, ...], value: Any) -> dict[str, Any]:
    for key in reversed(path):
        value = {key: value}
    return value


def merged(into: dict[str, Any], other: dict[str, Any]) -> dict[str, Any]:
    for key, value in other.items():
        if isinstance(value, dict) and isinstance(into.get(key), dict):
            merged(into[key], value)
        else:
            into[key] = value
    return into


def config_text(descriptor: ApplyPolicy, deny: list[str], toolset: list[str] | None = None) -> str:
    """A configuration holding `deny` at the descriptor's path and, given, `toolset` at its."""
    tree = nested(descriptor.deny_path, deny)
    if toolset is not None and descriptor.toolset is not None:
        merged(tree, nested(descriptor.toolset.path, toolset))
    return yaml.safe_dump(tree)


class Home:
    """A scratch agent home, named by the descriptor's variable for the test."""

    def __init__(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, descriptor: ApplyPolicy = DESCRIPTOR
    ) -> None:
        self.descriptor = descriptor
        self.dir = tmp_path / f"home-{descriptor.home_env.lower()}"
        self.dir.mkdir()
        monkeypatch.setenv(descriptor.home_env, str(self.dir))

    @property
    def config(self) -> Path:
        return self.dir / self.descriptor.file

    @property
    def backup(self) -> Path:
        return self.config.with_name(self.config.name + ".abk-backup")

    def write(self, text: str) -> Path:
        self.config.write_text(text)
        return self.config

    def holds(self, deny: list[str], toolset: list[str] | None = None) -> Path:
        return self.write(config_text(self.descriptor, deny, toolset))

    def files(self) -> list[str]:
        """Every file in the home, so a stray backup or temporary shows."""
        return sorted(path.name for path in self.dir.iterdir())

    def loaded(self) -> Any:
        return yaml.safe_load(self.config.read_text())

    def deny(self) -> list[str]:
        value = self.loaded()
        for key in self.descriptor.deny_path:
            value = value[key]
        return value

    def toolset(self) -> list[str]:
        assert self.descriptor.toolset is not None
        value = self.loaded()
        for key in self.descriptor.toolset.path:
            value = value[key]
        return value


def installation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    command: list[str] | None,
    extra: list[str] | None = None,
    policy_fix: list[str] | None = None,
) -> tuple[Path, SelectableRuntime]:
    """An abk.yaml selecting a registered recording runtime whose entry holds `command`."""
    runtime = select(monkeypatch, SelectableRuntime(RUNTIME))
    entry: dict[str, Any] = {}
    if command:
        entry["command"] = command
    if extra:
        entry["policy_extra"] = extra
    if policy_fix:
        entry["policy_fix"] = policy_fix
    planning = tmp_path / "planning"
    planning.mkdir()
    path = planning / "abk.yaml"
    path.write_text(yaml.safe_dump({"runtime": RUNTIME, "runtimes": {RUNTIME: entry}}))
    return path, runtime


def with_neutral_row(monkeypatch: pytest.MonkeyPatch) -> None:
    """The known-agent table with `NEUTRAL` after the kit's rows, wherever it is read from."""
    table = (*KNOWN_AGENTS, NEUTRAL)
    monkeypatch.setattr(known_agents, "KNOWN_AGENTS", table)


class Terminal:
    """Standard input for a run: each question is answered by the next of `answers`; what was
    printed, and the home's files, when each was asked are kept in `shown` and `homes`. Asking
    with no answer left is a test failure."""

    def __init__(
        self, capsys: pytest.CaptureFixture[str], home: Home | None, *answers: str
    ) -> None:
        self.capsys = capsys
        self.home = home
        self.answers = list(answers)
        self.out = ""
        self.err = ""
        self.shown: list[str] = []
        self.homes: list[list[str]] = []
        self.texts: list[str] = []

    def collect(self) -> None:
        captured = self.capsys.readouterr()
        self.out += captured.out
        self.err += captured.err

    def readline(self, *_: object) -> str:
        self.collect()
        self.shown.append(self.out)
        if self.home is not None:
            self.homes.append(self.home.files())
            self.texts.append(self.home.config.read_text() if self.home.config.exists() else "")
        if not self.answers:
            pytest.fail(f"asked a question with no answer left; shown so far:\n{self.out}")
        return self.answers.pop(0) + "\n"

    @property
    def asked(self) -> int:
        return len(self.shown)


def run_apply(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    config: Path,
    home: Home | None,
    *argv: str,
    answers: tuple[str, ...] = (),
    command: str = "apply",
) -> tuple[int, Terminal]:
    """`abk policy <command> <argv>` with `answers` at the terminal: the exit code, the terminal."""
    terminal = Terminal(capsys, home, *answers)
    monkeypatch.setattr(sys, "stdin", terminal)
    code = main(["--config", str(config), "policy", command, *argv])
    terminal.collect()
    return code, terminal
