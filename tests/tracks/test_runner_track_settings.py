"""The settings a track run sends are what the hook is run with: they must let
the run write its run log, not merely match an expected argv string."""

from __future__ import annotations

import io
import json
import shlex
import subprocess
from pathlib import Path

import pytest

from agent_build_kit.hooks import policy
from agent_build_kit.installation import Installation
from agent_build_kit.runtimes.claude_code import ClaudeCodeRuntime
from agent_build_kit.tracks import runner
from tests.runtimes.claude_cli import FakeClaude, record
from tests.tracks.test_runner import make_installation, project


@pytest.fixture
def inst(tmp_path: Path) -> Installation:
    installation = make_installation(tmp_path / "planning", git={"branch_prefix": "abk/"})
    installation.activate()
    return installation


def test_the_settings_a_track_run_sends_let_it_write_its_run_log(
    inst: Installation, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    app = project(inst)
    app.path.mkdir(parents=True)
    for checkout in (app.path, inst.root):
        subprocess.run(["git", "init", "-q"], cwd=checkout, check=True)
    fake = FakeClaude(stdout=record("done"))
    runner.health(inst, app, runtime=ClaudeCodeRuntime(execute=fake))
    settings = json.loads(fake.argv[fake.argv.index("--settings") + 1])
    command = settings["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
    hook_args = shlex.split(command.split("agent_build_kit.hooks.policy", 1)[1])
    assert hook_args[hook_args.index("--branch-prefix") + 1] == "abk/"

    capsys.readouterr()

    def ask(target: Path) -> str:
        payload = {
            "tool_name": "Write",
            "cwd": str(app.path),
            "tool_input": {"file_path": str(target)},
        }
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
        policy.main(hook_args)
        return capsys.readouterr().out

    assert ask(runner.run_log(inst, app, "health")) == ""
    assert ask(inst.state_dir / "tracked-issues.md") == ""
    assert "deny" in ask(inst.state_dir / "units.json")
    assert "deny" in ask(inst.state_dir / "paused.json")
