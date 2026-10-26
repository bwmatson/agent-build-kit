"""A confined step runs the pipeline's own `abk`, and a command the sandbox refuses to exec is said
in the run log with its path (spec: sandbox-abk-exec). The backend is a stand-in that enforces the
policy on the program a step starts and, inside it, on every file it opens in the planning repo;
the program is a real entry-point script, run the way an agent runs it, with the step's env."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from agent_build_kit.config import models
from agent_build_kit.pipeline.transcript import TranscriptEvent
from agent_build_kit.pipeline.wiring import build_run
from agent_build_kit.runtimes import AgentRequest, AgentResult
from agent_build_kit.sandboxes import Coverage
from tests.pipeline.test_wiring_sandbox import Recording, install
from tests.sandboxes.policy_support import reads, writes

PRE_COMMIT = "repos: []\n"

# What the entry point runs before the kit: refuses any open of a file under the planning repo
# that the policy does not list, as the sandbox would (a file that is not there is not found, not
# denied), with the error a denied open gives.
GUARD = """\
import json, os, sys
from pathlib import Path

guarded = Path(os.environ["ABK_TEST_GUARD"])
granted = [Path(p) for p in json.loads(os.environ["ABK_TEST_GRANTED"])]


def refuse(event, args):
    if event != "open" or not isinstance(args[0], (str, Path)):
        return
    path = Path(args[0]).resolve()
    listed = any(path.is_relative_to(g) for g in granted)
    if path.exists() and path.is_relative_to(guarded) and not listed:
        raise PermissionError(13, "Permission denied", str(path))


sys.addaudithook(refuse)
from agent_build_kit.cli import main

sys.exit(main())
"""


def entry_point(folder: Path) -> Path:
    """A script as an installer writes one: it starts the kit with the interpreter that installed
    it, behind the guard."""
    script = folder / "bin" / "abk"
    script.parent.mkdir(parents=True)
    guard = folder / "bin" / "guard.py"
    guard.write_text(GUARD)
    script.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{guard}" "$@"\n')
    script.chmod(0o755)
    return script


class Executing(Recording):
    """Starts each command the policy lets it read, with the step's env, and refuses the rest, as
    a real backend would; a refusal reaches the run as the tool result the agent's shell printed.
    The child cannot open a file under `guarded` that the policy does not list."""

    def __init__(self, commands: list[list[str]], guarded: Path) -> None:
        super().__init__()
        self.commands = commands
        self.guarded = guarded
        self.done: list[subprocess.CompletedProcess[str]] = []
        self.refused: list[str] = []

    def run(self, request: AgentRequest) -> AgentResult:
        assert request.policy is not None and request.policy.sandbox is not None
        policy = request.policy.sandbox
        granted = [str(p) for p in (*policy.read, *policy.write)]
        env = {
            **os.environ,
            **request.env,
            "ABK_TEST_GUARD": str(self.guarded.resolve()),
            "ABK_TEST_GRANTED": json.dumps(granted),
        }
        for argv in self.commands:
            if not reads(policy, Path(argv[0])):
                self.refused.append(argv[0])
                if request.on_record:
                    request.on_record(
                        TranscriptEvent(
                            kind="tool_result", text=f"bash: {argv[0]}: Permission denied"
                        )
                    )
                continue
            self.done.append(
                subprocess.run(
                    argv, cwd=request.cwd, env=env, capture_output=True, text=True, check=False
                )
            )
        return super().run(request)


class Saying(Recording):
    """A run whose shell printed `text` as a tool result."""

    def __init__(self, text: str) -> None:
        super().__init__()
        self.text = text

    def run(self, request: AgentRequest) -> AgentResult:
        if request.on_record:
            request.on_record(TranscriptEvent(kind="tool_result", text=self.text))
        return super().run(request)


class Scene:
    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.tmp = tmp_path
        self.root, self.main = install(tmp_path, enabled=True)
        (self.root / ".env").write_text("ABK_ADO_PAT=sentinel-credential\n")
        prefix = tmp_path / "process" / "venv"
        self.script = entry_point(prefix)
        (tmp_path / "process" / "base").mkdir()
        monkeypatch.setattr(sys, "prefix", str(prefix))
        monkeypatch.setattr(sys, "base_prefix", str(tmp_path / "process" / "base"))
        real = shutil.which
        monkeypatch.setattr(
            shutil,
            "which",
            lambda name, *a, **k: str(self.script) if name == "abk" else real(name, *a, **k),
        )

    def stage(self, content: str = PRE_COMMIT) -> str:
        staged = self.main / ".abk" / "proposed" / "root.yaml"
        staged.parent.mkdir(parents=True)
        staged.write_text(content)
        return ".abk/proposed/root.yaml"

    def abk(self, *words: str) -> list[str]:
        return [str(self.script), *words]

    def step(self, commands: list[list[str]], lines: list[str] | None = None) -> Executing:
        runtime = Executing(commands, self.root)
        self.run(runtime, lines)
        return runtime

    def run(self, runtime: Recording, lines: list[str] | None = None) -> None:
        build_run(
            runtime=runtime,
            planning_repo=self.root,
            sandbox_repo="app",
            log=(lines if lines is not None else []).append,
        )("Go.", cwd=self.main, model=models().implement)


@pytest.fixture
def scene(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Scene:
    return Scene(tmp_path, monkeypatch)


def test_a_confined_step_installs_a_staged_file_with_abk(scene: Scene) -> None:
    staged = scene.stage()

    runtime = scene.step([scene.abk("install-config", staged, ".pre-commit-config.yaml")])

    assert runtime.refused == []
    (done,) = runtime.done
    assert done.returncode == 0, done.stderr
    assert (scene.main / ".pre-commit-config.yaml").read_text() == PRE_COMMIT


def test_a_confined_step_runs_abk_version(scene: Scene) -> None:
    runtime = scene.step([scene.abk("--version")])

    assert runtime.refused == []
    (done,) = runtime.done
    assert done.stdout.startswith("abk "), done.stderr


def test_the_installation_is_read_and_not_written(scene: Scene) -> None:
    runtime = scene.step([])

    (request,) = runtime.requests
    assert request.policy is not None and request.policy.sandbox is not None
    policy = request.policy.sandbox
    assert reads(policy, scene.script)
    assert not writes(policy, scene.script)
    assert reads(policy, scene.root / "abk.yaml")
    assert not writes(policy, scene.root / "abk.yaml")
    assert not reads(policy, scene.root / ".env")


def test_the_planning_repo_s_other_folders_and_another_repository_stay_unreadable(
    scene: Scene,
) -> None:
    other = scene.tmp / "platform" / "tool"
    other.parent.mkdir()
    other.write_text("#!/bin/sh\n")
    readme = scene.root / "README.md"
    readme.write_text("text\n")
    env = scene.root / ".env"

    runtime = scene.step(
        [[str(scene.script), "--version"], [str(other)], [str(readme)], [str(env)]]
    )

    assert runtime.refused == [str(other), str(readme), str(env)]
    assert len(runtime.done) == 1


def test_a_command_the_sandbox_refused_to_exec_shows_in_the_log_naming_the_path(
    scene: Scene,
) -> None:
    elsewhere = scene.tmp / "elsewhere" / "bin" / "abk"
    elsewhere.parent.mkdir(parents=True)
    elsewhere.write_text("#!/bin/sh\n")
    lines: list[str] = []

    scene.step([[str(elsewhere), "--version"]], lines)

    said = [line for line in lines if line.startswith("sandbox:") and str(elsewhere) in line]
    assert said, lines


def test_a_command_that_ran_is_not_reported_as_refused(scene: Scene) -> None:
    lines: list[str] = []

    runtime = scene.step([scene.abk("--version")], lines)

    assert len(runtime.done) == 1
    assert not [line for line in lines if line.startswith("sandbox:")], lines


def test_a_denial_of_a_file_the_policy_grants_is_not_the_sandbox_s(scene: Scene) -> None:
    script = scene.main / "scripts" / "run.sh"
    lines: list[str] = []

    scene.run(Saying(f"bash: {script}: Permission denied"), lines)

    assert not [line for line in lines if line.startswith("sandbox:")], lines


class Uncovered(Saying):
    """A runtime that confines less than the repo requires, so its step runs unconfined."""

    sandbox_coverage = Coverage.NONE


def test_on_a_runtime_that_does_not_confine_a_denial_is_not_the_sandbox_s(scene: Scene) -> None:
    elsewhere = scene.tmp / "elsewhere" / "run.sh"
    lines: list[str] = []

    scene.run(Uncovered(f"bash: {elsewhere}: Permission denied"), lines)

    assert not [line for line in lines if line.startswith("sandbox:") and "does not let" in line]


def test_a_denial_printed_under_a_link_to_a_granted_folder_is_not_the_sandbox_s(
    scene: Scene,
) -> None:
    link = scene.tmp / "link"
    link.symlink_to(scene.main)
    lines: list[str] = []

    scene.run(Saying(f"bash: {link}/scripts/run.sh: Permission denied"), lines)

    assert not [line for line in lines if line.startswith("sandbox:")], lines


def test_a_denial_of_a_path_the_policy_does_not_grant_is_the_sandbox_s(scene: Scene) -> None:
    elsewhere = scene.tmp / "elsewhere" / "run.sh"
    lines: list[str] = []

    scene.run(Saying(f"bash: {elsewhere}: Permission denied"), lines)

    assert [line for line in lines if line.startswith("sandbox:") and str(elsewhere) in line]
